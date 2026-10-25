"""Small shared helpers for the Car Rental System."""
from django.urls import reverse


def safe_next(url, fallback="cars:home"):
    """
    Only accept *relative* paths (e.g. "/bookings/?tab=history") for the
    post-action redirect target, so a crafted `next` value can never send
    users to an external site.
    """
    if url and url.startswith("/") and not url.startswith("//") and ":" not in url.split("/")[0]:
        return url
    return reverse(fallback)
