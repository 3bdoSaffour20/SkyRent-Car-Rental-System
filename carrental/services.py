"""
Server-side CarAPI client and idempotent SQLite catalog synchronization.

Security notes
--------------
* Credentials are read from Django settings (environment / .env), never from
  the browser and never from the database.
* The JWT is cached in Django's server-side cache only. It is not written to
  SQLite, localStorage or any template.
* Error messages returned to the UI are intentionally generic; the provider's
  response body is logged by status code only, never with credentials.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from cars.models import CatalogSyncLog, VehicleCatalog, VehicleTrim

logger = logging.getLogger(__name__)

# Values shipped in .env.example must never be treated as real credentials.
_PLACEHOLDERS = {
    "",
    "your_api_token",
    "your_api_secret",
    "your_api_token_here",
    "your_api_secret_here",
    "changeme",
    "replace-me",
    "replace_me",
}


class CarAPIError(Exception):
    """Base error with a message that is safe to show to managers."""

    code = "carapi_error"

    def __init__(self, message, *, code=None):
        super().__init__(message)
        if code:
            self.code = code


class CarAPIAuthError(CarAPIError):
    code = "auth_error"


class CarAPIUnavailable(CarAPIError):
    code = "unavailable"


def _as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _as_text(value, limit=255):
    if value is None:
        return ""
    return str(value).strip()[:limit]


class CarAPIService:
    """Thin, defensive wrapper around the officially documented CarAPI."""

    AUTH_ENDPOINT = "/api/auth/login"
    TOKEN_CACHE_PREFIX = "carapi:jwt:"
    CLAIMS_CACHE_PREFIX = "carapi:claims:"
    MIN_TOKEN_TTL = 120  # seconds of safety margin before JWT expiry

    # ------------------------------------------------------------------ #
    # Configuration / status
    # ------------------------------------------------------------------ #
    @property
    def base_url(self):
        return getattr(settings, "CARAPI_BASE_URL", "https://carapi.app").rstrip("/")

    @property
    def timeout(self):
        return int(getattr(settings, "CARAPI_TIMEOUT", 25))

    @property
    def max_sync_records(self):
        return max(1, int(getattr(settings, "CARAPI_MAX_SYNC_RECORDS", 5000)))

    @property
    def token(self):
        return str(getattr(settings, "CARAPI_API_TOKEN", "") or "").strip()

    @property
    def secret(self):
        return str(getattr(settings, "CARAPI_API_SECRET", "") or "").strip()

    @property
    def fingerprint(self):
        """Stable, non-reversible cache key component for the credential pair."""
        raw = f"{self.token}:{self.secret}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def configured(self):
        return (
            self.token.lower() not in _PLACEHOLDERS
            and self.secret.lower() not in _PLACEHOLDERS
        )

    @property
    def _token_cache_key(self):
        return f"{self.TOKEN_CACHE_PREFIX}{self.fingerprint}"

    @property
    def _claims_cache_key(self):
        return f"{self.CLAIMS_CACHE_PREFIX}{self.fingerprint}"

    def cached_claims(self):
        if not self.configured():
            return None
        claims = cache.get(self._claims_cache_key)
        return claims if isinstance(claims, dict) else None

    def connection_status(self):
        """
        Non-networked status used by the dashboard. Safe to call on every page
        load: it only inspects credentials and the cached JWT claims.
        """
        if not self.configured():
            return {
                "state": "not_configured",
                "label": "Not configured",
                "subscription": None,
                "expires_at": None,
            }
        claims = self.cached_claims()
        if not claims:
            return {
                "state": "configured",
                "label": "Configured — not connected yet",
                "subscription": None,
                "expires_at": None,
            }
        user_claims = claims.get("user") if isinstance(claims.get("user"), dict) else {}
        expires_at = None
        exp = _as_int(claims.get("exp"))
        if exp:
            expires_at = datetime.fromtimestamp(exp, tz=dt_timezone.utc)
        return {
            "state": "authenticated",
            "label": "Connected",
            "subscription": user_claims.get("subscription") or (
                "active" if user_claims.get("subscribed") else "free/demo"
            ),
            "expires_at": expires_at,
        }

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #
    @staticmethod
    def _decode_jwt_claims(token):
        parts = token.split(".")
        if len(parts) != 3:
            raise CarAPIAuthError("CarAPI returned an invalid authentication token.")
        payload = parts[1]
        padded = payload + "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            claims = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CarAPIAuthError("CarAPI returned an unreadable authentication token.") from exc
        if not isinstance(claims, dict) or not _as_int(claims.get("exp")):
            raise CarAPIAuthError("CarAPI authentication token is missing an expiry.")
        return claims

    def authenticate(self, force=False):
        """Return a cached JWT, requesting a new one only when needed."""
        if not self.configured():
            raise CarAPIAuthError(
                "CarAPI credentials are not configured. Add CARAPI_API_TOKEN and "
                "CARAPI_API_SECRET to the server environment, then restart the app."
            )
        if not force:
            token = cache.get(self._token_cache_key)
            if token:
                return token

        try:
            response = requests.post(
                f"{self.base_url}{self.AUTH_ENDPOINT}",
                json={"api_token": self.token, "api_secret": self.secret},
                headers={"Accept": "text/plain", "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.warning("CarAPI authentication network failure (%s)", type(exc).__name__)
            raise CarAPIUnavailable(
                "CarAPI could not be reached. Check the server's internet connection "
                "and try again; cached catalog data is unchanged."
            ) from exc

        if response.status_code in (400, 401, 403, 422):
            logger.warning("CarAPI authentication rejected (HTTP %s)", response.status_code)
            raise CarAPIAuthError(
                "CarAPI rejected the configured credentials. Verify the API token, "
                "secret and subscription status."
            )
        if response.status_code == 429:
            raise CarAPIError(
                "CarAPI is rate-limiting authentication requests. Wait a minute and try again.",
                code="rate_limited",
            )
        if response.status_code >= 500:
            raise CarAPIUnavailable("CarAPI authentication is temporarily unavailable.")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("CarAPI authentication failed (HTTP %s)", response.status_code)
            raise CarAPIError("CarAPI authentication failed.") from exc

        raw = (response.text or "").strip()
        # The documented response is a plain JWT; tolerate a JSON wrapper too.
        if raw.startswith("{"):
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            raw = str(
                payload.get("access_token")
                or payload.get("token")
                or payload.get("jwt")
                or ""
            ).strip()
        token = raw.strip().strip('"').strip("'")
        claims = self._decode_jwt_claims(token)
        exp = _as_int(claims.get("exp"))
        ttl = exp - int(time.time()) - self.MIN_TOKEN_TTL
        if ttl <= 0:
            raise CarAPIAuthError(
                "CarAPI issued a token that is already expired. Check the server clock."
            )

        cache.set(self._token_cache_key, token, ttl)
        cache.set(self._claims_cache_key, claims, ttl)
        logger.info(
            "CarAPI JWT refreshed (subscription=%s)",
            (claims.get("user") or {}).get("subscription") if isinstance(claims.get("user"), dict) else "unknown",
        )
        return token

    # ------------------------------------------------------------------ #
    # HTTP / pagination
    # ------------------------------------------------------------------ #
    def _resolve_url(self, endpoint):
        """
        Resolve a relative CarAPI path (or a same-host absolute pagination URL)
        without allowing a provider response to redirect the server elsewhere.
        """
        if not isinstance(endpoint, str) or not endpoint:
            raise CarAPIError("CarAPI returned an unsupported endpoint URL.")

        if endpoint.startswith("/api/") and not endpoint.startswith("//"):
            return f"{self.base_url}{endpoint}"

        parsed = urlsplit(endpoint)
        base = urlsplit(self.base_url)
        if (
            parsed.scheme == base.scheme
            and parsed.netloc == base.netloc
            and parsed.path.startswith("/api/")
            and not parsed.username
            and not parsed.password
        ):
            return endpoint
        raise CarAPIError("CarAPI returned an unsupported endpoint URL.")

    def _request_json(self, endpoint, params=None, retry=True):
        url = self._resolve_url(endpoint)
        token = self.authenticate()
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            logger.warning("CarAPI request timed out for %s", endpoint)
            raise CarAPIUnavailable("CarAPI did not respond in time. Cached catalog data is unchanged.") from exc
        except requests.RequestException as exc:
            logger.warning("CarAPI request failed for %s (%s)", endpoint, type(exc).__name__)
            raise CarAPIUnavailable(
                "CarAPI is temporarily unavailable. Cached catalog data is unchanged."
            ) from exc

        if response.status_code == 401 and retry:
            # Token may have been revoked/expired early: refresh once and retry.
            cache.delete(self._token_cache_key)
            cache.delete(self._claims_cache_key)
            self.authenticate(force=True)
            return self._request_json(endpoint, params=params, retry=False)
        if response.status_code == 401:
            raise CarAPIAuthError("CarAPI session could not be refreshed. Sign in again later.")
        if response.status_code == 403:
            raise CarAPIAuthError(
                "The current CarAPI subscription does not allow this endpoint or data range."
            )
        if response.status_code == 404:
            raise CarAPIError("The requested CarAPI endpoint is not available.")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            suffix = f" Try again in {retry_after} seconds." if retry_after else " Try again shortly."
            raise CarAPIError("CarAPI rate limit reached." + suffix, code="rate_limited")
        if response.status_code >= 500:
            raise CarAPIUnavailable("CarAPI is temporarily unavailable (server error).")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("CarAPI request rejected for %s (HTTP %s)", endpoint, response.status_code)
            raise CarAPIError(
                f"CarAPI rejected the request (HTTP {response.status_code})."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("CarAPI returned invalid JSON for %s", endpoint)
            raise CarAPIError("CarAPI returned an invalid response.") from exc
        if not isinstance(payload, (dict, list)):
            raise CarAPIError("CarAPI returned an unexpected response shape.")
        return payload

    @staticmethod
    def _collection(payload):
        """Return (records, next_url, total) from a documented collection payload."""
        if isinstance(payload, list):
            return payload, "", len(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise CarAPIError("CarAPI response did not contain a vehicle data list.")
        collection = payload.get("collection") if isinstance(payload.get("collection"), dict) else {}
        next_url = collection.get("next") or ""
        total = _as_int(collection.get("total"))
        return payload["data"], str(next_url), total

    def _paginate(self, endpoint, params=None):
        """Follow CarAPI `collection.next` links with cycle and volume guards."""
        records = []
        seen_pages = set()
        page_count = 0
        total = None
        truncated = False

        payload = self._request_json(endpoint, params=params)
        while True:
            page_records, next_url, page_total = self._collection(payload)
            page_count += 1
            if page_total is not None:
                total = page_total
            records.extend(page_records)

            if len(records) >= self.max_sync_records:
                over_limit = len(records) > self.max_sync_records
                if over_limit:
                    records = records[: self.max_sync_records]
                if over_limit or next_url:
                    truncated = True
                break
            if not next_url:
                break
            next_target = self._resolve_url(next_url)
            if next_target in seen_pages:
                raise CarAPIError("CarAPI repeated a pagination link; synchronization stopped safely.")
            if page_count >= 100:
                raise CarAPIError("CarAPI pagination limit exceeded.")
            seen_pages.add(next_target)
            payload = self._request_json(next_url)

        return records, {
            "pages": page_count,
            "total": total,
            "truncated": truncated,
            "limit": self.max_sync_records,
        }

    # ------------------------------------------------------------------ #
    # Documented endpoints
    # ------------------------------------------------------------------ #
    def fetch_years(self):
        payload = self._request_json("/api/years/v2")
        values = payload if isinstance(payload, list) else payload.get("data", [])
        years = set()
        for value in values:
            if isinstance(value, dict):
                value = value.get("year") or value.get("value") or value.get("name")
            year = _as_int(value)
            if year is not None:
                years.add(year)
        return sorted(years, reverse=True)

    def fetch_models(self, year, make=None):
        params = {"year": year}
        if make:
            params["make"] = make
        return self._paginate("/api/models/v2", params=params)

    def fetch_trims(self, year, make=None):
        params = {"year": year}
        if make:
            params["make"] = make
        return self._paginate("/api/trims/v2", params=params)

    def fetch_bodies(self, year, make=None):
        params = {"year": year}
        if make:
            params["make"] = make
        return self._paginate("/api/bodies/v2", params=params)

    def fetch_engines(self, year, make=None):
        params = {"year": year}
        if make:
            params["make"] = make
        return self._paginate("/api/engines/v2", params=params)

    def test_connection(self):
        """One authenticated request used by the explicit 'Test connection' button."""
        years = self.fetch_years()
        status = self.connection_status()
        return {
            "years": len(years),
            "latest_year": years[0] if years else None,
            "subscription": status.get("subscription"),
        }

    # ------------------------------------------------------------------ #
    # Synchronization
    # ------------------------------------------------------------------ #
    def _validate_year(self, year):
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise CarAPIError("Select a valid model year.")
        current_year = timezone.now().year
        if not 1900 <= year <= current_year + 2:
            raise CarAPIError(f"Select a model year between 1900 and {current_year + 2}.")
        return year

    @staticmethod
    def _catalog_defaults(record, year):
        return {
            "make_id": _as_int(record.get("make_id")),
            "make": _as_text(record.get("make"), 100),
            "model": _as_text(record.get("name") or record.get("model"), 120),
            "year": year,
            "raw_data": record if isinstance(record, dict) else {},
            "last_synced_at": timezone.now(),
        }

    @staticmethod
    def _trim_defaults(record, catalog, year):
        return {
            "catalog": catalog,
            "make_id": _as_int(record.get("make_id")),
            "model_id": _as_int(record.get("model_id")),
            "submodel_id": _as_int(record.get("submodel_id")),
            "year": _as_int(record.get("year")) or year,
            "make": _as_text(record.get("make"), 100),
            "model": _as_text(record.get("model") or record.get("model_name"), 120),
            "series": _as_text(record.get("series"), 120),
            "submodel": _as_text(record.get("submodel") or record.get("submodel_name"), 120),
            "trim": _as_text(record.get("trim") or record.get("trim_name"), 120),
            "description": _as_text(record.get("description"), 255),
            "msrp": _as_decimal(record.get("msrp")),
            "invoice": _as_decimal(record.get("invoice")),
            "raw_data": record,
            "last_synced_at": timezone.now(),
        }

    @staticmethod
    def _representative_trim(trims):
        """Pick a stable trim to summarise a model without inventing data."""
        def score(trim):
            return (
                bool(trim.seating_capacity),
                bool(trim.body_type),
                bool(trim.fuel_type),
                bool(trim.transmission),
                bool(trim.engine_size),
                trim.horsepower or 0,
            )

        return max(trims, key=score) if trims else None

    def sync(self, year, make="", include_specs=True, triggered_by=None):
        """
        Import/update one year of CarAPI catalog data inside a transaction.

        Returns a result dictionary. On failure the log is marked failed and a
        CarAPIError with a safe message is raised; previously cached catalog
        rows remain untouched because the data write is atomic.
        """
        year = self._validate_year(year)
        make = _as_text(make, 100)
        include_specs = bool(include_specs)
        log = CatalogSyncLog.objects.create(
            year=year,
            make=make,
            include_specs=include_specs,
            status=CatalogSyncLog.STATUS_RUNNING,
            triggered_by=triggered_by if getattr(triggered_by, "is_authenticated", False) else None,
        )
        warnings = []
        counts = {
            "models_imported": 0,
            "models_updated": 0,
            "trims_imported": 0,
            "trims_updated": 0,
            "specs_updated": 0,
            "skipped": 0,
            "error_count": 0,
        }

        try:
            available_years = self.fetch_years()
            if available_years and year not in available_years:
                shown = ", ".join(str(y) for y in available_years[:6])
                raise CarAPIError(
                    f"CarAPI does not offer model year {year} on this subscription. "
                    f"Available years include: {shown}."
                )

            model_rows, model_meta = self.fetch_models(year, make or None)
            if model_meta.get("truncated"):
                warnings.append(
                    f"Model import was capped at {self.max_sync_records} records. "
                    "Synchronize a specific make to cover the remainder."
                )

            with transaction.atomic():
                catalogs = {}
                for record in model_rows:
                    if not isinstance(record, dict):
                        counts["skipped"] += 1
                        continue
                    model_id = _as_int(record.get("id"))
                    defaults = self._catalog_defaults(record, year)
                    if not model_id or not defaults["make"] or not defaults["model"]:
                        counts["skipped"] += 1
                        continue
                    catalog, created = VehicleCatalog.objects.update_or_create(
                        provider="carapi",
                        provider_model_id=model_id,
                        year=year,
                        defaults=defaults,
                    )
                    catalogs[(model_id, year)] = catalog
                    if created:
                        counts["models_imported"] += 1
                    else:
                        counts["models_updated"] += 1

                trim_objects = {}
                if include_specs:
                    # Trims define the provider relationship between models,
                    # bodies and engines.
                    try:
                        trim_rows, trim_meta = self.fetch_trims(year, make or None)
                        if trim_meta.get("truncated"):
                            warnings.append(
                                f"Trim import was capped at {self.max_sync_records} records."
                            )
                        for record in trim_rows:
                            if not isinstance(record, dict):
                                counts["skipped"] += 1
                                continue
                            trim_id = _as_int(record.get("id"))
                            model_id = _as_int(record.get("model_id"))
                            catalog = catalogs.get((model_id, year))
                            defaults = self._trim_defaults(record, catalog, year)
                            if not trim_id or not defaults["make"] or not defaults["model"]:
                                counts["skipped"] += 1
                                continue
                            trim, created = VehicleTrim.objects.update_or_create(
                                provider="carapi",
                                provider_trim_id=trim_id,
                                defaults=defaults,
                            )
                            trim_objects[trim_id] = trim
                            if created:
                                counts["trims_imported"] += 1
                            else:
                                counts["trims_updated"] += 1
                            if catalog is None:
                                counts["skipped"] += 1
                    except CarAPIError as exc:
                        counts["error_count"] += 1
                        warnings.append(f"Trims: {exc}")

                    if trim_objects:
                        body_by_trim = {}
                        try:
                            body_rows, body_meta = self.fetch_bodies(year, make or None)
                            if body_meta.get("truncated"):
                                warnings.append(
                                    f"Body specification import was capped at {self.max_sync_records} records."
                                )
                            for record in body_rows:
                                if not isinstance(record, dict):
                                    counts["skipped"] += 1
                                    continue
                                trim_id = _as_int(record.get("trim_id") or record.get("id"))
                                trim = trim_objects.get(trim_id)
                                if not trim:
                                    counts["skipped"] += 1
                                    continue
                                trim.body_type = _as_text(
                                    record.get("type") or record.get("body_type"), 60
                                )
                                trim.doors = _as_int(record.get("doors"))
                                trim.seating_capacity = _as_int(
                                    record.get("seats") or record.get("seating_capacity")
                                )
                                trim.raw_body = record
                                trim.last_synced_at = timezone.now()
                                trim.save(update_fields=[
                                    "body_type", "doors", "seating_capacity",
                                    "raw_body", "last_synced_at",
                                ])
                                body_by_trim[trim_id] = trim
                                counts["specs_updated"] += 1
                        except CarAPIError as exc:
                            counts["error_count"] += 1
                            warnings.append(f"Body specifications: {exc}")

                        try:
                            engine_rows, engine_meta = self.fetch_engines(year, make or None)
                            if engine_meta.get("truncated"):
                                warnings.append(
                                    f"Engine specification import was capped at {self.max_sync_records} records."
                                )
                            for record in engine_rows:
                                if not isinstance(record, dict):
                                    counts["skipped"] += 1
                                    continue
                                trim_id = _as_int(record.get("trim_id") or record.get("id"))
                                trim = trim_objects.get(trim_id)
                                if not trim:
                                    counts["skipped"] += 1
                                    continue
                                trim.engine_type = _as_text(
                                    record.get("engine_type") or record.get("type"), 60
                                )
                                trim.engine_size = _as_text(
                                    record.get("size") or record.get("engine_size"), 30
                                )
                                trim.cylinders = _as_text(record.get("cylinders"), 30)
                                trim.horsepower = _as_int(
                                    record.get("horsepower_hp") or record.get("horsepower")
                                )
                                trim.fuel_type = _as_text(record.get("fuel_type"), 60)
                                trim.transmission = _as_text(record.get("transmission"), 120)
                                trim.drive_type = _as_text(record.get("drive_type"), 80)
                                trim.raw_engine = record
                                trim.last_synced_at = timezone.now()
                                trim.save(update_fields=[
                                    "engine_type", "engine_size", "cylinders",
                                    "horsepower", "fuel_type", "transmission",
                                    "drive_type", "raw_engine", "last_synced_at",
                                ])
                                counts["specs_updated"] += 1
                        except CarAPIError as exc:
                            counts["error_count"] += 1
                            warnings.append(f"Engine specifications: {exc}")

                    # Summarise each model from its best-populated trim. This is
                    # catalog convenience data only; rental rates stay on Car.
                    grouped = {}
                    for trim in trim_objects.values():
                        if trim.catalog_id:
                            grouped.setdefault(trim.catalog_id, []).append(trim)
                    for catalog in catalogs.values():
                        best = self._representative_trim(grouped.get(catalog.id, []))
                        if not best:
                            continue
                        catalog.submodel = best.submodel
                        catalog.trim = best.trim
                        catalog.body_type = best.body_type
                        catalog.doors = best.doors
                        catalog.seating_capacity = best.seating_capacity
                        catalog.engine = " ".join(
                            part for part in [
                                best.engine_type,
                                f"{best.engine_size}L" if best.engine_size else "",
                                best.cylinders,
                            ] if part
                        )[:160]
                        catalog.fuel_type = best.fuel_type
                        catalog.transmission = best.transmission
                        catalog.drive_type = best.drive_type
                        catalog.horsepower = best.horsepower
                        catalog.description = best.description
                        catalog.msrp = best.msrp
                        catalog.invoice = best.invoice
                        catalog.save(update_fields=[
                            "submodel", "trim", "body_type", "doors",
                            "seating_capacity", "engine", "fuel_type",
                            "transmission", "drive_type", "horsepower",
                            "description", "msrp", "invoice",
                        ])

            status = CatalogSyncLog.STATUS_PARTIAL if warnings else CatalogSyncLog.STATUS_SUCCESS
            message = " ".join(warnings) if warnings else (
                f"Synchronized {len(catalogs)} model(s) and {len(trim_objects)} trim(s) "
                f"for {year}."
            )
            log.status = status
            log.models_imported = counts["models_imported"]
            log.models_updated = counts["models_updated"]
            log.trims_imported = counts["trims_imported"]
            log.trims_updated = counts["trims_updated"]
            log.specs_updated = counts["specs_updated"]
            log.skipped = counts["skipped"]
            log.error_count = counts["error_count"]
            log.message = message
            log.finished_at = timezone.now()
            log.save()

            logger.info(
                "CarAPI sync %s (%s): models +%s/~%s, trims +%s/~%s, specs %s, skipped %s, errors %s",
                year, status, counts["models_imported"], counts["models_updated"],
                counts["trims_imported"], counts["trims_updated"],
                counts["specs_updated"], counts["skipped"], counts["error_count"],
            )
            return {
                "status": status,
                "year": year,
                "make": make,
                "imported": counts["models_imported"],
                "updated": counts["models_updated"],
                "trims_imported": counts["trims_imported"],
                "trims_updated": counts["trims_updated"],
                "specs_updated": counts["specs_updated"],
                "skipped": counts["skipped"],
                "errors": counts["error_count"],
                "warnings": warnings,
                "message": message,
                "log_id": log.pk,
            }
        except CarAPIError as exc:
            logger.warning("CarAPI sync failed for %s (%s)", year, exc.code)
            log.status = CatalogSyncLog.STATUS_FAILED
            log.error_count = max(1, counts["error_count"])
            log.skipped = counts["skipped"]
            log.message = str(exc)
            log.finished_at = timezone.now()
            log.save(update_fields=[
                "status", "error_count", "skipped", "message", "finished_at",
            ])
            raise
        except Exception as exc:  # defensive: never leak internals to the UI
            logger.exception("Unexpected CarAPI sync failure for %s", year)
            log.status = CatalogSyncLog.STATUS_FAILED
            log.error_count = max(1, counts["error_count"])
            log.message = "Synchronization failed unexpectedly. Existing catalog data was preserved."
            log.finished_at = timezone.now()
            log.save(update_fields=[
                "status", "error_count", "message", "finished_at",
            ])
            raise CarAPIError(
                "Synchronization failed unexpectedly. Existing catalog data was preserved."
            ) from exc


carapi = CarAPIService()
