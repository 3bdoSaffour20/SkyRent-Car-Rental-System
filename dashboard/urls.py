from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("catalog/sync/", views.sync_vehicle_catalog, name="sync_catalog"),
    path("catalog/test/", views.test_carapi_connection, name="test_catalog"),
    path("cars/", views.manage_cars, name="manage_cars"),
    path("cars/add/", views.manage_car_create, name="manage_car_create"),
    path("cars/<int:pk>/edit/", views.manage_car_edit, name="manage_car_edit"),
    path("cars/<int:pk>/delete/", views.manage_car_delete, name="manage_car_delete"),
    path("bookings/", views.manage_bookings, name="manage_bookings"),
    path(
        "bookings/<int:pk>/status/<str:status>/",
        views.manage_booking_action,
        name="manage_booking_action",
    ),
    path("customers/", views.manage_customers, name="manage_customers"),
]
