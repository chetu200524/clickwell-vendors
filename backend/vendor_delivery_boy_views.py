import re
import secrets

from django.contrib.auth.hashers import make_password
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from backend.models import DeliveryPartner
from backend.vendor_auth_views import _vendor_from_request

_LOGIN_RE = re.compile(r'^[A-Za-z0-9_]{3,50}$')
_PHONE_RE = re.compile(r'^\d{10}$')


def _partner_payload(partner):
    return {
        'id': partner.id,
        'login_id': partner.login_id,
        'name': partner.name,
        'phone': partner.phone or '',
        'is_active': partner.is_active,
        'is_logged_in': bool(partner.is_logged_in and partner.auth_token),
        'logged_in_at': partner.logged_in_at,
        'created_at': partner.created_at,
    }


def _shop_prefix(vendor):
    return re.sub(r'[^A-Za-z0-9_]', '', vendor.login_id or 'shop')[:20] or 'shop'


def _clean_login_id(raw, vendor):
    """Always store {shopLoginId}_{suffix} so two shops can both type ravi."""
    prefix = _shop_prefix(vendor)
    suffix = re.sub(r'[^A-Za-z0-9_]', '', str(raw or '').strip())
    prefix_l = prefix.lower()
    if suffix.lower() == prefix_l:
        suffix = ''
    elif suffix.lower().startswith(f'{prefix_l}_'):
        suffix = re.sub(r'[^A-Za-z0-9_]', '', suffix[len(prefix) + 1:])
    max_suffix = max(3, 50 - len(prefix) - 1)
    suffix = suffix[:max_suffix]
    if not suffix:
        suffix = secrets.token_hex(3)[:max_suffix]
    return f'{prefix}_{suffix}'


def _login_id_taken_error(login_id, vendor, exclude_id=None):
    query = DeliveryPartner.objects.filter(login_id__iexact=login_id)
    if exclude_id is not None:
        query = query.exclude(id=exclude_id)
    existing = query.first()
    if existing is None:
        return None
    if existing.vendor_id == vendor.id:
        return 'This shop already has that delivery ID.'
    return 'That delivery ID is already used by another shop. Choose another.'


def _clean_phone(raw):
    digits = re.sub(r'\D', '', str(raw or ''))
    return digits[-10:] if len(digits) >= 10 else digits


@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_delivery_boys(request):
    vendor = _vendor_from_request(request)
    if vendor is None:
        return Response({'error': 'Sign in again.'}, status=401)

    if request.method == 'GET':
        partners = vendor.delivery_partners.order_by('name', 'login_id')
        return Response([_partner_payload(partner) for partner in partners])

    name = str(request.data.get('name') or '').strip()
    login_id = _clean_login_id(request.data.get('login_id'), vendor)
    password = str(request.data.get('password') or '')
    phone = _clean_phone(request.data.get('phone'))

    if not name:
        return Response({'error': 'Enter the delivery boy name.'}, status=400)
    if not _LOGIN_RE.match(login_id):
        return Response({'error': 'Delivery ID must be 3–50 letters, numbers, or _.'}, status=400)
    if len(password) < 6:
        return Response({'error': 'Password must be at least 6 characters.'}, status=400)
    if phone and not _PHONE_RE.match(phone):
        return Response({'error': 'Enter a 10-digit phone number.'}, status=400)
    taken = _login_id_taken_error(login_id, vendor)
    if taken:
        return Response({'error': taken}, status=400)

    partner = DeliveryPartner.objects.create(
        vendor=vendor,
        login_id=login_id,
        name=name,
        phone=phone,
        password=make_password(password),
        is_active=True,
    )
    return Response(_partner_payload(partner), status=201)


@api_view(['PATCH', 'DELETE'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_delivery_boy_detail(request, partner_id):
    vendor = _vendor_from_request(request)
    if vendor is None:
        return Response({'error': 'Sign in again.'}, status=401)

    partner = vendor.delivery_partners.filter(id=partner_id).first()
    if partner is None:
        return Response({'error': 'Delivery boy not found.'}, status=404)

    if request.method == 'DELETE':
        partner.is_active = False
        partner.force_logout()
        partner.save(update_fields=['is_active', 'updated_at'])
        return Response(_partner_payload(partner))

    name = request.data.get('name')
    login_id = request.data.get('login_id')
    password = request.data.get('password')
    phone = request.data.get('phone')
    is_active = request.data.get('is_active')
    force_logout = request.data.get('force_logout')

    if name is not None:
        name = str(name).strip()
        if not name:
            return Response({'error': 'Enter the delivery boy name.'}, status=400)
        partner.name = name

    if login_id is not None:
        cleaned = _clean_login_id(login_id, vendor)
        if not _LOGIN_RE.match(cleaned):
            return Response({'error': 'Delivery ID must be 3–50 letters, numbers, or _.'}, status=400)
        taken = _login_id_taken_error(cleaned, vendor, exclude_id=partner.id)
        if taken:
            return Response({'error': taken}, status=400)
        partner.login_id = cleaned

    if password:
        if len(str(password)) < 6:
            return Response({'error': 'Password must be at least 6 characters.'}, status=400)
        partner.password = make_password(str(password))
        partner.force_logout()

    if phone is not None:
        cleaned_phone = _clean_phone(phone)
        if cleaned_phone and not _PHONE_RE.match(cleaned_phone):
            return Response({'error': 'Enter a 10-digit phone number.'}, status=400)
        partner.phone = cleaned_phone

    if is_active is not None:
        partner.is_active = bool(is_active)
        if not partner.is_active:
            partner.force_logout()

    if force_logout is True:
        partner.force_logout()

    partner.save()
    return Response(_partner_payload(partner))
