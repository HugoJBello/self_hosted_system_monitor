import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure the default admin user exists."

    def handle(self, *args, **options):
        username = os.getenv("SYSTEM_MONITOR_DEFAULT_ADMIN_USER", "admin")
        password = os.getenv("SYSTEM_MONITOR_DEFAULT_ADMIN_PASSWORD", "change_me")
        email = os.getenv("SYSTEM_MONITOR_DEFAULT_ADMIN_EMAIL", "")
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        changed = False
        if created:
            user.set_password(password)
            changed = True
        if not user.is_staff or not user.is_superuser or not user.is_active:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if changed:
            user.save()
        action = "created" if created else "ready"
        self.stdout.write(self.style.SUCCESS(f"Default admin user '{username}' {action}."))
