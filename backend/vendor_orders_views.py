import datetime
from collections import OrderedDict

from django.db.models import Count, DateField, Prefetch
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from backend.delivery_auth_views import _shop_timing_payload
from backend.models import OrderedProduct, Order
from backend.vendor_auth_views import _vendor_from_request


def _calendar_date():
    return Coalesce(
        'delivery_date',
        TruncDate('created_at', tzinfo=timezone.get_current_timezone()),
        output_field=DateField(),
    )


def _month_bounds(month_raw):
    today = timezone.localdate()
    if month_raw:
        try:
            year_text, month_text = month_raw.split('-', 1)
            start = datetime.date(int(year_text), int(month_text), 1)
        except (TypeError, ValueError):
            start = datetime.date(today.year, today.month, 1)
    else:
        start = datetime.date(today.year, today.month, 1)
    if start.month == 12:
        nxt = datetime.date(start.year + 1, 1, 1)
    else:
        nxt = datetime.date(start.year, start.month + 1, 1)
    return start, nxt


def handler_update_kwargs(partner):
    if partner is None:
        return {}
    name = (getattr(partner, 'name', None) or getattr(partner, 'login_id', '') or 'Delivery boy')[:100]
    return {
        'handled_by': partner,
        'handled_by_name': name,
        'handled_at': timezone.now(),
    }


def assign_delivery_handler(order, partner):
    if order is None or partner is None:
        return
    OrderedProduct.objects.filter(order=order).update(**handler_update_kwargs(partner))


def _customer_name(order):
    address = getattr(order, 'user_address', None)
    for value in (
        getattr(order, 'delivery_contact_name', ''),
        getattr(address, 'name', '') if address is not None else '',
        getattr(order.user, 'fullname', '') if order.user_id else '',
        getattr(order.user, 'name', '') if order.user_id else '',
    ):
        text = (value or '').strip()
        if text:
            return text
    return 'Customer'


def _customer_phone(order):
    address = getattr(order, 'user_address', None)
    for value in (
        getattr(order, 'delivery_contact_phone', ''),
        getattr(address, 'contact_no', '') if address is not None else '',
        getattr(order.user, 'phone', '') if order.user_id else '',
    ):
        text = (value or '').strip()
        if text:
            return text
    return ''


def _delivery_label(order):
    kind = (getattr(order, 'delivery_type', '') or '').strip().lower()
    if kind in ('quick', 'express'):
        return getattr(order, 'delivery_eta', '') or 'Quick delivery'
    parts = []
    day = getattr(order, 'delivery_date', None)
    if day is not None:
        parts.append(day.strftime('%d %b %Y'))
    slot = (getattr(order, 'delivery_slot', '') or '').strip()
    if slot:
        parts.append(slot)
    return ' - '.join(parts)


def _status_label(items):
    statuses = [item.status for item in items if (item.status or '').strip()]
    unique = list(OrderedDict.fromkeys(statuses))
    if not unique:
        return 'ORDERED'
    if len(unique) == 1:
        return unique[0]
    return ' · '.join(f'{statuses.count(status)} {status}' for status in unique)


def _order_payload(order, items):
    handler_name = ''
    handler_login = ''
    handler_phone = ''
    handled_at = None
    for item in items:
        partner = item.handled_by
        if (item.handled_by_name or '').strip():
            handler_name = item.handled_by_name.strip()
            handled_at = item.handled_at
            if partner is not None:
                handler_login = getattr(partner, 'login_id', '') or ''
                handler_phone = getattr(partner, 'phone', '') or ''
            break
        if partner is not None:
            handler_name = partner.name or partner.login_id
            handler_login = partner.login_id
            handler_phone = partner.phone or ''
            handled_at = item.handled_at
            break
    return {
        'id': str(order.id),
        'created_at': order.created_at,
        'customer_name': _customer_name(order),
        'customer_phone': _customer_phone(order),
        'address': order.address or '',
        'payment_mode': order.payment_mode or '',
        'tx_amount': str(order.tx_amount or 0),
        'status': _status_label(items),
        'delivery_type': getattr(order, 'delivery_type', '') or '',
        'delivery_date': order.delivery_date.isoformat() if getattr(order, 'delivery_date', None) else '',
        'delivery_slot': getattr(order, 'delivery_slot', '') or '',
        'delivery_label': _delivery_label(order),
        'handled_by_name': handler_name,
        'handled_by_login_id': handler_login,
        'handled_by_phone': handler_phone,
        'handled_at': handled_at,
        'item_count': len(items),
        **order.cancel_request_payload(items),
        'items': [
            {
                'id': str(item.id),
                'title': str(item.product_option.product.title) if item.product_option_id else 'Product',
                'option': item.product_option.option if item.product_option_id else '',
                'quantity': item.quantity,
                'status': item.status,
                'price': str(item.tx_price or item.product_price or 0),
            }
            for item in items
        ],
    }


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_orders(request):
    vendor = _vendor_from_request(request)
    if vendor is None:
        return Response({'error': 'Sign in again.'}, status=401)

    status_filter = (request.GET.get('status') or '').strip().upper()
    try:
        page = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(50, max(1, int(request.GET.get('page_size') or 20)))
    except (TypeError, ValueError):
        page_size = 20

    month_start, month_next = _month_bounds((request.GET.get('month') or '').strip())
    date_raw = (request.GET.get('date') or '').strip()
    selected_day = None
    if date_raw:
        try:
            selected_day = datetime.date.fromisoformat(date_raw)
        except ValueError:
            selected_day = None

    vendor_items = OrderedProduct.objects.filter(product_option__product__vendor=vendor)
    order_ids = vendor_items.values_list('order_id', flat=True).distinct()
    dated_orders = Order.objects.filter(id__in=order_ids).annotate(calendar_date=_calendar_date())
    calendar_rows = (
        dated_orders.filter(calendar_date__gte=month_start, calendar_date__lt=month_next)
        .values('calendar_date')
        .annotate(count=Count('id'))
    )
    calendar = {}
    for row in calendar_rows:
        day = row.get('calendar_date')
        if day is None:
            continue
        calendar[day.isoformat()] = int(row.get('count') or 0)

    orders = dated_orders.select_related('user', 'user_address')
    if status_filter in {'ORDERED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'CANCELLED'}:
        orders = orders.filter(
            id__in=vendor_items.filter(status=status_filter).values_list('order_id', flat=True)
        )
    if selected_day is not None:
        orders = orders.filter(calendar_date=selected_day)

    orders = orders.prefetch_related(
        Prefetch(
            'orders_set',
            queryset=OrderedProduct.objects.filter(product_option__product__vendor=vendor)
            .select_related(
                'product_option',
                'product_option__product',
                'handled_by',
            )
            .order_by('created_at'),
            to_attr='vendor_items',
        )
    ).order_by('-created_at')

    total = orders.count()
    start = (page - 1) * page_size
    page_orders = list(orders[start:start + page_size])
    results = [
        _order_payload(order, getattr(order, 'vendor_items', []))
        for order in page_orders
    ]

    count_source = vendor_items
    if selected_day is not None:
        count_ids = dated_orders.filter(calendar_date=selected_day).values_list('id', flat=True)
        count_source = vendor_items.filter(order_id__in=count_ids)
    counts = {
        'all': count_source.values('order_id').distinct().count(),
        'ordered': count_source.filter(status='ORDERED').values('order_id').distinct().count(),
        'out_for_delivery': count_source.filter(status='OUT_FOR_DELIVERY').values('order_id').distinct().count(),
        'delivered': count_source.filter(status='DELIVERED').values('order_id').distinct().count(),
    }

    today = timezone.localdate()
    upcoming_prefetch = Prefetch(
        'orders_set',
        queryset=OrderedProduct.objects.filter(product_option__product__vendor=vendor)
        .select_related(
            'product_option',
            'product_option__product',
            'handled_by',
        )
        .order_by('created_at'),
        to_attr='vendor_items',
    )
    active_upcoming_ids = vendor_items.exclude(
        status__in=['DELIVERED', 'CANCELLED']
    ).values_list('order_id', flat=True)
    upcoming_orders = list(
        dated_orders.filter(
            id__in=active_upcoming_ids,
            delivery_date__gte=today,
        )
        .exclude(delivery_type__in=['quick', 'express'])
        .select_related('user', 'user_address')
        .prefetch_related(upcoming_prefetch)
        .order_by('delivery_date', 'created_at')[:50]
    )
    upcoming = [
        _order_payload(order, getattr(order, 'vendor_items', []))
        for order in upcoming_orders
    ]

    return Response({
        'results': results,
        'count': total,
        'page': page,
        'page_size': page_size,
        'has_next': start + len(results) < total,
        'counts': counts,
        'calendar': calendar,
        'upcoming': upcoming,
        'month': month_start.strftime('%Y-%m'),
        'date': selected_day.isoformat() if selected_day else '',
        'slots': _shop_timing_payload(vendor).get('slots') or [],
    })
