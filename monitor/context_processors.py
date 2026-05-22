from django.conf import settings


def app_shell(request):
    return {
        "app_subpath": settings.APP_SUBPATH,
    }

