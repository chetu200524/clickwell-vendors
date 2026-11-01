import secrets

from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from backend.authentication import DeliveryTokenAuthentication
from backend.models import DeliveryPartner
from backend.utils import IsDeliveryAuthenticated


def _shop_timing_payload(shop):
    if shop is None:
        return {
            'quick_enabled': False,
            'quick_min_minutes': 10,
            'quick_max_minutes': 30,
            'slots': [],
        }
    slots = []
    raw = shop.slots if isinstance(shop.slots, list) else []
    for slot in raw:
        if not isinstance(slot, dict):
            continue
        start = str(slot.get('start') or '').strip()
        end = str(slot.get('end') or '').strip()
        if not start or not end:
            continue
        slots.append({'start': start, 'end': end})
    return {
        'quick_enabled': bool(shop.quick_enabled),
        'quick_min_minutes': shop.quick_min_minutes,
        'quick_max_minutes': shop.quick_max_minutes,
        'slots': slots,
    }


@api_view(['POST'])
@permission_classes([AllowAny])
def delivery_login(request):
    """
    Delivery app login. Single active session per partner until admin force logout.
    """
    login_id = (request.data.get('login_id') or '').strip()
    password = request.data.get('password') or ''

    if not login_id or not password:
        return Response(
            {'error': 'missing_credentials', 'message': 'Delivery ID and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    partner = DeliveryPartner.objects.select_related('vendor').filter(login_id__iexact=login_id).first()
    if not partner:
        return Response(
            {'error': 'invalid_credentials', 'message': 'Invalid delivery ID or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not partner.is_active:
        return Response(
            {'error': 'account_disabled', 'message': 'Your account is disabled. Contact admin.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not check_password(password, partner.password):
        return Response(
            {'error': 'invalid_credentials', 'message': 'Invalid delivery ID or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if partner.is_logged_in and partner.auth_token:
        return Response(
            {
                'error': 'already_logged_in',
                'message': (
                    'This delivery account is already signed in. '
                    'Ask the shop owner to force logout from the vendor app before signing in again.'
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )

    token = secrets.token_urlsafe(48)
    partner.auth_token = token
    partner.is_logged_in = True
    partner.logged_in_at = timezone.now()
    partner.device_info = (request.data.get('device_info') or '')[:255]
    partner.save(
        update_fields=['auth_token', 'is_logged_in', 'logged_in_at', 'device_info', 'updated_at']
    )

    shop = partner.vendor
    return Response(
        {
            'token': token,
            'login_id': partner.login_id,
            'name': partner.name,
            'phone': partner.phone or '',
            'shop_name': getattr(shop, 'shop_name', '') or '',
            'vendor_id': shop.id if shop is not None else None,
            'shop_timing': _shop_timing_payload(shop),
        },
        status=status.HTTP_200_OK,
    )


@api_view(['GET'])
@authentication_classes([DeliveryTokenAuthentication])
@permission_classes([IsDeliveryAuthenticated])
def delivery_session(request):
    partner = request.user
    shop = getattr(partner, 'vendor', None)
    return Response(
        {
            'login_id': partner.login_id,
            'name': partner.name,
            'phone': partner.phone or '',
            'shop_name': getattr(shop, 'shop_name', '') or '',
            'vendor_id': shop.id if shop is not None else None,
            'shop_timing': _shop_timing_payload(shop),
            'logged_in_at': partner.logged_in_at,
            'is_active': partner.is_active,
            'device_info': partner.device_info or '',
            'member_since': partner.created_at,
        },
        status=status.HTTP_200_OK,
    )
