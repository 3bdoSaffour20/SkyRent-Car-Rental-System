from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    """
    Extended information for every registered user (customer or manager).
    A Profile is created automatically whenever a User is created.
    """

    ROLE_CUSTOMER = "customer"
    ROLE_MANAGER = "manager"
    ROLE_CHOICES = [
        (ROLE_CUSTOMER, "Customer"),
        (ROLE_MANAGER, "Manager / Admin"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CUSTOMER)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    license_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Driving license number (optional)",
    )
    avatar_url = models.URLField(
        blank=True,
        help_text="Optional URL to a profile picture",
    )
    api_user_id = models.CharField(max_length=100, blank=True, null=True)
    # NOTE: a per-user `api_token` field was removed in migration 0003.
    # Provider credentials are server-side environment variables only and are
    # never stored in SQLite.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Profile of {self.user.username}"

    @property
    def is_manager(self):
        """Manager access = superuser, staff or an explicitly promoted profile."""
        return (
            self.role == self.ROLE_MANAGER
            or self.user.is_superuser
            or self.user.is_staff
        )

    @property
    def display_name(self):
        full_name = self.user.get_full_name()
        return full_name or self.user.username


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_update_profile(sender, instance, created, **kwargs):
    """Keep a Profile in sync with its User (role follows staff status)."""
    if created:
        Profile.objects.create(
            user=instance,
            role=Profile.ROLE_MANAGER
            if (instance.is_staff or instance.is_superuser)
            else Profile.ROLE_CUSTOMER,
        )
    else:
        profile, _ = Profile.objects.get_or_create(user=instance)
        if (instance.is_staff or instance.is_superuser) and profile.role != Profile.ROLE_MANAGER:
            profile.role = Profile.ROLE_MANAGER
            profile.save(update_fields=["role"])
