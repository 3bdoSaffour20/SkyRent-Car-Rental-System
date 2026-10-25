from django.contrib import messages
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from bookings.models import Booking
from carrental.utils import safe_next
from dashboard.decorators import user_is_manager

from .forms import LoginForm, ProfileForm, RegisterForm


def register(request):
    """Customer / manager self-registration."""
    if request.user.is_authenticated:
        return redirect("bookings:my_bookings")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, {user.username}! Your account has been created.")
            return redirect("cars:home")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


def user_login(request):
    """Authenticate using SkyRent's local Django account system."""
    if request.user.is_authenticated:
        return redirect("bookings:my_bookings")

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            default = "dashboard:index" if user_is_manager(user) else "bookings:my_bookings"
            return redirect(safe_next(request.POST.get("next"), fallback=default))
    else:
        form = LoginForm()
    return render(request, "accounts/login.html", {"form": form})


@login_required
def profile(request):
    """Account / profile settings page."""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user.profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user.profile, user=request.user)

    reservations = Booking.objects.for_user(request.user)
    stats = {
        "total": reservations.count(),
        "active": reservations.filter(status=Booking.STATUS_ACTIVE).count(),
        "pending": reservations.filter(status=Booking.STATUS_PENDING).count(),
        "completed": reservations.filter(status=Booking.STATUS_COMPLETED).count(),
        "lifetime_value": sum(
            b.total_price for b in reservations.filter(status__in=[Booking.STATUS_ACTIVE, Booking.STATUS_COMPLETED])
        ),
    }
    context = {"form": form, "stats": stats, "profile": request.user.profile}
    return render(request, "accounts/profile.html", context)
