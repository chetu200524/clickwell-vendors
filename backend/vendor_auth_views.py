import secrets

from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from backend.models import Plan, Vendor


def _vendor_from_request(request):
    header = request.headers.get('Authorization', '')
    token = header[6:].strip() if header.startswith('Token ') else ''
    if not token:
        return None
    vendor = Vendor.objects.select_related('plan').filter(auth_token=token, is_active=True).first()
    if vendor is None:
        return None
    if vendor.session_is_expired():
        vendor.expire_session()
        return None
    return vendor


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_login(request):
    login_id = str(request.data.get('login_id') or '').strip()
    password = str(request.data.get('password') or '')
    if not login_id or not password:
        return Response({'error': 'Vendor ID and password are required.'}, status=400)

    vendor = Vendor.objects.select_related('plan').filter(login_id__iexact=login_id).first()
    if vendor is None or not vendor.is_active or not check_password(password, vendor.password):
        return Response({'error': 'Incorrect vendor ID or password.'}, status=401)
    if vendor.razorpay_subscription_id:
        try:
            from backend.vendor_plan_autopay import sync_vendor_autopay
            sync_vendor_autopay(vendor)
            vendor.refresh_from_db()
        except Exception:
            pass
    if vendor.session_is_expired():
        vendor.expire_session()
        return Response({
            'error': 'This shop session has expired. Ask admin to set a new expiry date.',
        }, status=403)

    vendor.auth_token = secrets.token_urlsafe(48)
    vendor.logged_in_at = timezone.now()
    vendor.save(update_fields=['auth_token', 'logged_in_at', 'updated_at'])
    return Response({'token': vendor.auth_token, 'vendor': vendor.profile(request)})


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_profile(request):
    vendor = _vendor_from_request(request)
    if vendor is None:
        return Response({'error': 'Sign in again.'}, status=401)
    if vendor.razorpay_subscription_id:
        try:
            from backend.vendor_plan_autopay import sync_vendor_autopay
            sync_vendor_autopay(vendor)
            vendor.refresh_from_db()
        except Exception:
            pass
    return Response(vendor.profile(request))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_logout(request):
    vendor = _vendor_from_request(request)
    if vendor is not None:
        vendor.auth_token = None
        vendor.save(update_fields=['auth_token', 'updated_at'])
    return Response({'ok': True})


def _plan_payload(plan, request=None):
    return {
        'slug': plan.slug,
        'name': plan.name,
        'duration_days': plan.duration_days,
        'duration_value': plan.duration_value,
        'duration_unit': plan.duration_unit,
        'duration_label': plan.duration_label(),
        'price': f'{plan.price:.2f}',
        'description': plan.description or '',
        'image': plan.image_url(request),
        'autopay': plan.is_autopay(),
        'autopay_period': plan.autopay_period(),
    }


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_plans(request):
    vendor = _vendor_from_request(request)
    current = vendor.plan if vendor is not None and vendor.plan_id else None
    plans = list(Plan.objects.filter(is_active=True).order_by('position', 'name'))
    return Response({
        'current': current.slug if current is not None else '',
        'current_name': current.name if current is not None else '',
        'session_expires_at': vendor.session_expires_at.isoformat() if vendor is not None and vendor.session_expires_at else '',
        'results': [_plan_payload(plan, request) for plan in plans],
    })
