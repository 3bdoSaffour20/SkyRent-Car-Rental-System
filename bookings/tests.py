from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from cars.models import Car

from .forms import BookingForm
from .models import Booking


class BookingFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="renter",
            password="StrongPass123!",
        )
        self.car = Car.objects.create(
            make="Test",
            model="Sedan",
            year=2024,
            daily_rate=Decimal("50.00"),
            location="Main Branch",
        )
        self.today = timezone.localdate()

    def test_total_is_calculated_from_server_daily_rate(self):
        form = BookingForm(
            {
                "pickup_date": (self.today + timedelta(days=1)).isoformat(),
                "dropoff_date": (self.today + timedelta(days=3)).isoformat(),
                "pickup_location": "Main Branch",
            },
            car=self.car,
        )
        self.assertTrue(form.is_valid(), form.errors)
        booking = form.save(commit=False)
        booking.user = self.user
        booking.car = self.car
        booking.save()
        self.assertEqual(booking.num_days, 2)
        self.assertEqual(booking.total_price, Decimal("100.00"))

    def test_overlapping_reservation_is_rejected(self):
        Booking.objects.create(
            user=self.user,
            car=self.car,
            pickup_date=self.today + timedelta(days=1),
            dropoff_date=self.today + timedelta(days=4),
            status=Booking.STATUS_PENDING,
        )
        form = BookingForm(
            {
                "pickup_date": (self.today + timedelta(days=2)).isoformat(),
                "dropoff_date": (self.today + timedelta(days=3)).isoformat(),
                "pickup_location": "Main Branch",
            },
            car=self.car,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("pickup_date", form.errors)

    def test_return_date_must_be_after_pickup(self):
        form = BookingForm(
            {
                "pickup_date": (self.today + timedelta(days=3)).isoformat(),
                "dropoff_date": (self.today + timedelta(days=3)).isoformat(),
                "pickup_location": "Main Branch",
            },
            car=self.car,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("dropoff_date", form.errors)

    def test_customer_can_cancel_only_open_bookings(self):
        booking = Booking.objects.create(
            user=self.user,
            car=self.car,
            pickup_date=self.today + timedelta(days=1),
            dropoff_date=self.today + timedelta(days=2),
            status=Booking.STATUS_PENDING,
        )
        self.assertTrue(booking.can_be_cancelled_by_user)
        booking.status = Booking.STATUS_COMPLETED
        self.assertFalse(booking.can_be_cancelled_by_user)
