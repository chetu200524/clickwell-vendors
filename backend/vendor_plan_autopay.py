import os
from decimal import Decimal

import razorpay

from backend.models import Plan, Vendor
from core.settings import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET


def _clear_proxies():
    for key in (
        'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
        'http_proxy', 'https_proxy', 'all_proxy',
    ):
        os.environ.pop(key, None)


def razorpay_client():
    _clear_proxies()
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def amount_paise(plan):
    return int((plan.price or Decimal('0')) * 100)


def razorpay_recurring_plan_id(plan):
    period = plan.autopay_period()
    if not period:
        return ''
    amount = amount_paise(plan)
    if amount < 100:
        return ''
    client = razorpay_client()
    existing_id = (plan.razorpay_plan_id or '').strip()
    if existing_id:
        try:
            remote = client.plan.fetch(existing_id)
            remote_amount = int((remote.get('item') or {}).get('amount') or 0)
            remote_period = str(remote.get('period') or '')
            if remote_amount == amount and remote_period == period:
                return existing_id
        except Exception:
            pass
    label = 'month' if period == 'monthly' else 'year'
    created = client.plan.create({
        'period': period,
        'interval': 1,
        'item': {
            'name': f'ClickWell {plan.name} {period}',
            'amount': amount,
            'currency': 'INR',
            'description': f'{plan.name} autopay every {label}',
        },
    })
    plan.razorpay_plan_id = str(created.get('id') or '')
    plan.save(update_fields=['razorpay_plan_id'])
    return plan.razorpay_plan_id


def cancel_subscription(subscription_id):
    sub_id = str(subscription_id or '').strip()
    if not sub_id:
        return
    try:
        razorpay_client().subscription.cancel(sub_id)
    except Exception:
        pass


def subscription_paid_count(subscription_id):
    sub_id = str(subscription_id or '').strip()
    if not sub_id:
        return 0
    try:
        remote = razorpay_client().subscription.fetch(sub_id)
        return int(remote.get('paid_count') or 0)
    except Exception:
        return 0


def cancel_vendor_autopay(vendor):
    cancel_subscription(vendor.razorpay_subscription_id)
    if not vendor.razorpay_subscription_id and not vendor.autopay_enabled:
        return
    vendor.razorpay_subscription_id = ''
    vendor.autopay_enabled = False
    vendor.razorpay_paid_count = 0
    vendor.save(update_fields=[
        'razorpay_subscription_id', 'autopay_enabled', 'razorpay_paid_count', 'updated_at',
    ])


def create_recurring_subscription(vendor, plan, start_at=None, cancel_existing=True):
    period = plan.autopay_period()
    if not period:
        return ''
    if cancel_existing:
        cancel_vendor_autopay(vendor)
    plan_id = razorpay_recurring_plan_id(plan)
    if not plan_id:
        return ''
    phone = ''.join(ch for ch in str(vendor.phone or '') if ch.isdigit())[-10:]
    payload = {
        'plan_id': plan_id,
        'total_count': 120 if period == 'monthly' else 20,
        'quantity': 1,
        'customer_notify': 1,
        'notify_info': {
            'notify_phone': phone or '9999999999',
            'notify_email': 'vendor@clickwell.test',
        },
        'notes': {
            'vendor_id': str(vendor.id),
            'plan_slug': plan.slug,
            'autopay_period': period,
        },
    }
    if start_at:
        payload['start_at'] = int(start_at)
    created = razorpay_client().subscription.create(payload)
    return str(created.get('id') or '')


def sync_vendor_autopay(vendor):
    sub_id = (vendor.razorpay_subscription_id or '').strip()
    if not sub_id:
        return vendor
    try:
        remote = razorpay_client().subscription.fetch(sub_id)
    except Exception:
        return vendor

    status = str(remote.get('status') or '')
    paid_count = int(remote.get('paid_count') or 0)
    notes = remote.get('notes') or {}
    active = status in {'authenticated', 'active', 'pending'}
    stopped = status in {'cancelled', 'completed', 'expired', 'halted'}

    extra = paid_count - int(vendor.razorpay_paid_count or 0)
    if extra > 0:
        plan = vendor.plan
        if plan is None:
            plan = Plan.objects.filter(slug__iexact=str(notes.get('plan_slug') or '')).first()
        if plan is not None:
            for _ in range(extra):
                vendor.apply_plan(plan)
        vendor.razorpay_paid_count = paid_count
        vendor.autopay_enabled = active
        vendor.save(update_fields=['razorpay_paid_count', 'autopay_enabled', 'updated_at'])
        return vendor

    wanted = active and not stopped
    if vendor.autopay_enabled != wanted:
        vendor.autopay_enabled = wanted
        vendor.save(update_fields=['autopay_enabled', 'updated_at'])
    return vendor


def vendor_for_subscription(subscription_id):
    key = str(subscription_id or '').strip()
    if not key:
        return None
    return Vendor.objects.select_related('plan').filter(razorpay_subscription_id=key).first()
