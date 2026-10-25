from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q, Sum
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from bookings.models import Booking
from cars.forms import CarForm
from cars.models import Car, CatalogSyncLog, VehicleCatalog, VehicleTrim
from carrental.services import CarAPIError, carapi
from carrental.utils import safe_next

from .decorators import manager_required

REVENUE_STATUSES = [Booking.STATUS_ACTIVE, Booking.STATUS_COMPLETED]


def _last_six_months():
    """Return a list of (year, month) tuples, oldest first, for the chart."""
    today = date.today()
    keys, year, month = [], today.year, today.month
    for _ in range(6):
        keys.append((year, month))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    keys.reverse()
    return keys


MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------- #
# Overview / analytics
# --------------------------------------------------------------------------- #
@manager_required
def index(request):
    """Custom management dashboard home: KPIs, charts and recent activity."""
    User = get_user_model()
    bookings = Booking.objects.select_related("user", "car")

    kpis = {
        "cars": Car.objects.count(),
        "cars_available": Car.objects.filter(is_available=True).exclude(
            pk__in=Booking.objects.filter(
                status__in=Booking.OPEN_STATUSES,
                pickup_date__lte=date.today(),
                dropoff_date__gt=date.today(),
            ).values("car_id")
        ).count(),
        "bookings": bookings.count(),
        "pending": bookings.filter(status=Booking.STATUS_PENDING).count(),
        "open": bookings.filter(status__in=Booking.OPEN_STATUSES).count(),
        "customers": User.objects.filter(profile__role="customer").count(),
        "revenue": sum(b.total_price for b in bookings.filter(status__in=REVENUE_STATUSES)),
        "pending_value": sum(
            b.total_price for b in bookings.filter(status=Booking.STATUS_PENDING)
        ),
    }

    # Bookings created per month (last 6 months) ---------------------------
    since = date.today().replace(day=1) - timedelta(days=160)
    monthly_counts = {key: 0 for key in _last_six_months()}
    for b in bookings.filter(created_at__date__gte=since):
        key = (b.created_at.year, b.created_at.month)
        if key in monthly_counts:
            monthly_counts[key] += 1
    peak = max(monthly_counts.values()) or 1
    monthly_chart = [
        {"label": MONTH_ABBR[month], "count": count, "pct": round(count / peak * 100)}
        for (_, month), count in monthly_counts.items()
    ]

    # Fleet mix by category -------------------------------------------------
    category_rows = (
        Car.objects.values("category")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    max_cat = max((r["count"] for r in category_rows), default=1) or 1
    for row in category_rows:
        row["pct"] = round(row["count"] / max_cat * 100)

    # Booking status distribution ------------------------------------------
    total_bookings = bookings.count() or 1
    status_rows = [
        {
            "label": label,
            "value": bookings.filter(status=status).count(),
            "pct": round(bookings.filter(status=status).count() / total_bookings * 100),
        }
        for status, label in Booking.STATUS_CHOICES
    ]

    # Top performing cars ---------------------------------------------------
    top_cars = list(
        Car.objects.annotate(
            booking_count=Count("bookings"),
            revenue=Sum("bookings__total_price", filter=Q(bookings__status__in=REVENUE_STATUSES)),
        )
        .order_by("-booking_count", "-revenue")[:5]
    )
    top_peak = max((c.booking_count for c in top_cars), default=0) or 1
    for car in top_cars:
        car.pct = round(car.booking_count / top_peak * 100)

    recent_bookings = bookings.order_by("-created_at")[:8]
    pending_list = bookings.filter(status=Booking.STATUS_PENDING).select_related("user", "car")[:5]

    last_sync = (
        CatalogSyncLog.objects.filter(
            status__in=[CatalogSyncLog.STATUS_SUCCESS, CatalogSyncLog.STATUS_PARTIAL]
        )
        .order_by("-started_at")
        .first()
    )

    context = {
        "kpis": kpis,
        "monthly_chart": monthly_chart,
        "category_rows": category_rows,
        "status_rows": status_rows,
        "top_cars": top_cars,
        "recent_bookings": recent_bookings,
        "pending_list": pending_list,
        "catalog_model_count": VehicleCatalog.objects.count(),
        "catalog_trim_count": VehicleTrim.objects.count(),
        "catalog_last_synced": (
            VehicleCatalog.objects.order_by("-last_synced_at")
            .values_list("last_synced_at", flat=True)
            .first()
        ),
        "last_sync": last_sync,
        "sync_year_default": last_sync.year if last_sync else date.today().year,
        "sync_logs": CatalogSyncLog.objects.select_related("triggered_by")[:5],
        "carapi_configured": carapi.configured(),
        "carapi_status": carapi.connection_status(),
    }
    return render(request, "dashboard/index.html", context)


@manager_required
@require_POST
def sync_vehicle_catalog(request):
    """
    Explicit, manager-only CarAPI sync. Rental fleet records are never changed.

    The result shown to the manager comes from the database audit log created by
    the service; a success message is only shown when the sync actually
    completed, and partial results are reported as warnings.
    """
    year = request.POST.get("year", "")
    make = request.POST.get("make", "").strip()
    include_specs = request.POST.get("include_specs") == "on"
    try:
        result = carapi.sync(
            year,
            make=make,
            include_specs=include_specs,
            triggered_by=request.user,
        )
    except CarAPIError as exc:
        messages.error(request, f"CarAPI synchronization failed: {exc}")
    except Exception:
        messages.error(
            request,
            "CarAPI synchronization failed unexpectedly. Existing catalog data was preserved.",
        )
    else:
        summary = (
            f"CarAPI sync for {result['year']}: "
            f"{result['imported']} new model(s), {result['updated']} updated, "
            f"{result['trims_imported']} new trim(s), {result['trims_updated']} updated, "
            f"{result['specs_updated']} specification record(s) applied, "
            f"{result['skipped']} skipped, {result['errors']} error(s)."
        )
        if result["status"] == CatalogSyncLog.STATUS_PARTIAL:
            messages.warning(
                request,
                summary + " Completed with warnings: " + " ".join(result.get("warnings", [])),
            )
        else:
            messages.success(request, summary)
    return redirect(f"{reverse('dashboard:index')}#carapi-sync")


@manager_required
@require_POST
def test_carapi_connection(request):
    """Perform one authenticated call to verify credentials without syncing."""
    try:
        result = carapi.test_connection()
    except CarAPIError as exc:
        messages.error(request, f"CarAPI connection test failed: {exc}")
    except Exception:
        messages.error(
            request,
            "CarAPI connection test failed unexpectedly. No catalog data was changed.",
        )
    else:
        latest = f" Latest available year: {result['latest_year']}." if result.get("latest_year") else ""
        subscription = result.get("subscription") or "unknown"
        messages.success(
            request,
            f"CarAPI connection successful ({result['years']} model year(s) available; "
            f"subscription: {subscription}).{latest}",
        )
    return redirect(f"{reverse('dashboard:index')}#carapi-sync")



# --------------------------------------------------------------------------- #
# Fleet management (custom CRUD)
# --------------------------------------------------------------------------- #
@manager_required
def manage_cars(request):
    query = request.GET.get("q", "").strip()
    cars = Car.objects.all().order_by("-created_at")
    if query:
        cars = cars.search(query)
    return render(
        request,
        "dashboard/car_manage.html",
        {"cars": cars, "query": query, "total": Car.objects.count()},
    )


@manager_required
@require_http_methods(["GET", "POST"])
def manage_car_create(request):
    if request.method == "POST":
        form = CarForm(request.POST)
        if form.is_valid():
            car = form.save()
            messages.success(request, f"{car} has been added to the fleet.")
            return redirect("dashboard:manage_cars")
    else:
        form = CarForm()
    return render(
        request,
        "dashboard/car_form.html",
        {"form": form, "title": "Add a new car", "submit_label": "Add car"},
    )


@manager_required
@require_http_methods(["GET", "POST"])
def manage_car_edit(request, pk):
    car = get_object_or_404(Car, pk=pk)
    if request.method == "POST":
        form = CarForm(request.POST, instance=car)
        if form.is_valid():
            form.save()
            messages.success(request, f"{car} has been updated.")
            return redirect("dashboard:manage_cars")
    else:
        form = CarForm(instance=car)
    return render(
        request,
        "dashboard/car_form.html",
        {"form": form, "car": car, "title": f"Edit {car}", "submit_label": "Save changes"},
    )


@manager_required
@require_POST
def manage_car_delete(request, pk):
    car = get_object_or_404(Car, pk=pk)
    try:
        car.delete()
        messages.success(request, f"{car} has been removed from the fleet.")
    except ProtectedError:
        car.is_available = False
        car.save(update_fields=["is_available"])
        messages.warning(
            request,
            f"{car} has reservations on record, so it was marked as unavailable instead of deleted.",
        )
    return redirect("dashboard:manage_cars")


# --------------------------------------------------------------------------- #
# Reservation management
# --------------------------------------------------------------------------- #
@manager_required
def manage_bookings(request):
    status = request.GET.get("status", "")
    bookings = Booking.objects.select_related("user", "car", "user__profile")
    if status in dict(Booking.STATUS_CHOICES):
        bookings = bookings.filter(status=status)

    tabs = [{"value": "", "label": "All", "count": Booking.objects.count()}]
    tabs += [
        {"value": value, "label": label, "count": Booking.objects.filter(status=value).count()}
        for value, label in Booking.STATUS_CHOICES
    ]

    action_meta = {
        Booking.STATUS_APPROVED: {"label": "Approve", "icon": "check2-circle", "cls": "btn-accent"},
        Booking.STATUS_REJECTED: {"label": "Reject", "icon": "x-circle", "cls": "btn-ghost"},
        Booking.STATUS_ACTIVE: {"label": "Start rental", "icon": "key", "cls": "btn-accent"},
        Booking.STATUS_COMPLETED: {"label": "Mark completed", "icon": "check2-all", "cls": "btn-outline-accent"},
        Booking.STATUS_CANCELLED: {"label": "Cancel", "icon": "x-octagon", "cls": "btn-ghost"},
    }

    # Materialize the rows so each one carries its allowed actions
    bookings = list(bookings)
    for b in bookings:
        b.action_list = [
            dict(status=s, **action_meta[s]) for s in b.next_status if s in action_meta
        ]

    labels = dict(Booking.STATUS_CHOICES)

    return render(
        request,
        "dashboard/booking_manage.html",
        {
            "bookings": bookings,
            "tabs": tabs,
            "active_tab": status,
            "active_tab_label": labels.get(status, "All"),
            "status_choices": dict(Booking.STATUS_CHOICES),
            "action_meta": action_meta,
        },
    )


@manager_required
@require_POST
def manage_booking_action(request, pk, status):
    """Approve / reject / start / complete / cancel a reservation."""
    booking = get_object_or_404(Booking, pk=pk)
    allowed = booking.next_status

    if status not in dict(Booking.STATUS_CHOICES):
        messages.error(request, "Unknown status.")
    elif status not in allowed:
        messages.error(
            request,
            f"A booking with status “{booking.get_status_display()}” cannot move to "
            f"“{dict(Booking.STATUS_CHOICES).get(status, status)}”.",
        )
    else:
        booking.status = status
        booking.save(update_fields=["status", "updated_at"])
        messages.success(
            request,
            f"Reservation #{booking.pk} is now “{booking.get_status_display()}”.",
        )

    return redirect(safe_next(request.POST.get("next"), fallback="dashboard:manage_bookings"))


# --------------------------------------------------------------------------- #
# Customer analytics
# --------------------------------------------------------------------------- #
@manager_required
def manage_customers(request):
    User = get_user_model()
    customers = (
        User.objects.filter(is_superuser=False)
        .select_related("profile")
        .annotate(
            booking_count=Count("bookings", distinct=True),
            total_spent=Sum(
                "bookings__total_price",
                filter=Q(bookings__status__in=REVENUE_STATUSES),
            ),
            last_booking=Max("bookings__created_at"),
            open_bookings=Count(
                "bookings", filter=Q(bookings__status__in=Booking.OPEN_STATUSES), distinct=True
            ),
        )
        .order_by("-booking_count", "-total_spent")
    )
    totals = {
        "customers": customers.count(),
        "bookings": Booking.objects.count(),
        "revenue": sum(
            b.total_price for b in Booking.objects.filter(status__in=REVENUE_STATUSES)
        ),
        "active_customers": customers.filter(booking_count__gt=0).count(),
    }
    return render(
        request,
        "dashboard/customer_manage.html",
        {"customers": customers, "totals": totals},
    )
