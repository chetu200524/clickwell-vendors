from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from backend.models import DeliveryPartner, Order, OrderedProduct
from backend.utils import IsAuthenticatedUser, notify_order_bulk_status_change, send_user_notification
from backend.vendor_auth_views import _vendor_from_request
from backend.vendor_orders_views import assign_delivery_handler


def _find_order(lookup):
    lookup = (lookup or '').strip()
    if not lookup:
        return None
    order = Order.objects.filter(id=lookup).first()
    if order is not None:
        return order
    line = OrderedProduct.objects.select_related('order').filter(id=lookup).first()
    return line.order if line is not None else None


def _delivery_from_request(request):
    header = request.headers.get('Authorization') or ''
    parts = str(header).split()
    token = ''
    if len(parts) == 2 and parts[0] in ('Delivery', 'Bearer'):
        token = parts[1].strip()
    if not token:
        token = (request.headers.get('X-Delivery-Token') or '').strip()
    if not token:
        return None
    return DeliveryPartner.objects.select_related('vendor').filter(
        auth_token=token,
        is_active=True,
        is_logged_in=True,
    ).first()


def _order_vendor_id(order):
    if order.vendor_id:
        return order.vendor_id
    item = order.orders_set.select_related('product_option__product').first()
    if item is None:
        return None
    product = getattr(item.product_option, 'product', None)
    vendor = getattr(product, 'vendor', None)
    return getattr(vendor, 'id', None)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def request_order_cancel(request):
    order = _find_order(request.data.get('id') or request.data.get('order_id'))
    user = request.user
    if order is None or order.user_id != user.id:
        return Response({'error': 'Order not found.'}, status=404)

    flags = order.cancel_request_payload()
    if flags['cancel_request_status'] == 'pending':
        return Response({'error': 'A return request is already waiting for approval.', **flags}, status=400)
    if not flags['can_request_cancel']:
        statuses = order.line_statuses()
        if statuses & {'OUT_FOR_DELIVERY', 'SHIPPED'}:
            message = 'This order cannot be returned while it is out for delivery.'
        elif statuses & {'CANCELLED'}:
            message = 'This order is already cancelled.'
        else:
            message = 'This order cannot be returned right now.'
        return Response({'error': message, **flags}, status=400)

    order.cancel_request_status = 'pending'
    order.cancel_requested_at = timezone.now()
    order.cancel_reviewed_at = None
    order.cancel_reviewed_by = ''
    order.save(update_fields=[
        'cancel_request_status',
        'cancel_requested_at',
        'cancel_reviewed_at',
        'cancel_reviewed_by',
        'updated_at',
    ])
    return Response({
        'ok': True,
        'message': 'Return request sent to the store and delivery partner.',
        **order.cancel_request_payload(),
    })


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def review_order_cancel(request):
    vendor = _vendor_from_request(request)
    partner = None if vendor is not None else _delivery_from_request(request)
    if vendor is None and partner is None:
        return Response({'error': 'Sign in again.'}, status=401)

    role = 'vendor' if vendor is not None else 'delivery'
    order = _find_order(request.data.get('id') or request.data.get('order_id'))
    if order is None:
        return Response({'error': 'Order not found.'}, status=404)

    owner_id = _order_vendor_id(order)
    if role == 'vendor' and owner_id not in (None, vendor.id):
        return Response({'error': 'Order not found.'}, status=404)
    if role == 'delivery' and owner_id not in (None, getattr(partner, 'vendor_id', None)):
        return Response({'error': 'Order not found.'}, status=404)

    action = (request.data.get('action') or '').strip().lower()
    if action not in ('approve', 'reject'):
        return Response({'error': 'Choose approve or reject.'}, status=400)
    if (order.cancel_request_status or '').strip().lower() != 'pending':
        return Response({'error': 'There is no return request to review.'}, status=400)

    statuses = order.line_statuses()
    if action == 'approve' and statuses & {'OUT_FOR_DELIVERY', 'SHIPPED'}:
        return Response({'error': 'This order is already out for delivery.'}, status=400)

    if action == 'approve':
        items = list(order.orders_set.select_related('order', 'product_option'))
        for item in items:
            if (item.status or '').upper() == 'CANCELLED':
                continue
            item.status = 'CANCELLED'
            item.save(update_fields=['status', 'updated_at'])
        if partner is not None:
            assign_delivery_handler(order, partner)
        order.cancel_request_status = 'approved'
        order.cancel_reviewed_at = timezone.now()
        order.cancel_reviewed_by = role
        order.save(update_fields=[
            'cancel_request_status',
            'cancel_reviewed_at',
            'cancel_reviewed_by',
            'updated_at',
        ])
        if items:
            notify_order_bulk_status_change(
                order,
                'CANCELLED',
                reference_product=items[0],
                item_count=len(items),
            )
        return Response({
            'ok': True,
            'message': 'Return approved. The order is cancelled.',
            **order.cancel_request_payload(),
        })

    order.cancel_request_status = 'rejected'
    order.cancel_reviewed_at = timezone.now()
    order.cancel_reviewed_by = role
    order.save(update_fields=[
        'cancel_request_status',
        'cancel_reviewed_at',
        'cancel_reviewed_by',
        'updated_at',
    ])
    try:
        send_user_notification(
            order.user,
            'Return request declined',
            'The store did not approve your return request.',
            '',
        )
    except Exception:
        pass
    return Response({
        'ok': True,
        'message': 'Return request declined.',
        **order.cancel_request_payload(),
    })
