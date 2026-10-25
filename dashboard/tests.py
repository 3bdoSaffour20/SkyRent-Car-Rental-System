from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cars.models import Car, CatalogSyncLog, VehicleCatalog


class ManagerAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_user(
            username="manager",
            password="StrongPass123!",
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username="customer",
            password="StrongPass123!",
        )

    def test_customer_cannot_open_management_dashboard(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("dashboard:index"))
        self.assertRedirects(response, reverse("cars:home"))

    def test_manager_can_open_management_dashboard(self):
        CatalogSyncLog.objects.create(
            year=2024,
            status=CatalogSyncLog.STATUS_SUCCESS,
            finished_at=timezone.now(),
            models_imported=1,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CarAPI vehicle catalog")
        self.assertContains(response, "Recent sync attempts")

    def test_catalog_sync_is_manager_only(self):
        self.client.force_login(self.customer)
        with patch("dashboard.views.carapi.sync") as sync:
            response = self.client.post(reverse("dashboard:sync_catalog"), {"year": "2024"})
        self.assertRedirects(response, reverse("cars:home"))
        sync.assert_not_called()

    def test_manager_sync_reports_real_service_result(self):
        self.client.force_login(self.manager)
        result = {
            "status": CatalogSyncLog.STATUS_SUCCESS,
            "year": 2024,
            "imported": 2,
            "updated": 3,
            "trims_imported": 4,
            "trims_updated": 5,
            "specs_updated": 6,
            "skipped": 1,
            "errors": 0,
            "warnings": [],
        }
        with patch("dashboard.views.carapi.sync", return_value=result) as sync:
            response = self.client.post(
                reverse("dashboard:sync_catalog"),
                {"year": "2024", "make": "Toyota", "include_specs": "on"},
            )
        self.assertRedirects(
            response,
            reverse("dashboard:index") + "#carapi-sync",
            fetch_redirect_response=False,
        )
        sync.assert_called_once()
        self.assertEqual(sync.call_args.kwargs["make"], "Toyota")
        self.assertTrue(sync.call_args.kwargs["include_specs"])

    def test_manager_sync_reports_provider_error(self):
        from carrental.services import CarAPIError

        self.client.force_login(self.manager)
        with patch(
            "dashboard.views.carapi.sync",
            side_effect=CarAPIError("provider unavailable"),
        ):
            response = self.client.post(
                reverse("dashboard:sync_catalog"),
                {"year": "2024"},
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "provider unavailable")

    def test_sync_endpoint_rejects_get(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("dashboard:sync_catalog"))
        self.assertEqual(response.status_code, 405)

    def test_connection_test_endpoint_is_manager_protected(self):
        self.client.force_login(self.customer)
        with patch("dashboard.views.carapi.test_connection") as test_connection:
            response = self.client.post(reverse("dashboard:test_catalog"))
        self.assertRedirects(response, reverse("cars:home"))
        test_connection.assert_not_called()

    def test_connection_test_uses_provider_result(self):
        self.client.force_login(self.manager)
        with patch(
            "dashboard.views.carapi.test_connection",
            return_value={"years": 6, "latest_year": 2020, "subscription": "test"},
        ):
            response = self.client.post(
                reverse("dashboard:test_catalog"), follow=True
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CarAPI connection successful")


class DashboardMetricsTests(TestCase):
    def test_kpis_and_catalog_counts_come_from_database(self):
        User = get_user_model()
        manager = User.objects.create_user(
            username="manager2", password="StrongPass123!", is_staff=True
        )
        Car.objects.create(
            make="Test",
            model="Car",
            year=2024,
            daily_rate=Decimal("50.00"),
            location="Main Branch",
        )
        VehicleCatalog.objects.create(
            provider="carapi",
            provider_model_id=1,
            make="Example",
            model="Model",
            year=2024,
        )
        CatalogSyncLog.objects.create(
            year=2024,
            status=CatalogSyncLog.STATUS_SUCCESS,
            finished_at=timezone.now(),
            models_imported=1,
        )

        self.client.force_login(manager)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["kpis"]["cars"], 1)
        self.assertEqual(response.context["catalog_model_count"], 1)
        self.assertEqual(response.context["last_sync"].models_imported, 1)
        self.assertEqual(response.context["sync_year_default"], 2024)
