import base64
import datetime
import hashlib
import hmac
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from random import randint

import requests
from django.core.mail import EmailMessage
from django.template.loader import get_template
import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from backend.models import Otp, Token, PasswordResetToken, Notification
from backend.serializers import NotificationSerializer
from core.settings import TEMPLATES_BASE_URL, CF_KEY, FSMS_KEY, SERVICE_ACCOUNT_FILE, PROJECT_ID

from django.utils import timezone


def parse_price(value, default=Decimal('0')):
    """Parse rupee amounts such as 25, 25.3, or '25.30' into Decimal."""
    if value is None or value == '':
        return default
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'Invalid price: {value}')
    if amount < 0:
        raise ValueError('Price must be non-negative')
    return amount


FCM_SCOPES = ['https://www.googleapis.com/auth/firebase.messaging']


def get_access_token():
    """
    OAuth2 access token for Firebase Cloud Messaging HTTP v1 API.
    See https://firebase.google.com/docs/cloud-messaging/auth-server
    """
    if not os.path.isfile(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f'Firebase service account file not found: {SERVICE_ACCOUNT_FILE}. '
            'Download a new key from Firebase Console → Project settings → '
            'Service accounts → Generate new private key.'
        )

    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=FCM_SCOPES,
        )
        credentials.refresh(Request())
    except RefreshError as exc:
        raise RefreshError(
            'Firebase service account key is invalid or was revoked. '
            f'File: {SERVICE_ACCOUNT_FILE}. '
            'Generate a new private key in Firebase Console → Project settings '
            f'→ Service accounts (project: clickwell-78742). Original error: {exc}'
        ) from exc

    token = credentials.token
    return token.decode('utf-8') if isinstance(token, bytes) else token


ORDER_STATUS_NOTIFICATIONS = frozenset({
    'OUT_FOR_DELIVERY',
    'DELIVERED',
    'CANCELLED',
})


def _product_option_notification_image(product_option):
    if product_option is None:
        return None
    first_image = product_option.images_set.order_by('position').first()
    return first_image.image if first_image else None


def _order_status_notification_body(product_label, new_status, item_count=1):
    if new_status == 'OUT_FOR_DELIVERY':
        if item_count > 1:
            return f'{item_count} items in your order are out for delivery.'
        return f'Your {product_label} is out for delivery.'
    if new_status == 'DELIVERED':
        if item_count > 1:
            return f'{item_count} items in your order have been delivered.'
        return f'Your {product_label} has been delivered.'
    if new_status == 'CANCELLED':
        if item_count > 1:
            return f'{item_count} items in your order have been cancelled.'
        return f'Your {product_label} has been cancelled.'
    return f'Your order status is now {new_status.replace("_", " ").lower()}.'


def notify_order_status_change(ordered_product, new_status, old_status=None):
    """Notify the customer when a single order line status changes."""
    if old_status is not None and old_status == new_status:
        return
    if new_status not in ORDER_STATUS_NOTIFICATIONS:
        return

    user = ordered_product.order.user
    product_label = str(ordered_product.product_option)
    title = f'ORDER {new_status}'
    body = _order_status_notification_body(product_label, new_status)
    image = _product_option_notification_image(ordered_product.product_option)

    try:
        send_user_notification(
            user,
            title,
            body,
            image,
            product_option=ordered_product.product_option,
        )
    except Exception as exc:
        print(f'Error sending order status notification: {exc}')


def notify_order_bulk_status_change(order, new_status, *, reference_product=None, item_count=None):
    """Notify the customer once when multiple order lines share a status update."""
    if new_status not in ORDER_STATUS_NOTIFICATIONS:
        return

    products = list(
        order.orders_set.select_related('product_option').order_by('created_at')
    )
    if not products:
        return

    count = item_count if item_count is not None else len(products)
    product = reference_product if reference_product is not None else products[0]
    user = order.user
    product_label = str(product.product_option)
    title = f'ORDER {new_status}'
    body = _order_status_notification_body(product_label, new_status, item_count=count)
    image = _product_option_notification_image(product.product_option)

    try:
        send_user_notification(
            user,
            title,
            body,
            image,
            product_option=product.product_option,
        )
    except Exception as exc:
        print(f'Error sending bulk order status notification: {exc}')


def send_user_notification(user, title, body, image, product_option=None):
    notif = Notification(
        user=user,
        title=title,
        body=body,
        image=image,
        product_option=product_option,
    )
    notif.save()

    notif_data = NotificationSerializer(notif, many=False).data
    message_title = notif_data.get('title')
    message_body = notif_data.get('body')
    message_image = notif_data.get('image') or ''
    product_option_id = notif_data.get('product_option_id') or ''

    # Retrieve the most recent FCM token for the user
    latest_token = user.tokens_set.order_by('-created_at').first()

    if not latest_token:
        return Response({'message': 'No FCM token available'}, status=400)

    notification_payload = {
        "title": message_title,
        "body": message_body,
    }
    if message_image:
        notification_payload["image"] = message_image

    message = {
        "message": {
            "notification": notification_payload,
            "data": {
                "image": str(message_image),
                "title": str(message_title or ''),
                "body": str(message_body or ''),
                "product_option_id": str(product_option_id),
            },
            "android": {
                "notification": {
                    "channel_id": "clickwell_order_updates",
                    "sound": "default",
                    "notification_priority": "PRIORITY_HIGH",
                }
            },
            "token": latest_token.fcmtoken
        }
    }

    # Set up the FCM endpoint and headers
    url = f'https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send'
    headers = {
        'Authorization': 'Bearer ' + get_access_token(),
        'Content-Type': 'application/json; UTF-8',
    }

    # Send the POST request to FCM
    response = requests.post(url, json=message, headers=headers)

    # Handle the response
    if response.status_code == 200:
        print('Successfully sent message')
        return Response({'message': 'Notification sent successfully'})
    else:
        error = response.json()
        print('Error sending message:', error)
        return Response({'message': 'Failed to send notification', 'error': error}, status=400)


def send_otp(phone):
    otp = randint(100000, 999999)
    validity = timezone.now() + datetime.timedelta(minutes=10)
    Otp.objects.update_or_create(phone=phone, defaults={"otp": otp, "verified": False, "validity": validity})

    # Send via Fast2SMS when configured (falls back to console log in dev)
    if FSMS_KEY:
        try:
            response = requests.post(
                "https://www.fast2sms.com/dev/bulkV2",
                headers={"authorization": FSMS_KEY, "Content-Type": "application/json"},
                json={
                    "route": "otp",
                    "variables_values": str(otp),
                    "numbers": str(phone),
                },
                timeout=15,
            )
            if response.status_code == 200:
                print(f"OTP sent via Fast2SMS to {phone}")
                return Response("otp send successfully")
            print(f"Fast2SMS failed ({response.status_code}): {response.text}")
        except Exception as exc:
            print(f"Fast2SMS error: {exc}")

    print(f"[DEV OTP] phone={phone} otp={otp}")
    return Response("otp send successfully")


def new_token():
    token = uuid.uuid1().hex
    return token


def token_response(user, fcmtoken):
    token = new_token()
    Token.objects.create(token=token, user=user, fcmtoken=fcmtoken or '')
    return Response('token ' + token)


def send_password_reset_email(user):
    token = new_token()
    exp_time = datetime.datetime.now() + datetime.timedelta(minutes=10)

    PasswordResetToken.objects.update_or_create(user=user,
                                                defaults={'user': user, 'token': token, 'validity': exp_time})

    email_data = {
        'token': token,
        'email': user.email,
        'base_url': TEMPLATES_BASE_URL
    }

    message = get_template('emails/reset-password.html').render(email_data)

    msg = EmailMessage('Reset Password', body=message, to=[user.email])
    msg.content_subtype = 'html'

    try:
        msg.send()
    except Exception as e:
        print(f'Error sending email: {e}')
        return Response('email_failed', status=500)

    return Response('reset_password_email_sent')


class IsAuthenticatedUser(BasePermission):
    message = 'unauthenticated_user'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if user is None:
            return False
        if getattr(user, 'is_authenticated', False):
            return True
        from backend.models import User
        return isinstance(user, User)


class IsDeliveryAuthenticated(BasePermission):
    message = 'delivery_login_required'

    def has_permission(self, request, view):
        from backend.models import DeliveryPartner
        user = getattr(request, 'user', None)
        if user is None or not isinstance(user, DeliveryPartner):
            return False
        return True


def cfSignature(postData):
    signatureData = postData["orderId"] + postData["orderAmount"] + postData["referenceId"] + postData["txStatus"] + \
                    postData["paymentMode"] + postData["txMsg"] + postData["txTime"]

    message = bytes(signatureData, encoding='utf8')
    secret = bytes(CF_KEY, encoding='utf8')
    signature = base64.b64encode(hmac.new(secret, message, digestmod=hashlib.sha256).digest())

    return signature