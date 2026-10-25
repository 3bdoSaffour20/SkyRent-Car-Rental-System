from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("", views.my_bookings, name="my_bookings"),
    path("<int:pk>/cancel/", views.cancel_booking, name="cancel"),
]
