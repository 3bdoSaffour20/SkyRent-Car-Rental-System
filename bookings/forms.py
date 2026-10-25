from datetime import timedelta

from django import forms
from django.utils import timezone

from accounts.forms import StyledFormMixin
from cars.models import Car

from .models import Booking


class BookingForm(StyledFormMixin, forms.ModelForm):
    """Date-range reservation form shown on the car detail page."""

    class Meta:
        model = Booking
        fields = ["pickup_date", "dropoff_date", "pickup_location", "notes"]
        labels = {
            "pickup_date": "Pickup date",
            "dropoff_date": "Drop-off date",
            "pickup_location": "Pickup location",
            "notes": "Special requests",
        }
        widgets = {
            "pickup_date": forms.DateInput(attrs={"type": "date"}),
            "dropoff_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2, "placeholder": "Anything we should know? (optional)"}),
        }

    def __init__(self, *args, car: Car | None = None, **kwargs):
        self.car = car
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["pickup_date"].widget.attrs["min"] = today.isoformat()
        self.fields["dropoff_date"].widget.attrs["min"] = (
            today + timedelta(days=1)
        ).isoformat()
        if car:
            self.fields["pickup_location"].initial = car.location
        self.fields["pickup_location"].required = False
        self.fields["pickup_location"].widget.attrs.setdefault("placeholder", car.location if car else "Pickup location")

    def clean(self):
        cleaned = super().clean()
        pickup = cleaned.get("pickup_date")
        dropoff = cleaned.get("dropoff_date")

        if pickup and dropoff:
            if dropoff <= pickup:
                self.add_error("dropoff_date", "Drop-off date must be after the pickup date.")
            elif pickup < timezone.localdate():
                self.add_error("pickup_date", "Pickup date cannot be in the past.")
            elif self.car:
                overlap = Booking.objects.filter(
                    car=self.car,
                    status__in=Booking.OPEN_STATUSES,
                    pickup_date__lt=dropoff,
                    dropoff_date__gt=pickup,
                )
                if overlap.exists():
                    self.add_error(
                        "pickup_date",
                        "Sorry, this car is already reserved for the selected dates. "
                        "Please choose a different range.",
                    )
        return cleaned
