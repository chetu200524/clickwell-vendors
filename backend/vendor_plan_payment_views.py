from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from backend.models import Plan, Vendor
from backend.vendor_auth_views import _vendor_from_request
from datetime import timedelta

from django.utils import timezone

from backend.vendor_plan_autopay import (
    amount_paise,
    cancel_subscription,
    cancel_vendor_autopay,
    create_recurring_subscription,
    razorpay_client,
    subscription_paid_count,
    sync_vendor_autopay,
    vendor_for_subscription,
)
from core.settings import RAZORPAY_KEY_ID


def _test_mode():
    return str(RAZORPAY_KEY_ID or '').startswith('rzp_test_')


def _plan_from_slug(slug):
    key = str(slug or '').strip().lower()
    if not key:
        return None
    return Plan.objects.filter(slug__iexact=key, is_active=True).first()


def _pay_payload(vendor, plan, order_id='', subscription_id=''):
    amount = amount_paise(plan)
    period = plan.autopay_period()
    return {
        'paid': False,
        'test_mode': _test_mode(),
        'orderId': order_id,
        'subscriptionId': subscription_id,
        'autopay': plan.is_autopay(),
        'autopay_period': period,
        'razorpayKey': RAZORPAY_KEY_ID,
        'amount': amount,
        'currency': 'INR',
        'plan': plan.name,
        'plan_slug': plan.slug,
        'shop_name': vendor.shop_name,
        'phone': vendor.phone,
        'vendor_id': vendor.id,
    }


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_plan_pay(request):
    vendor = _vendor_from_request(request)
    if vendor is None:
        return Response({'error': 'Sign in again.'}, status=401)

    plan = _plan_from_slug(request.data.get('slug'))
    if plan is None:
        return Response({'error': 'This subscription is not available.'}, status=400)

    amount = amount_paise(plan)
    if amount < 100:
        return Response({'error': 'This subscription does not have a payable price.'}, status=400)

    order_id = ''
    subscription_id = ''
    if plan.is_autopay():
        try:
            subscription_id = create_recurring_subscription(
                vendor, plan, cancel_existing=False,
            )
        except Exception:
            subscription_id = ''
    if not subscription_id:
        try:
            rzp_order = razorpay_client().order.create({
                'amount': amount,
                'currency': 'INR',
                'receipt': f'plan-{vendor.id}-{plan.slug}'[:40],
                'payment_capture': 1,
                'notes': {
                    'vendor_id': str(vendor.id),
                    'plan_slug': plan.slug,
                    'autopay': '1' if plan.is_autopay() else '0',
                    'autopay_period': plan.autopay_period(),
                },
            })
            order_id = str(rzp_order.get('id') or '')
        except Exception:
            order_id = ''

    return Response(_pay_payload(
        vendor, plan, order_id=order_id, subscription_id=subscription_id,
    ))


def _activate_plan(vendor, plan, subscription_id=''):
    old_sub = (vendor.razorpay_subscription_id or '').strip()
    if not plan.is_autopay():
        cancel_vendor_autopay(vendor)
        vendor.apply_plan(plan)
        return

    already_applied = (
        vendor.plan_id == plan.id
        and vendor.session_expires_at
        and vendor.session_expires_at > timezone.localdate()
        and old_sub
        and old_sub == subscription_id
        and vendor.autopay_enabled
    )
    if not already_applied:
        vendor.apply_plan(plan)

    created_later = False
    if not subscription_id:
        try:
            start_at = int((timezone.now() + timedelta(days=plan.duration_in_days())).timestamp())
            subscription_id = create_recurring_subscription(
                vendor, plan, start_at=start_at, cancel_existing=True,
            )
            created_later = True
        except Exception:
            subscription_id = ''
    elif old_sub and old_sub != subscription_id:
        cancel_subscription(old_sub)

    if created_later:
        paid_count = 0
    elif subscription_id:
        paid_count = max(subscription_paid_count(subscription_id), 1)
    else:
        paid_count = 0

    vendor.razorpay_subscription_id = subscription_id
    vendor.razorpay_paid_count = paid_count
    vendor.autopay_enabled = bool(subscription_id)
    vendor.save(update_fields=[
        'razorpay_subscription_id', 'razorpay_paid_count', 'autopay_enabled', 'updated_at',
    ])


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_plan_verify(request):
    vendor = _vendor_from_request(request)
    if vendor is None:
        return Response({'error': 'Sign in again.'}, status=401)

    order_id = str(request.data.get('razorpay_order_id') or '').strip()
    payment_id = str(request.data.get('razorpay_payment_id') or '').strip()
    signature = str(request.data.get('razorpay_signature') or '').strip()
    subscription_id = str(request.data.get('razorpay_subscription_id') or '').strip()
    slug = request.data.get('slug')
    if not payment_id:
        return Response({'error': 'Payment details are incomplete.'}, status=400)

    client = razorpay_client()
    paid_amount = 0
    notes = {}
    try:
        if subscription_id and signature:
            client.utility.verify_subscription_payment_signature({
                'razorpay_subscription_id': subscription_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature,
            })
            payment = client.payment.fetch(payment_id)
            paid_amount = int(payment.get('amount') or 0)
            notes = payment.get('notes') or {}
        elif order_id and signature:
            client.utility.verify_payment_signature({
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature,
            })
            rzp_order = client.order.fetch(order_id)
            paid_amount = int(rzp_order.get('amount') or 0)
            notes = rzp_order.get('notes') or {}
        else:
            payment = client.payment.fetch(payment_id)
            status = str(payment.get('status') or '')
            if status not in {'authorized', 'captured'}:
                return Response({'error': 'Payment could not be verified.'}, status=400)
            paid_amount = int(payment.get('amount') or 0)
            notes = payment.get('notes') or {}
            if not subscription_id:
                subscription_id = str(payment.get('subscription_id') or '')
    except Exception:
        return Response({'error': 'Payment could not be verified.'}, status=400)

    if notes and str(notes.get('vendor_id') or '') not in {'', str(vendor.id)}:
        return Response({'error': 'This payment does not belong to this shop.'}, status=400)

    plan = _plan_from_slug(notes.get('plan_slug') or slug)
    if plan is None:
        return Response({'error': 'This subscription is not available.'}, status=400)

    expected = amount_paise(plan)
    if expected < 100 or paid_amount != expected:
        return Response({'error': 'Payment amount does not match this subscription.'}, status=400)

    _activate_plan(vendor, plan, subscription_id=subscription_id)
    vendor.refresh_from_db()
    return Response({
        'paid': True,
        'test_mode': _test_mode(),
        'plan': plan.name,
        'plan_slug': plan.slug,
        'autopay': bool(vendor.autopay_enabled),
        'autopay_period': plan.autopay_period(),
        'vendor': vendor.profile(request),
    })


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_plan_autopay_webhook(request):
    event = str((request.data or {}).get('event') or '')
    if event not in {
        'subscription.charged',
        'subscription.activated',
        'subscription.authenticated',
        'subscription.cancelled',
        'subscription.halted',
        'subscription.completed',
    }:
        return Response({'ok': True})

    payload = (request.data or {}).get('payload') or {}
    remote = ((payload.get('subscription') or {}).get('entity') or {})
    sub_id = str(remote.get('id') or '').strip()
    vendor = vendor_for_subscription(sub_id)
    if vendor is None:
        notes = remote.get('notes') or {}
        vendor_id = str(notes.get('vendor_id') or '').strip()
        if vendor_id.isdigit():
            vendor = Vendor.objects.select_related('plan').filter(id=int(vendor_id)).first()
            if vendor is not None and sub_id:
                vendor.razorpay_subscription_id = sub_id
                vendor.save(update_fields=['razorpay_subscription_id', 'updated_at'])
    if vendor is not None:
        sync_vendor_autopay(vendor)
    return Response({'ok': True})
