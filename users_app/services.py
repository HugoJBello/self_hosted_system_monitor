from django.contrib.auth import get_user_model


def list_users():
    return get_user_model().objects.order_by("username")


__all__ = ["list_users"]
