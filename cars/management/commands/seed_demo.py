"""
Seed the database with demo users, vehicles and reservations.

    python manage.py seed_demo            # add demo data (skips if cars exist)
    python manage.py seed_demo --clear     # wipe cars/bookings first, then seed
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from bookings.models import Booking
from cars.models import Car

CARS = [
    ("Toyota", "Corolla", 2023, "Sedan", 45, 5, "Automatic", "Petrol",
     "Reliable and efficient daily driver with a smooth ride.",
     "Bluetooth, Backup camera, Apple CarPlay, Cruise control",
     "https://images.unsplash.com/photo-1623869675185-1cc8bcbfc332?w=900&q=70"),
    ("Honda", "Civic", 2022, "Sedan", 48, 5, "Automatic", "Petrol",
     "Sporty compact sedan, great fuel economy for city and highway.",
     "Android Auto, Lane assist, USB-C, Bluetooth",
     "https://images.unsplash.com/photo-1606611013016-969c19ba27bb?w=900&q=70"),
    ("Toyota", "RAV4", 2024, "SUV", 75, 5, "Automatic", "Hybrid",
     "Family SUV with plenty of cargo space and AWD confidence.",
     "AWD, Panoramic roof, Adaptive cruise, Heated seats",
     "https://images.unsplash.com/photo-1568844293986-8d0400bd4745?w=900&q=70"),
    ("Ford", "Explorer", 2023, "SUV", 89, 7, "Automatic", "Petrol",
     "Three-row SUV for the whole crew — comfortable on long trips.",
     "7 seats, Tow package, 4G Wi-Fi, Navigation",
     "https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?w=900&q=70"),
    ("BMW", "5 Series", 2023, "Luxury", 145, 5, "Automatic", "Petrol",
     "Executive sedan with premium comfort and effortless power.",
     "Leather seats, Harman Kardon, Heads-up display, Massage seats",
     "https://images.unsplash.com/photo-1555215695-3004980ad54e?w=900&q=70"),
    ("Mercedes-Benz", "C-Class", 2024, "Luxury", 160, 5, "Automatic", "Petrol",
     "Refined luxury compact with the latest MBUX infotainment.",
     "Ambient lighting, Burmester audio, 360 camera, Keyless go",
     "https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?w=900&q=70"),
    ("Tesla", "Model 3", 2024, "Electric", 120, 5, "Automatic", "Electric",
     "All-electric sedan with Autopilot and a 350 km range.",
     "Autopilot, Glass roof, Supercharger access, Premium audio",
     "https://images.unsplash.com/photo-1560958089-b8a1929cea89?w=900&q=70"),
    ("Nissan", "Leaf", 2023, "Electric", 70, 5, "Automatic", "Electric",
     "Compact EV, perfect for zero-emission city driving.",
     "e-Pedal, ProPILOT, Heated seats, Fast charging",
     "https://images.unsplash.com/photo-1593941707882-a5bba14938c7?w=900&q=70"),
    ("Volkswagen", "Transporter", 2022, "Van", 95, 8, "Manual", "Diesel",
     "Spacious van for group travel, moves and weekend getaways.",
     "8 seats, Rear camera, Air conditioning, Large cargo",
     "https://images.unsplash.com/photo-1527786356703-4b100091cd2c?w=900&q=70"),
    ("Ford", "Mustang GT", 2023, "Sports", 210, 4, "Manual", "Petrol",
     "Iconic V8 muscle car — an unforgettable driving experience.",
     "V8 engine, Sport exhaust, Launch control, Track apps",
     "https://images.unsplash.com/photo-1494976388531-d1058494cdd8?w=900&q=70"),
    ("Toyota", "Hilux", 2023, "Pickup", 85, 5, "Manual", "Diesel",
     "Tough double-cab pickup ready for work sites and trails.",
     "4x4, Bed liner, Tow hooks, Bluetooth",
     "https://images.unsplash.com/photo-1595758228888-1a4a4d2c8b6d?w=900&q=70"),
    ("Honda", "Fit", 2022, "Hatchback", 38, 5, "Automatic", "Petrol",
     "Compact hatchback that's easy to park and gentle on fuel.",
     "Magic seats, Backup camera, Bluetooth, USB",
     "https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?w=900&q=70"),
]

USERS = [
    # username, password, email, first, last, is_staff
    ("admin", "admin12345", "admin@skyrent.example", "Amina", "Manager", True),
    ("dana", "customer12345", "dana@example.com", "Dana", "Carter", False),
    ("marcus", "customer12345", "marcus@example.com", "Marcus", "Reyes", False),
]


class Command(BaseCommand):
    help = "Seed demo data: users, cars and reservations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear", action="store_true",
            help="Delete existing cars and reservations before seeding.",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if options["clear"]:
            Booking.objects.all().delete()
            Car.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared cars and reservations."))

        # --- users ------------------------------------------------------- #
        for username, password, email, first, last, staff in USERS:
            if not User.objects.filter(username=username).exists():
                User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first,
                    last_name=last,
                    is_staff=staff,
                )
                self.stdout.write(self.style.SUCCESS(f"Created user '{username}' ({'manager' if staff else 'customer'})"))

        # --- cars -------------------------------------------------------- #
        if Car.objects.exists():
            self.stdout.write(self.style.WARNING("Cars already exist — skipped vehicle seeding. Use --clear to reseed."))
        else:
            for make, model, year, cat, rate, seats, trans, fuel, desc, feats, img in CARS:
                Car.objects.create(
                    make=make, model=model, year=year, category=cat,
                    daily_rate=Decimal(rate), seating_capacity=seats,
                    transmission=trans, fuel_type=fuel, description=desc,
                    features=feats, image_url=img, location="Main Branch",
                )
            self.stdout.write(self.style.SUCCESS(f"Added {len(CARS)} vehicles to the fleet."))

        # --- demo reservations ------------------------------------------- #
        if Booking.objects.exists():
            self.stdout.write(self.style.WARNING("Reservations already exist — skipped."))
        else:
            dana = User.objects.filter(username="dana").first()
            marcus = User.objects.filter(username="marcus").first()
            cars = list(Car.objects.all())
            today = date.today()

            samples = [
                (dana, cars[0], -12, -8, Booking.STATUS_COMPLETED, "Ready for pickup on time, thanks!"),
                (dana, cars[6], +3, +7, Booking.STATUS_APPROVED, ""),
                (marcus, cars[9], +5, +6, Booking.STATUS_PENDING, "Weekend trip — hope it's available!"),
                (marcus, cars[2], -20, -15, Booking.STATUS_COMPLETED, ""),
                (dana, cars[4], -2, +2, Booking.STATUS_ACTIVE, "Business trip."),
                (marcus, cars[7], +10, +14, Booking.STATUS_PENDING, ""),
            ]
            for user, car, start_off, end_off, status, notes in samples:
                if not user or not car:
                    continue
                Booking.objects.create(
                    user=user, car=car,
                    pickup_date=today + timedelta(days=start_off),
                    dropoff_date=today + timedelta(days=end_off),
                    pickup_location=car.location,
                    status=status, notes=notes,
                )
            self.stdout.write(self.style.SUCCESS("Added demo reservations."))

        self.stdout.write(self.style.SUCCESS("\nDemo accounts:"))
        self.stdout.write("  manager : admin / admin12345")
        self.stdout.write("  customer: dana  / customer12345")
        self.stdout.write(self.style.WARNING("  Change or delete these before deploying for real!"))
