from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware


class RelaxedCsrfViewMiddleware(CsrfViewMiddleware):
    def _origin_verified(self, request):
        if getattr(settings, "CSRF_TRUST_ANY_ORIGIN", False):
            return True
        return super()._origin_verified(request)
