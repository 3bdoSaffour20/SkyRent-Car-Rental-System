"""
Root URL configuration for the Car Rental System.

NOTE: The default Django admin (`/admin/`) is intentionally NOT wired up.
All management is done through the fully custom `/manage/` dashboard.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("", include("cars.urls")),
    path("accounts/", include("accounts.urls")),
    path("bookings/", include("bookings.urls")),
    path("manage/", include("dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
