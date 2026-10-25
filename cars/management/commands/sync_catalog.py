"""Explicit CarAPI catalog synchronization from the command line.

Examples:
    python manage.py sync_catalog --year 2024
    python manage.py sync_catalog --year 2024 --make Toyota

The command never touches SkyRent rental cars, rates, branches or bookings.
"""
from django.core.management.base import BaseCommand, CommandError

from carrental.services import CarAPIError, carapi


class Command(BaseCommand):
    help = "Synchronize CarAPI catalog models (and optionally specs) into SQLite."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Model year to synchronize.")
        parser.add_argument("--make", default="", help="Optional make filter to reduce the scope.")
        parser.add_argument(
            "--no-specs",
            action="store_true",
            help="Only import model identities (skip trims, bodies and engines).",
        )

    def handle(self, *args, **options):
        if not carapi.configured():
            raise CommandError(
                "CarAPI credentials are not configured. Set CARAPI_API_TOKEN and "
                "CARAPI_API_SECRET in the server environment."
            )
        self.stdout.write(
            f"Synchronizing CarAPI catalog for {options['year']}"
            f"{' / ' + options['make'] if options['make'] else ''} ..."
        )
        try:
            result = carapi.sync(
                options["year"],
                make=options["make"],
                include_specs=not options["no_specs"],
            )
        except CarAPIError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"[{result['status']}] models: {result['imported']} new, "
                f"{result['updated']} updated; trims: {result['trims_imported']} new, "
                f"{result['trims_updated']} updated; specs applied: "
                f"{result['specs_updated']}; skipped: {result['skipped']}; "
                f"errors: {result['errors']}."
            )
        )
        for warning in result.get("warnings", []):
            self.stdout.write(self.style.WARNING(f"Warning: {warning}"))
