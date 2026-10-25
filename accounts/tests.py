from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Profile


class RegistrationTests(TestCase):
    def test_registration_creates_customer_profile_and_signs_in(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newcustomer",
                "first_name": "New",
                "last_name": "Customer",
                "email": "new@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertRedirects(response, reverse("cars:home"))
        user = get_user_model().objects.get(username="newcustomer")
        self.assertEqual(user.profile.role, Profile.ROLE_CUSTOMER)
        self.assertEqual(user.email, "new@example.com")

        profile_response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(profile_response.status_code, 200)
        self.assertContains(profile_response, "Account settings")


class LoginTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="driver",
            password="StrongPass123!",
        )

    def test_login_uses_local_next_path(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "driver",
                "password": "StrongPass123!",
                "next": reverse("accounts:profile"),
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_login_rejects_external_next_path(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "driver",
                "password": "StrongPass123!",
                "next": "https://example.invalid/steal",
            },
        )
        self.assertRedirects(response, reverse("bookings:my_bookings"))
