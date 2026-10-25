from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Booking

# Local imports (kept at the bottom-ish group to mirror other apps)
from carrental.utils import safe_next  # noqa: F401  (used by cancel view)


@login_required
def my_bookings(request):
    """Customer dashboard: active + past reservations."""
    reservations = Booking.objects.for_user(request.user)

    open_bookings = reservations.filter(status__in=Booking.OPEN_STATUSES)
    past_bookings = reservations.exclude(status__in=Booking.OPEN_STATUSES)

    stats = {
        "open": open_bookings.count(),
        "pending": reservations.filter(status=Booking.STATUS_PENDING).count(),
        "approved": reservations.filter(status=Booking.STATUS_APPROVED).count(),
        "active": reservations.filter(status=Booking.STATUS_ACTIVE).count(),
        "past": past_bookings.count(),
        "spent": sum(
            b.total_price
            for b in reservations.filter(
                status__in=[Booking.STATUS_ACTIVE, Booking.STATUS_COMPLETED]
            )
        ),
    }

    return render(
        request,
        "bookings/my_bookings.html",
        {
            "open_bookings": open_bookings,
            "past_bookings": past_bookings,
            "stats": stats,
            "tab": request.GET.get("tab", "active"),
        },
    )


@login_required
@require_POST
def cancel_booking(request, pk):
    """A customer may withdraw a pending or approved reservation."""
    booking = get_object_or_404(Booking, pk=pk, user=request.user)

    if not booking.can_be_cancelled_by_user:
        messages.error(
            request,
            "This reservation can no longer be cancelled. Please contact the office.",
        )
    else:
        booking.status = Booking.STATUS_CANCELLED
        booking.save(update_fields=["status", "updated_at"])
        messages.success(request, "Your reservation has been cancelled.")

    return redirect(safe_next(request.POST.get("next"), fallback="bookings:my_bookings"))
