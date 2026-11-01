from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from backend.models import Token, DeliveryPartner, Vendor


class TokenAuthentication(BaseAuthentication):

    def authenticate(self, request):
        header = request.headers.get('Authorization') or ''
        parts = str(header).split()
        if len(parts) != 2:
            return None
        raw = parts[1]
        try:
            user = Token.objects.get(token=raw).user
        except Token.DoesNotExist:
            if Vendor.objects.filter(auth_token=raw, is_active=True).exists():
                return None
            raise exceptions.AuthenticationFailed('unauthenticated_user')
        return user, None


class DeliveryTokenAuthentication(BaseAuthentication):
    """
    Delivery partner auth.
    Accepts:
      - Authorization: Delivery <token>
      - X-Delivery-Token: <token>  (fallback when nginx strips Authorization)
    """

    def authenticate(self, request):
        token = self._extract_delivery_token(request)
        if not token:
            return None

        partner = DeliveryPartner.objects.select_related('vendor').filter(
            auth_token=token,
            is_active=True,
            is_logged_in=True,
        ).first()
        if not partner:
            raise exceptions.AuthenticationFailed('delivery_session_invalid')

        return partner, None

    @staticmethod
    def _extract_delivery_token(request):
        auth_header = (
            request.headers.get('Authorization')
            or request.META.get('HTTP_AUTHORIZATION')
            or ''
        )
        parts = str(auth_header).split()
        if len(parts) == 2:
            scheme = parts[0]
            if scheme in ('Delivery', 'Bearer'):
                return parts[1]

        fallback = (
            request.headers.get('X-Delivery-Token')
            or request.META.get('HTTP_X_DELIVERY_TOKEN')
            or ''
        ).strip()
        return fallback or None