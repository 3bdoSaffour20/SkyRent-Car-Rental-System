# SkyRent — Car Rental System

A Django + SQLite car rental application with a custom public site and a
manager-only operations dashboard. The public UI keeps the SkyRent branding and
the existing booking flow, with a refreshed ocean-blue design, live fleet
search, date-aware availability, and a documented server-side CarAPI catalog
integration.

> No Django admin is installed. All management screens live under `/manage/`
> and are protected by the project's own manager role checks.

## Palette

| Role | Color |
|---|---|
| Page background | `#075E91` |
| Navbar | `#064B73` |
| Panels / cards | `#06486F` |
| Accent / highlights | `#58C7F5` |
| Primary button | `#83D0F5` |

The design system lives in `static/css/skyrent.css`; shared navigation and
small enhancements live in `static/js/skyrent.js`.

## Highlights

### Public site
- Sticky, responsive navbar with Home, Browse Cars, Categories, My Bookings,
  About Us, and Contact.
- Guests see Sign In / Register; signed-in users get an account menu with
  Profile, My Bookings, and Logout.
- Hero retains **“Rent the perfect car, hassle-free.”**
- Quick search supports make/model, category, minimum/maximum daily price,
  transmission, fuel type, and pickup/return dates, with client and server
  validation.
- All eight rental categories have consistent outline SVG icons, plus live
  available counts and average daily rental rates computed from `Car` records.
- Vehicle cards show photo, make/model, year, category, daily rate, branch,
  seats, transmission, fuel, availability, View Details, and Book Now.
- Browse Cars supports filtering, sorting, pagination, loading skeletons,
  explicit empty/error states, and a no-JavaScript fallback.
- Date searches exclude vehicles with overlapping open reservations.

### Accounts and reservations
- Registration, login, logout, and profile editing use the existing Django auth
  system and the custom SkyRent UI.
- Reservations are still calculated and stored server-side; client-side price
  estimates are only a convenience.
- Managers can approve, reject, start, complete, or cancel reservations through
  the existing state machine.

### Manager dashboard
- KPIs and charts are computed from the live SQLite database.
- Fleet CRUD, reservation management, and customer analytics remain available.
- CarAPI section shows connection state, catalog model/trim counts, the most
  recent successful sync, per-attempt counts, and recent sync logs.
- Sync and Test connection actions are manager-only and POST-only.

## Architecture

```
carrental/          Project settings, URL root, CarAPI service
accounts/           Auth, Profile (role, contact data)
cars/               Rental fleet (Car), filters, views, catalog models
bookings/           Reservations and availability checks
dashboard/          Custom manager dashboard
templates/          Bootstrap 5 templates and partials
static/css/         SkyRent design system
static/js/          Navigation + progressive enhancements
```

### Two separate vehicle stores

| Store | Purpose | Never used for |
|---|---|---|
| `Car` | SkyRent rental fleet: rates, photos, branch, availability | CarAPI manufacturer data |
| `VehicleCatalog` / `VehicleTrim` | External manufacturer catalog, specs, manufacturer MSRP/invoice | Rental prices, branch, availability, bookings |

CarAPI data cannot change rental rates, rental photos, branches, availability,
or existing reservations. A provider outage leaves the rental fleet and cached
catalog untouched.

## Setup

**Prerequisites:** Python 3.10+ (the project has been run with Python 3.14 and
Django 6.x) and network access only if you plan to sync CarAPI.

```powershell
cd "Car Rentel System"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

Copy-Item .env.example .env
# Edit .env and set a strong DJANGO_SECRET_KEY.
# Add CarAPI credentials only if you want to use catalog sync.

python manage.py migrate
python manage.py seed_demo        # optional demo fleet/users/bookings
python manage.py createsuperuser  # create a manager account
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

Demo accounts created by `seed_demo`:

| Role | Username | Password |
|---|---|---|
| Manager | `admin` | `admin12345` |
| Customer | `dana` | `customer12345` |
| Customer | `marcus` | `customer12345` |

Change or remove demo credentials before deployment.

## Environment variables

`carrental/settings.py` reads `.env` if present. Real process environment values
take precedence over `.env`.

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `true` | Set `false` in production. |
| `DJANGO_SECRET_KEY` | local insecure value | Replace before deployment. |
| `CARAPI_API_TOKEN` | empty | CarAPI token, server-side only. |
| `CARAPI_API_SECRET` | empty | CarAPI secret, server-side only. |
| `CARAPI_BASE_URL` | `https://carapi.app` | Provider base URL. |
| `CARAPI_TIMEOUT` | `25` | HTTP timeout in seconds. |
| `CARAPI_MAX_SYNC_RECORDS` | `5000` | Safety cap per endpoint/sync. |

Legacy `CAR_API_TOKEN` / `CAR_API_SECRET` names are still accepted for existing
local installations. `.env` and `db.sqlite3` are gitignored. Credentials are
never stored in SQLite, templates, browser storage, or log messages.

## CarAPI catalog integration

### Server-side client

`carrental/services.py` implements the provider client and synchronization:

1. `POST /api/auth/login` exchanges the configured token/secret for a JWT.
2. The JWT is cached in Django's server-side cache until shortly before its
   `exp` claim. It is not persisted to SQLite or exposed to the frontend.
3. A `401` invalidates the cached token and retries once after re-authenticating.
4. Requests use documented endpoints:
   - `GET /api/years/v2`
   - `GET /api/models/v2`
   - `GET /api/trims/v2`
   - `GET /api/bodies/v2`
   - `GET /api/engines/v2`
5. Pagination follows `collection.next` links, rejects links outside the
   configured CarAPI host, detects repeated pages, caps page count, and caps
   records with `CARAPI_MAX_SYNC_RECORDS`.
6. Provider model IDs, trim IDs, and years are upserted idempotently. Repeated
   syncs update existing rows instead of duplicating them.
7. Catalog writes run in one transaction. A failed sync does not wipe cached
   catalog data; an audit log records the failed attempt.

The current JWT cache is Django's `LocMemCache`, which is per-process. For a
multi-worker deployment, configure a shared cache backend (for example Redis or
the database cache).

### Manager sync UI

Open `/manage/` as a manager/staff user and use the **CarAPI vehicle catalog**
card:

- Choose a model year.
- Optionally narrow the import to one make.
- Choose whether to include trims, body, and engine specifications.
- Use **Test connection** to verify credentials without writing catalog rows.
- Use **Synchronize catalog** to perform the import.

The dashboard displays the last completed sync counts, error count, skipped
records, timestamps, connection status, and recent attempts. If credentials are
not configured, the buttons remain disabled and the card explains which
environment variables are required.

### Command line

```powershell
python manage.py sync_catalog --year 2020
python manage.py sync_catalog --year 2020 --make Toyota
python manage.py sync_catalog --year 2020 --make Toyota --no-specs
```

The command refuses to run without configured credentials.

### Provider plan limits

CarAPI plans differ. The service checks the requested year against
`/api/years/v2` and reports a clear message if the year is not offered by the
current subscription. Free/demo plans may only expose older years (for example
2015–2020), so requesting the current year can legitimately fail. This is a
provider-plan limitation, not a rental-data error.

Manufacturer `msrp` / `invoice` values are stored only for catalog reference and
are never displayed as SkyRent rental prices. Rental prices always come from
`Car.daily_rate`.

### Verification performed

On 2026-10-25 this workspace was verified against the live provider with the
configured free/demo subscription:

- Connection test: success, 6 model years available, latest year 2020.
- Scoped synchronization: `2020 / Toyota`, 19 models, 196 trims, 392
  specification records applied, 0 skipped, 0 errors.
- Rental fleet and reservations were unchanged by the import: 12 cars and 7
  bookings before and after.
- The real dashboard displayed the resulting catalog counts and sync audit row.

This confirms the documented auth/token flow, pagination, model/trim/spec
relationships and transactional write path against real provider responses. A
full all-make/full-year import and other subscription tiers were not run.

## Search behavior

- `/cars/` with no filters lists the rental fleet; it does not return an empty
  page.
- `CarFilterForm` validates inverted price ranges, partial date ranges, past
  pickup dates, and return dates that are not after pickup.
- When both dates are present, overlapping open bookings are excluded.
- “Available now only” also excludes vehicles currently on rent.
- `/cars/?partial=1` returns only the results grid. The browser uses it for
  skeleton loading while keeping the full-page form submission as a fallback.
- Pagination preserves the active filters.

## Migrations and data preservation

The catalog integration was added with incremental migrations:

- `cars/0004` adds catalog specification fields, `VehicleTrim`, and
  `CatalogSyncLog`.
- `cars/0005` adds rental search indexes.
- `accounts/0003` removes the unused `Profile.api_token` field so provider
  secrets are not kept in SQLite.

Existing rental `Car`, `Booking`, and user records are not recreated by these
migrations. Run:

```powershell
python manage.py makemigrations --check --dry-run
python manage.py migrate
```

## Tests

```powershell
python manage.py check
python manage.py test
```

The test suite covers filter/date validation, fleet search behavior, partial
result rendering, manager access control, CarAPI JWT caching and renewal,
idempotent catalog sync, catalog/fleet separation, and failed-sync preservation.
Provider calls are mocked; tests do not need real CarAPI credentials.

## URL map

| URL | Purpose |
|---|---|
| `/` | Landing page, quick search, categories, featured cars |
| `/cars/` | Fleet search with filters and pagination |
| `/cars/<id>/` | Vehicle detail and reservation widget |
| `/accounts/register/`, `/accounts/login/` | Authentication |
| `/accounts/profile/` | Profile settings |
| `/bookings/` | Customer reservations |
| `/manage/` | Manager dashboard and CarAPI sync |
| `/manage/cars/` | Fleet management |
| `/manage/bookings/` | Reservation management |
| `/manage/customers/` | Customer analytics |

## Limitations

- **Live verification scope:** a real connection test and one scoped
  `2020 / Toyota` synchronization succeeded (see above). Full multi-make/full-year
  imports, other subscription tiers, and provider-side schema changes were not
  exercised.
- CarAPI free/demo data may be limited to older model years; sync validates the
  year and reports the provider's available years.
- Sync is manual. There is no scheduled background job, webhook, or automatic
  refresh.
- The default cache is per-process. Use a shared cache backend in production.
- `ALLOWED_HOSTS`, `DEBUG`, and `SECRET_KEY` defaults are development-oriented.
- Catalog data is not yet surfaced as a public specification search; the public
  catalog searches SkyRent's rental fleet only.

## Security notes

- Provider credentials are read from environment variables / `.env` only.
- JWTs live in the server-side cache; no token is returned to templates.
- Sync endpoints are manager-protected and POST-only; CSRF protection stays on.
- Provider error messages shown to managers are sanitized; response bodies and
  credentials are not logged.
- `next` redirects are restricted to local paths by `carrental.utils.safe_next`.
- Do not commit `.env` or database files containing user data.

## Useful commands

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
python manage.py test
python manage.py sync_catalog --year 2020 --make Toyota
```
# SkyRent-Car-Rental-System
