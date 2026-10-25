from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from cars.models import Car


class BookingQuerySet(models.QuerySet):
    def active(self):
        """Bookings that currently block the vehicle (not finished/declined)."""
        return self.filter(status__in=[Booking.STATUS_PENDING, Booking.STATUS_APPROVED, Booking.STATUS_ACTIVE])

    def for_user(self, user):
        return self.filter(user=user)


class Booking(models.Model):
    """A reservation made by a customer for a specific car and date range."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    # Which statuses are visible to the customer as "live" reservations
    OPEN_STATUSES = [STATUS_PENDING, STATUS_APPROVED, STATUS_ACTIVE]

    # Allowed manager transitions
    TRANSITIONS = {
        STATUS_PENDING: [STATUS_APPROVED, STATUS_REJECTED],
        STATUS_APPROVED: [STATUS_ACTIVE, STATUS_CANCELLED, STATUS_REJECTED],
        STATUS_ACTIVE: [STATUS_COMPLETED],
        STATUS_COMPLETED: [],
        STATUS_REJECTED: [],
        STATUS_CANCELLED: [],
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    car = models.ForeignKey(Car, on_delete=models.PROTECT, related_name="bookings")
    pickup_date = models.DateField()
    dropoff_date = models.DateField()
    pickup_location = models.CharField(max_length=120, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} → {self.car} ({self.pickup_date} → {self.dropoff_date})"

    def get_absolute_url(self):
        return reverse("bookings:my_bookings")

    # ------------------------------------------------------------------ #
    # Business logic
    # ------------------------------------------------------------------ #
    @property
    def num_days(self):
        """Rental length in days (minimum 1)."""
        delta = (self.dropoff_date - self.pickup_date).days
        return max(delta, 1)

    @property
    def computed_total(self):
        return self.num_days * self.car.daily_rate

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def can_be_cancelled_by_user(self):
        return self.status in [self.STATUS_PENDING, self.STATUS_APPROVED]

    @property
    def next_status(self):
        """Statuses the manager can move this booking to (used for action buttons)."""
        return self.TRANSITIONS.get(self.status, [])

    def clean(self):
        super().clean()
        if self.pickup_date and self.dropoff_date:
            if self.dropoff_date <= self.pickup_date:
                raise ValidationError({"dropoff_date": "Drop-off date must be after the pickup date."})
            if self.pickup_date < timezone.localdate():
                raise ValidationError({"pickup_date": "Pickup date cannot be in the past."})
            if self.car_id:
                overlap = (
                    Booking.objects.filter(
                        car=self.car,
                        status__in=self.OPEN_STATUSES,
                        pickup_date__lt=self.dropoff_date,
                        dropoff_date__gt=self.pickup_date,
                    )
                    .exclude(pk=self.pk)
                )
                if overlap.exists():
                    raise ValidationError(
                        {"pickup_date": "This car is already reserved for the selected dates."}
                    )

    def save(self, *args, **kwargs):
        """Auto-calculate the total rental cost before persisting."""
        if self.car_id and self.pickup_date and self.dropoff_date:
            self.total_price = self.computed_total
        super().save(*args, **kwargs)
