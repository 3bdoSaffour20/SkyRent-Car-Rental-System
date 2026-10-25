from datetime import timedelta

from django import forms
from django.utils import timezone

from accounts.forms import StyledFormMixin

from .models import Car


class CarForm(StyledFormMixin, forms.ModelForm):
    """Form used inside the custom management dashboard to create / edit cars."""

    class Meta:
        model = Car
        fields = [
            "make", "model", "year", "category", "daily_rate",
            "seating_capacity", "transmission", "fuel_type",
            "image_url", "exterior_color", "interior_color", "mileage",
            "api_id", "description", "features", "location", "is_available",
        ]
        labels = {
            "make": "Make",
            "model": "Model",
            "year": "Year",
            "category": "Category",
            "daily_rate": "Daily rate ($)",
            "seating_capacity": "Seats",
            "transmission": "Transmission",
            "fuel_type": "Fuel type",
            "image_url": "Photo URL",
            "exterior_color": "Exterior Color",
            "interior_color": "Interior Color",
            "mileage": "Mileage",
            "api_id": "API ID",
            "description": "Description",
            "features": "Features",
            "location": "Pickup location",
            "is_available": "Available for rental",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "features": forms.Textarea(
                attrs={"rows": 2, "placeholder": "GPS, Bluetooth, Backup camera, USB ..."}
            ),
        }


class CarFilterForm(StyledFormMixin, forms.Form):
    """GET filter form used by the public car catalog and quick search."""

    SORT_CHOICES = [
        ("", "Recommended"),
        ("rate_asc", "Price: low to high"),
        ("rate_desc", "Price: high to low"),
        ("year_desc", "Newest first"),
        ("seats_desc", "Most seats"),
    ]

    q = forms.CharField(
        required=False,
        label="Make or model",
        widget=forms.TextInput(attrs={"placeholder": "Search make or model ...", "id": "id_q"}),
    )
    make = forms.CharField(
        required=False,
        label="Make",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Toyota"}),
    )
    model = forms.CharField(
        required=False,
        label="Model",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Corolla"}),
    )
    year = forms.IntegerField(
        required=False,
        min_value=1900,
        max_value=2100,
        label="Model year",
        widget=forms.NumberInput(attrs={"placeholder": "Any year", "inputmode": "numeric"}),
    )
    category = forms.ChoiceField(required=False, choices=[("", "All categories")])
    branch = forms.ChoiceField(required=False, choices=[("", "All branches")], label="Pickup branch")
    transmission = forms.ChoiceField(
        required=False, choices=[("", "Any transmission")]
    )
    fuel_type = forms.ChoiceField(required=False, choices=[("", "Any fuel type")])
    min_price = forms.DecimalField(
        required=False, min_value=0, label="Min $/day",
        widget=forms.NumberInput(attrs={"placeholder": "Min", "step": "1", "min": "0"}),
    )
    max_price = forms.DecimalField(
        required=False, min_value=0, label="Max $/day",
        widget=forms.NumberInput(attrs={"placeholder": "Max", "step": "1", "min": "0"}),
    )
    seats = forms.ChoiceField(required=False, choices=[("", "Any seats")])
    pickup_date = forms.DateField(
        required=False,
        label="Pickup date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    dropoff_date = forms.DateField(
        required=False,
        label="Return date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    available = forms.BooleanField(required=False, label="Available now only")
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices += Car.CATEGORY_CHOICES
        self.fields["transmission"].choices += Car.TRANSMISSION_CHOICES
        self.fields["fuel_type"].choices += Car.FUEL_CHOICES
        self.fields["seats"].choices += [
            (str(n), f"{n}+ seats") for n in [2, 4, 5, 6, 7, 8]
        ]
        locations = (
            Car.objects.exclude(location="")
            .values_list("location", flat=True)
            .distinct()
            .order_by("location")
        )
        self.fields["branch"].choices += [(location, location) for location in locations]

        today = timezone.localdate()
        self.fields["pickup_date"].widget.attrs["min"] = today.isoformat()
        self.fields["dropoff_date"].widget.attrs["min"] = (
            today + timedelta(days=1)
        ).isoformat()

    def filter_queryset(self, queryset):
        from bookings.models import Booking

        data = self.cleaned_data
        queryset = queryset.search(data.get("q", ""))

        if data.get("make"):
            queryset = queryset.filter(make__icontains=data["make"].strip())
        if data.get("model"):
            queryset = queryset.filter(model__icontains=data["model"].strip())
        if data.get("category"):
            queryset = queryset.filter(category=data["category"])
        if data.get("branch"):
            queryset = queryset.filter(location=data["branch"])
        if data.get("year"):
            queryset = queryset.filter(year=data["year"])
        if data.get("transmission"):
            queryset = queryset.filter(transmission=data["transmission"])
        if data.get("fuel_type"):
            queryset = queryset.filter(fuel_type=data["fuel_type"])
        if data.get("seats"):
            queryset = queryset.filter(seating_capacity__gte=int(data["seats"]))
        if data.get("min_price") is not None:
            queryset = queryset.filter(daily_rate__gte=data["min_price"])
        if data.get("max_price") is not None:
            queryset = queryset.filter(daily_rate__lte=data["max_price"])

        pickup = data.get("pickup_date")
        dropoff = data.get("dropoff_date")
        if data.get("available"):
            queryset = queryset.filter(is_available=True)
            if not (pickup and dropoff):
                # "Available now" excludes vehicles currently on an open rental.
                today = timezone.localdate()
                busy_now = Booking.objects.filter(
                    status__in=Booking.OPEN_STATUSES,
                    pickup_date__lte=today,
                    dropoff_date__gt=today,
                ).values_list("car_id", flat=True)
                queryset = queryset.exclude(pk__in=busy_now)

        if pickup and dropoff:
            # Date-aware availability: a vehicle is excluded only when an open
            # reservation overlaps the requested window.
            busy_car_ids = (
                Booking.objects.filter(
                    status__in=Booking.OPEN_STATUSES,
                    pickup_date__lt=dropoff,
                    dropoff_date__gt=pickup,
                )
                .values_list("car_id", flat=True)
            )
            queryset = queryset.filter(is_available=True).exclude(pk__in=busy_car_ids)

        sort = data.get("sort")
        ordering = {
            "rate_asc": "daily_rate",
            "rate_desc": "-daily_rate",
            "year_desc": "-year",
            "seats_desc": "-seating_capacity",
        }.get(sort)
        if ordering:
            queryset = queryset.order_by(ordering)
        return queryset

    def clean(self):
        cleaned = super().clean()
        minimum, maximum = cleaned.get("min_price"), cleaned.get("max_price")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error("max_price", "Maximum price must be at least the minimum price.")

        pickup = cleaned.get("pickup_date")
        dropoff = cleaned.get("dropoff_date")
        if bool(pickup) != bool(dropoff):
            missing = "dropoff_date" if pickup else "pickup_date"
            self.add_error(
                missing,
                "Choose both a pickup and a return date to check availability.",
            )
        elif pickup and dropoff:
            if dropoff <= pickup:
                self.add_error("dropoff_date", "Return date must be after the pickup date.")
            elif pickup < timezone.localdate():
                self.add_error("pickup_date", "Pickup date cannot be in the past.")
        return cleaned

