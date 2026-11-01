import base64
import datetime
import hashlib
import hmac
import json
import logging
import math
import re
from decimal import Decimal

import razorpay


import requests
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db import transaction, IntegrityError
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q , Case, When, IntegerField, Value, Count, Sum, F, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import get_template
from google.auth import jwt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.generics import get_object_or_404
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.views import APIView

from django.utils.html import strip_tags

from django.utils.encoding import force_str

from backend.models import User, Otp, PasswordResetToken, Token, Category, Slide, PageItem, Product, ProductOption, \
    OrderedProduct, Order, ContactInfo, ProductImage, InformMe, ProductSuggestion, AppVersion, UserAddress, \
    known_subcategory_spellings, resolve_subcategory_names, normalize_barcode, DeliveryTiming, Vendor
from backend.serializers import UserSerializer, CategorySerializer, SlideSerializer, PageItemSerializer, \
    ProductSerializer, WishlistSerializer, CartSerializer, AddressSerializer, ItemOrderSerializer, \
    OrderDetailsSerializer, NotificationSerializer, OrderItemSerializer, ProductOptionSerializer, InformMeSerializer, \
    VersionCheckRequestSerializer, UserAddressSerializer, format_order_datetime
from backend.authentication import DeliveryTokenAuthentication
from backend.utils import send_otp, token_response, send_password_reset_email, IsAuthenticatedUser, cfSignature, \
    send_user_notification, IsDeliveryAuthenticated, parse_price, \
    notify_order_status_change, notify_order_bulk_status_change
from core import settings
from core.settings import TEMPLATES_BASE_URL, CF_ID, CF_KEY, RAZORPAY_KEY_ID, \
    RAZORPAY_KEY_SECRET, DELIVERY_CHARGE_AMOUNT, FREE_DELIVERY_THRESHOLD
from rest_framework import status as http_status

from .serializers import PrivacyPolicySerializer

from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

@csrf_exempt
def app_store_notifications(request):
    """
    Production endpoint to receive and process App Store Server Notifications.

    This view supports:
      - Legacy notifications that include a "notification_type" field.
      - Notifications with a signedPayload (App Store Server Notifications V2).

    If a signedPayload is present, the payload is verified using the Apple public key
    stored in settings.APPLE_PUBLIC_KEY and then processed.
    """
    # Allow only POST requests.
    if request.method != 'POST':
        logger.warning("Received non-POST request: %s", request.method)
        return JsonResponse({'error': 'Invalid request method. Only POST is supported.'}, status=405)

    try:
        # Decode the incoming JSON payload.
        payload = request.body.decode('utf-8')
        data = json.loads(payload)
        logger.info("Received raw notification data: %s", data)
    except Exception as e:
        logger.error("Error parsing JSON payload: %s", e)
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Check if the notification includes a signedPayload (for App Store Server Notifications V2).
    if 'signedPayload' in data:
        signed_payload = data['signedPayload']
        try:
            # Verify the JWT using Apple's public key and the ES256 algorithm.
            decoded_payload = jwt.decode(
                signed_payload,
                settings.APPLE_PUBLIC_KEY,
                algorithms=['ES256']
            )
            logger.info("Decoded signedPayload successfully: %s", decoded_payload)
            # Use the decoded payload for further processing.
            data = decoded_payload
        except jwt.ExpiredSignatureError:
            logger.error("Expired signature in signedPayload")
            return JsonResponse({'error': 'Expired signature'}, status=400)
        except jwt.InvalidTokenError as e:
            logger.error("Invalid token in signedPayload: %s", e)
            return JsonResponse({'error': 'Invalid token'}, status=400)
    else:
        logger.info("No signedPayload found; processing as legacy notification.")

    # Process the notification based on its type.
    notification_type = data.get("notification_type")
    if notification_type:
        if notification_type == "DID_RENEW":
            logger.info("Subscription renewed. Data: %s", data)
            # TODO: Add your renewal handling logic here.
        elif notification_type == "CANCEL":
            logger.info("Subscription cancelled. Data: %s", data)
            # TODO: Add your cancellation handling logic here.
        elif notification_type == "DID_FAIL_TO_RENEW":
            logger.info("Failed to renew subscription. Data: %s", data)
            # TODO: Add your failure handling logic here.
        else:
            logger.info("Unhandled notification type: %s", notification_type)
    else:
        logger.warning("Notification type not provided in data.")

    # Respond with a success status.
    return JsonResponse({'status': 'ok'}, status=200)


@api_view(['POST'])
def request_otp(request):
    email = (request.data.get('email') or '').strip()
    phone = _normalize_phone(request.data.get('phone'))

    if email and phone:
        if User.objects.filter(email__iexact=email).exists():
            return Response('email already exists', status=400)
        if User.objects.filter(phone=phone).exists():
            return Response('phone already exists', status=400)
        return send_otp(phone)
    else:
        return Response('data_missing', status=400)


@api_view(['POST'])
def resend_otp(request):
    phone = _normalize_phone(request.data.get('phone'))
    if not phone:
        return Response('data_missing', 400)
    return send_otp(phone)


@api_view(['POST'])
def verify_otp(request):
    phone = _normalize_phone(request.data.get('phone'))
    otp = request.data.get('otp')

    if not phone or otp is None or str(otp).strip() == '':
        return Response('data_missing', 400)

    otp_obj = Otp.objects.filter(phone=phone).order_by('-id').first()
    if not otp_obj:
        if User.objects.filter(phone=phone).exists():
            return Response('phone already exists', 400)
        return Response('otp_not_found', 404)

    if otp_obj.validity.replace(tzinfo=None) <= datetime.datetime.utcnow():
        return Response('otp expired', 400)

    if otp_obj.verified:
        return Response('otp_verified_successfully')

    try:
        otp_value = int(str(otp).strip())
    except (TypeError, ValueError):
        return Response('Incorrect otp', 400)

    if otp_obj.otp == otp_value:
        otp_obj.verified = True
        otp_obj.save()
        return Response('otp_verified_successfully')

    return Response('Incorrect otp', 400)


@api_view(['POST'])
def create_account(request):
    email = (request.data.get('email') or '').strip()
    phone = _normalize_phone(request.data.get('phone'))
    password = request.data.get('password')
    fullname = (request.data.get('fullname') or '').strip()
    fcmtoken = request.data.get('fcmtoken')

    if not (email and phone and password and fullname):
        return Response('data_missing', 400)

    if User.objects.filter(email__iexact=email).exists():
        return Response('email already exists', 400)
    if User.objects.filter(phone=phone).exists():
        return Response('phone already exists', 400)

    otp_obj = Otp.objects.filter(phone=phone, verified=True).order_by('-id').first()
    if not otp_obj:
        return Response('otp_not_verified', 400)

    try:
        with transaction.atomic():
            user = User()
            user.email = email
            user.phone = phone
            user.fullname = fullname
            user.password = make_password(password)
            user.save()
            otp_obj.delete()
            return token_response(user, fcmtoken)
    except IntegrityError:
        return Response('account already exists', 400)


def _normalize_phone(phone):
    if not phone:
        return None
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) >= 10:
        return digits[-10:]
    return digits or None


@api_view(['POST'])
def login(request):
    email = (request.data.get('email') or '').strip() or None
    phone = _normalize_phone(request.data.get('phone'))
    password = request.data.get('password')
    fcmtoken = request.data.get('fcmtoken')

    if email:
        user = get_object_or_404(User, email__iexact=email)
    elif phone:
        user = get_object_or_404(User, phone=phone)
    else:
        return Response('data_missing', 400)

    if check_password(password, user.password):
        return token_response(user, fcmtoken)
    else:
        return Response('incorrect password', 400)

@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def logout(request):
    # Grab the bearer token header
    token_header = request.headers.get('Authorization')

    # Parse logout_all query param: expect "true"/"false"
    logout_all_param = request.GET.get('logout_all', 'false').lower()
    logout_all = logout_all_param == 'true'

    if logout_all:
        # Delete *all* tokens for this user → logout everywhere
        Token.objects.filter(user=request.user).delete()
    else:
        # Delete only the current token → logout this device
        Token.objects.filter(token=token_header).delete()

    return Response({'message': 'logged_out'})
    return Response('logged_out')


@api_view(['POST'])
def password_reset_email(request):
    email = request.data.get('email')
    if not email:
        return Response('params_missing', 400)

    user = get_object_or_404(User, email=email)
    return send_password_reset_email(user)


@api_view(['GET'])
def password_reset_form(request, email, token):
    token_instance = PasswordResetToken.objects.filter(user__email=email, token=token).first()
    link_expired = get_template('pages/link-expired.html').render()
    if token_instance:
        if datetime.datetime.utcnow() < token_instance.validity.replace(tzinfo=None):
            return render(request, 'pages/new-password-form.html', {
                'email': email,
                'token': token,
                'base_url': TEMPLATES_BASE_URL
            })
        else:
            token_instance.delete()
            return HttpResponse(link_expired)
    else:
        return HttpResponse(link_expired)


@api_view(['POST'])
def password_reset_confirm(request):
    email = request.data.get('email')
    token = request.data.get('token')
    password1 = request.data.get('password1')
    password2 = request.data.get('password2')

    token_instance = PasswordResetToken.objects.filter(user__email=email, token=token).first()
    link_expired = get_template('pages/link-expired.html').render()

    if token_instance:
        if datetime.datetime.utcnow() < token_instance.validity.replace(tzinfo=None):
            if len(password1) < 8:
                return render(request, 'pages/new-password-form.html', {
                    'email': email,
                    'token': token,
                    'base_url': TEMPLATES_BASE_URL,
                    'error': 'Password length must be at least 8 characters!'
                })

            if password1 == password2:
                user = token_instance.user
                user.password = make_password(password1)
                user.save()
                token_instance.delete()
                Token.objects.filter(user=user).delete()
                return render(request, 'pages/password-updated.html')
            else:
                return render(request, 'pages/new-password-form.html', {
                    'email': email,
                    'token': token,
                    'base_url': TEMPLATES_BASE_URL,
                    'error': 'Password doesn\'t matched!'
                })
        else:
            token_instance.delete()
            return HttpResponse(link_expired)
    else:
        return HttpResponse(link_expired)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def userdata(request):
    user = request.user
    data = UserSerializer(user, many=False).data
    return Response(data)


@api_view(['GET'])
def categories(request):
    categories_qs = Category.objects.all().order_by('position')
    vendor = request.GET.get('vendor')
    if vendor:
        categories_qs = categories_qs.filter(
            Q(products_set__vendor_id=vendor) |
            Q(pageitems_set__vendor_id=vendor) |
            Q(slides_set__vendor_id=vendor)
        ).distinct()
    data = CategorySerializer(categories_qs, many=True).data
    return Response(data)


@api_view(['GET'])
def slides(request):
    queryset = Slide.objects.select_related('category').order_by('position')
    category_id = request.GET.get('category')
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    vendor = request.GET.get('vendor')
    if vendor:
        queryset = queryset.filter(vendor_id=vendor)
    data = SlideSerializer(queryset, many=True, context={'request': request}).data
    return Response(data)


def _serialize_option_for_catalog(option):
    """Product option payload for mobile grids (cart uses option id)."""
    first_image = option.images_set.order_by('position').first()
    image_url = None
    if first_image and first_image.image:
        try:
            image_url = first_image.image.url
        except Exception:
            image_url = str(first_image.image)
    return {
        'id': str(option.id),
        'product_id': str(option.product.id),
        'image': image_url,
        'title': str(option),
        'price': option.effective_price(),
        'offer_price': option.effective_offer_price(),
        'quantity': option.quantity,
    }


@api_view(['GET'])
def pageitems(request):
    category = request.GET.get('category')
    list_products = request.GET.get('products') in ('1', 'true', 'yes')

    if list_products:
        if not category:
            return Response({'error': 'category parameter is required'}, status=400)
        pagination = LimitOffsetPagination()
        queryset = (
            ProductOption.objects.filter(product__category_id=category)
            .select_related('product')
            .prefetch_related('images_set')
            .order_by('product__title', 'option')
        )
        if request.GET.get('vendor'):
            queryset = queryset.filter(product__vendor_id=request.GET.get('vendor'))
        page = pagination.paginate_queryset(queryset, request)
        data = [_serialize_option_for_catalog(opt) for opt in page]
        return pagination.get_paginated_response(data)

    pagination = LimitOffsetPagination()

    page_items = PageItem.objects.filter(category=category).order_by('position')
    if request.GET.get('vendor'):
        page_items = page_items.filter(vendor_id=request.GET.get('vendor'))

    queryset = pagination.paginate_queryset(page_items, request)

    data = PageItemSerializer(queryset, many=True, context={'request': request}).data

    return pagination.get_paginated_response(data)


@api_view(['GET'])
def viewall(request):
    page_item_id = request.GET.get('id')

    pagination = LimitOffsetPagination()

    page_item = get_object_or_404(PageItem, id=page_item_id)
    vendor = request.GET.get('vendor')
    if vendor and str(page_item.vendor_id) != str(vendor):
        return Response({'count': 0, 'next': None, 'previous': None, 'results': []})
    product_options = page_item.product_options.all().order_by('page_item_links__position', 'page_item_links__id')
    if vendor:
        product_options = product_options.filter(product__vendor_id=vendor)

    queryset = pagination.paginate_queryset(product_options, request)

    data = WishlistSerializer(queryset, many=True).data
    return pagination.get_paginated_response(data)


_MATCH_STOP_WORDS = {
    'and', 'the', 'with', 'for', 'from', 'pack', 'pcs', 'piece', 'pieces',
    'ml', 'gm', 'kg', 'mg', 'ltr', 'litre', 'liter', 'size', 'new',
}


def _product_chip_names(subcategories, subcategory):
    names = subcategories if isinstance(subcategories, list) else []
    cleaned = [str(name).strip() for name in names if str(name).strip()]
    if cleaned:
        return cleaned
    return [part.strip() for part in str(subcategory or '').split(',') if part.strip()]


def _match_tokens(title):
    words = re.findall(r'[a-z0-9]+', str(title or '').lower())
    return {
        word for word in words
        if len(word) >= 4 and not word.isdigit() and word not in _MATCH_STOP_WORDS
    }


def _suggestion_card(option):
    images = sorted(option.images_set.all(), key=lambda image: image.position)
    image = ''
    if images and images[0].image:
        image = images[0].image.url
    return {
        'id': str(option.id),
        'product_id': str(option.product_id),
        'title': str(option),
        'image': image,
        'price': float(option.effective_price()),
        'offer_price': float(option.effective_offer_price()),
        'quantity': option.quantity,
    }


def _cards_for_products(product_ids):
    if not product_ids:
        return []
    products = Product.objects.filter(id__in=product_ids).prefetch_related('options_set__images_set')
    by_id = {product.id: product for product in products}
    cards = []
    for product_id in product_ids:
        product = by_id.get(product_id)
        if product is None:
            continue
        options = list(product.options_set.all())
        if not options:
            continue
        option = next((item for item in options if item.quantity > 0), options[0])
        cards.append(_suggestion_card(option))
    return cards


def _product_suggestions(product):
    """Subcategory products under Related, plus name-matched products from this shop."""
    chips = {name.casefold() for name in _product_chip_names(product.subcategories, product.subcategory)}
    tokens = _match_tokens(product.title)
    barcode = str(product.barcode or '').strip()
    catalog = Product.objects.exclude(id=product.id)
    if product.vendor_id:
        catalog = catalog.filter(vendor_id=product.vendor_id)
    rows = catalog.values('id', 'title', 'subcategory', 'subcategories', 'barcode')

    related_ids = []
    matched = []
    for row in rows:
        row_chips = {name.casefold() for name in _product_chip_names(row['subcategories'], row['subcategory'])}
        if chips and row_chips & chips:
            if len(related_ids) < 12:
                related_ids.append(row['id'])
            continue
        score = 0
        if barcode and str(row['barcode'] or '').strip() == barcode:
            score += 5
        overlap = _match_tokens(row['title']) & tokens
        score += len(overlap)
        if score > 0:
            matched.append((score, row['id']))

    used = set(related_ids) | {product.id}
    matched.sort(key=lambda item: (-item[0], str(item[1])))
    matched_ids = []
    for _, product_id in matched:
        if product_id in used:
            continue
        matched_ids.append(product_id)
        if len(matched_ids) >= 12:
            break

    return {
        'related_products': _cards_for_products(related_ids),
        'matched_products': _cards_for_products(matched_ids),
    }


@api_view(['GET'])
def product_details(request):
    productId = request.GET.get('productId')

    if not productId:
        return Response(
            {'error': 'productId parameter is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Try to get as Product first
        try:
            product = Product.objects.get(id=productId)
        except Product.DoesNotExist:
            # Maybe it's a ProductOption ID - try to get the product from it
            try:
                product_option = ProductOption.objects.get(id=productId)
                product = product_option.product

                # Log this for debugging
                logger.warning(
                    f"ProductOption ID {productId} was used instead of Product ID. "
                    f"Returning product {product.id}"
                )
            except ProductOption.DoesNotExist:
                return Response(
                    {
                        'error': 'Product not found',
                        'message': f'No product or product option found with ID: {productId}',
                        'productId': productId
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

        data = ProductSerializer(product, many=False, context={'request': request}).data
        data.update(_product_suggestions(product))
        return Response(data)

    except ValueError:
        return Response(
            {
                'error': 'Invalid product ID format',
                'message': 'Product ID must be a valid UUID',
                'productId': productId
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Error in product_details: {str(e)}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def update_wishlist(request):
    id = request.GET.get('id')
    action = request.GET.get('action')
    user = request.user

    if action == 'ADD':
        user.wishlist.add(id)
        user.save()
    elif action == 'REMOVE':
        user.wishlist.remove(id)
        user.save()
    return Response('updated')


def _clear_user_cart_items(user, item_ids):
    """Remove product options from the user's cart after a successful order."""
    if not item_ids:
        return
    for item_id in item_ids:
        try:
            product_option = ProductOption.objects.get(id=item_id)
            user.cart.remove(product_option)
        except ProductOption.DoesNotExist:
            pass
    user.save()


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def update_cart(request):
    id = request.GET.get('id')
    action = request.GET.get('action')
    quantity = request.GET.get('quantity')
    user = request.user

    # Validate inputs
    if not id:
        return Response({'error': 'Product option ID is required'}, status=400)

    if action not in ['ADD', 'REMOVE', 'UPDATE_QUANTITY']:
        return Response({'error': 'Invalid action. Must be ADD, REMOVE, or UPDATE_QUANTITY'}, status=400)

    try:
        # Verify the ProductOption exists
        product_option = ProductOption.objects.get(id=id)

        # ✅ FIX: Check if item is actually in user's cart
        is_in_cart = user.cart.filter(id=id).exists()

        # ✅ NEW: Better error handling for cart state mismatches
        if action == 'UPDATE_QUANTITY' and not is_in_cart:
            return Response({
                'error': 'not_in_cart',
                'message': 'Item not in cart. Please add it first.',
                'should_reset': True  # Signal frontend to reset state
            }, status=400)

        if action == 'REMOVE' and not is_in_cart:
            return Response({
                'message': 'updated',
                'action': 'already_removed',
                'should_reset': True
            }, status=200)

        # Check stock for ADD and UPDATE_QUANTITY actions
        if action in ['ADD', 'UPDATE_QUANTITY']:
            if action == 'UPDATE_QUANTITY':
                if not quantity:
                    return Response({'error': 'Quantity is required for UPDATE_QUANTITY action'}, status=400)

                try:
                    quantity = int(quantity)
                    if quantity < 0:
                        return Response({'error': 'Quantity must be non-negative'}, status=400)
                    if quantity > product_option.quantity:
                        return Response({
                            'error': 'insufficient_stock',
                            'message': f'Only {product_option.quantity} units available',
                            'available_quantity': product_option.quantity
                        }, status=400)
                except ValueError:
                    return Response({'error': 'Invalid quantity value'}, status=400)

                # If quantity is 0, remove from cart
                if quantity == 0:
                    if is_in_cart:
                        user.cart.remove(product_option)
                        user.save()
                        return Response({
                            'message': 'updated',
                            'action': 'removed',
                            'reason': 'quantity_zero',
                            'product': product_option.product.title,
                            'option': product_option.option
                        })
                    else:
                        return Response({
                            'error': 'not_in_cart',
                            'message': 'Item not in your cart',
                            'should_reset': True
                        }, status=400)

                # Update quantity (stored in frontend, backend just validates)
                if is_in_cart:
                    return Response({
                        'message': 'updated',
                        'action': 'quantity_updated',
                        'quantity': quantity,
                        'product': product_option.product.title,
                        'option': product_option.option
                    })
                else:
                    return Response({
                        'error': 'not_in_cart',
                        'message': 'Item not in your cart',
                        'should_reset': True
                    }, status=400)

            elif action == 'ADD' and product_option.quantity <= 0:
                return Response({
                    'error': 'out_of_stock',
                    'message': f'{product_option.product.title} is currently out of stock'
                }, status=400)

        if action == 'ADD':
            if is_in_cart:
                return Response({
                    'message': 'already_in_cart',
                    'detail': 'Product is already in your cart'
                }, status=200)

            user.cart.add(product_option)
            user.save()

            return Response({
                'message': 'updated',
                'action': 'added',
                'product': product_option.product.title,
                'option': product_option.option
            })

        elif action == 'REMOVE':
            if is_in_cart:
                user.cart.remove(product_option)
                user.save()

            return Response({
                'message': 'updated',
                'action': 'removed' if is_in_cart else 'already_removed',
                'product': product_option.product.title,
                'option': product_option.option
            })

    except ProductOption.DoesNotExist:
        logger.error(f"ProductOption not found: {id}")

        try:
            product = Product.objects.get(id=id)
            first_option = product.options_set.filter(quantity__gt=0).first()

            if first_option:
                return Response({
                    'error': 'wrong_id_type',
                    'message': 'Product ID provided instead of ProductOption ID',
                    'suggestion': {
                        'correct_id': str(first_option.id),
                        'product': product.title,
                        'option': first_option.option
                    }
                }, status=400)
            else:
                return Response({
                    'error': 'no_options_available',
                    'message': f'{product.title} has no available options'
                }, status=400)
        except Product.DoesNotExist:
            return Response({
                'error': 'invalid_id',
                'message': 'The provided ID does not match any product or product option',
                'id_received': id
            }, status=404)

    except Exception as e:
        logger.error(f"Error updating cart: {str(e)}")
        return Response({
            'error': 'server_error',
            'message': 'An error occurred while updating the cart',
            'details': str(e)
        }, status=500)

def _signed_in_user(request):
    """App user with a real account. Guests stay anonymous and have no cart."""
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False):
        return user
    return None


@api_view(['GET'])
@permission_classes([AllowAny])
def wishlist(request):
    user = _signed_in_user(request)
    if user is None:
        return Response([])
    _wishlist = user.wishlist.all()
    data = WishlistSerializer(_wishlist, many=True).data
    return Response(data)


@api_view(['GET'])
@permission_classes([AllowAny])
def cart(request):
    user = _signed_in_user(request)
    if user is None:
        return Response([])
    id = request.GET.get('id')
    if id:
        products = ProductOption.objects.filter(id=id)
        data = CartSerializer(products, many=True).data
    else:
        products = user.cart.all()
        data = CartSerializer(products, many=True).data
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def updateaddress(request):
    name = request.data.get('name')
    address = request.data.get('address')
    pincode = request.data.get('pincode')
    contact_no = request.data.get('contact_no')
    label = request.data.get('label', 'Home')
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    address_id = request.data.get('address_id')

    if not address:
        address = _compose_address_line(
            (request.data.get('house') or '').strip(),
            (request.data.get('locality') or '').strip(),
            (request.data.get('landmark') or '').strip(),
            (request.data.get('city') or '').strip(),
            (request.data.get('state') or '').strip(),
            pincode,
        )

    if name and address and pincode and contact_no:
        try:
            user = request.user
            district, state = _lookup_district_state(pincode)

            if address_id:
                user_address = get_object_or_404(UserAddress, id=address_id, user=user)
            else:
                user_address = user.addresses_set.filter(is_default=True).first()
                if not user_address:
                    user_address = UserAddress(user=user, is_default=True)

            user_address.label = label or user_address.label or 'Home'
            user_address.name = name
            user_address.address = address
            user_address.contact_no = contact_no
            user_address.pincode = pincode
            if not request.data.get('city') and not request.data.get('state'):
                user_address.district = district
                user_address.city = district
                user_address.state = state
            if latitude is not None:
                user_address.latitude = latitude
            if longitude is not None:
                user_address.longitude = longitude
            _apply_address_details(user_address, request.data)

            if not user.addresses_set.exclude(id=user_address.id).exists():
                user_address.is_default = True

            user_address.save()
            _sync_user_profile_from_address(user, user_address)
            return Response(UserAddressSerializer(user_address).data)

        except Exception as e:
            return Response({'error': 'Failed to update address', 'details': str(e)}, status=400)
    else:
        return Response({'error': 'Missing required fields'}, status=400)


def _compose_address_line(house, locality, landmark, city, state, pincode, fallback=''):
    parts = [part for part in (house, locality, landmark, city, state) if part]
    line = ', '.join(parts)
    pin = str(pincode or '').strip()
    if pin and pin not in line:
        line = f'{line} - {pin}' if line else pin
    return line or fallback


def _apply_address_details(user_address, data):
    house = (data.get('house') or '').strip()
    locality = (data.get('locality') or '').strip()
    landmark = (data.get('landmark') or '').strip()
    city = (data.get('city') or data.get('district') or '').strip()
    state = (data.get('state') or '').strip()
    if house:
        user_address.house = house
    if locality:
        user_address.locality = locality
    if 'landmark' in data:
        user_address.landmark = landmark
    if city:
        user_address.city = city
        user_address.district = city
    if state:
        user_address.state = state
    composed = _compose_address_line(
        user_address.house,
        user_address.locality,
        user_address.landmark,
        user_address.city or user_address.district,
        user_address.state,
        user_address.pincode,
        fallback=(data.get('address') or user_address.address or ''),
    )
    if composed:
        user_address.address = composed


def _lookup_district_state(pincode):
    url = f"https://api.postalpincode.in/pincode/{pincode}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if data and data[0]['Status'] == "Success":
            post_office = data[0]['PostOffice'][0]
            return (
                post_office.get('District', 'Not Available'),
                post_office.get('State', 'Not Available'),
            )
    except Exception:
        pass
    return "Seoni", "Madhya Pradesh"


def _format_address_snapshot(address, pincode, district, state):
    """Location-only snapshot for delivery partners (no receiver name/phone)."""
    return (
        f"{address}\n"
        f"{pincode}\n"
        f"{district}\n"
        f"{state}\n"
    )


def _sync_user_profile_from_address(user, user_address):
    user.name = user_address.name
    user.address = user_address.address
    user.contact_no = user_address.contact_no
    user.pincode = user_address.pincode
    user.district = user_address.district
    user.state = user_address.state
    user.save()


def _set_default_address(user, user_address):
    user.addresses_set.exclude(id=user_address.id).update(is_default=False)
    user_address.is_default = True
    user_address.save()
    _sync_user_profile_from_address(user, user_address)


def _parse_bool_flag(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes')
    return bool(value)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedUser])
def user_addresses(request):
    user = request.user

    if request.method == 'GET':
        addresses = user.addresses_set.all()
        return Response(UserAddressSerializer(addresses, many=True).data)

    address = request.data.get('address')
    pincode = request.data.get('pincode')
    label = request.data.get('label', 'Home')
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    is_default = request.data.get('is_default', False)
    name = (request.data.get('name') or '').strip() or user.fullname or 'Customer'
    contact_no = (request.data.get('contact_no') or '').strip() or user.phone or ''

    if not address:
        address = _compose_address_line(
            (request.data.get('house') or '').strip(),
            (request.data.get('locality') or '').strip(),
            (request.data.get('landmark') or '').strip(),
            (request.data.get('city') or '').strip(),
            (request.data.get('state') or '').strip(),
            pincode,
        )

    if not all([address, pincode]):
        return Response({'error': 'Missing required fields'}, status=400)

    district, looked_up_state = _lookup_district_state(pincode)
    city = (request.data.get('city') or district or '').strip()
    state = (request.data.get('state') or looked_up_state or '').strip()
    make_default = is_default or not user.addresses_set.exists()

    user_address = UserAddress.objects.create(
        user=user,
        label=label or 'Home',
        name=name,
        address=address,
        house=(request.data.get('house') or '').strip(),
        locality=(request.data.get('locality') or '').strip(),
        landmark=(request.data.get('landmark') or '').strip(),
        city=city,
        pincode=pincode,
        contact_no=contact_no,
        district=city or district,
        state=state,
        latitude=latitude,
        longitude=longitude,
        is_default=make_default,
    )
    _apply_address_details(user_address, request.data)
    user_address.save()

    if make_default:
        _set_default_address(user, user_address)
    else:
        user_address.save()

    return Response(UserAddressSerializer(user_address).data, status=201)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticatedUser])
def user_address_detail(request, address_id):
    user = request.user
    user_address = get_object_or_404(UserAddress, id=address_id, user=user)

    if request.method == 'DELETE':
        was_default = user_address.is_default
        user_address.delete()
        if was_default:
            next_default = user.addresses_set.first()
            if next_default:
                _set_default_address(user, next_default)
            else:
                user.name = ''
                user.address = ''
                user.contact_no = ''
                user.pincode = None
                user.district = ''
                user.state = ''
                user.save()
        return Response({'message': 'Address deleted'})

    name = request.data.get('name')
    address = request.data.get('address')
    pincode = request.data.get('pincode')
    contact_no = request.data.get('contact_no')
    label = request.data.get('label', user_address.label)
    latitude = request.data.get('latitude')
    longitude = request.data.get('longitude')
    is_default = (
        _parse_bool_flag(request.data.get('is_default'))
        if 'is_default' in request.data
        else None
    )

    if name:
        user_address.name = name
    if address:
        user_address.address = address
    if pincode:
        user_address.pincode = pincode
        if not request.data.get('city') and not request.data.get('state'):
            user_address.district, user_address.state = _lookup_district_state(pincode)
            user_address.city = user_address.district
    if contact_no:
        user_address.contact_no = contact_no
    if label:
        user_address.label = label
    if latitude is not None:
        user_address.latitude = latitude
    if longitude is not None:
        user_address.longitude = longitude
    _apply_address_details(user_address, request.data)

    user_address.save()

    if is_default is True:
        _set_default_address(user, user_address)
    elif is_default is False and user_address.is_default:
        user_address.is_default = False
        user_address.save()
    elif user_address.is_default:
        _sync_user_profile_from_address(user, user_address)

    user_address.refresh_from_db()
    return Response(UserAddressSerializer(user_address).data)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def set_default_address(request, address_id):
    user = request.user
    user_address = get_object_or_404(UserAddress, id=address_id, user=user)
    _set_default_address(user, user_address)
    return Response(UserAddressSerializer(user_address).data)


def _resolve_order_address(user, address_id, address_text, order_for_someone_else):
    if address_id:
        user_address = get_object_or_404(UserAddress, id=address_id, user=user)

        formatted = _format_address_snapshot(
            user_address.address,
            user_address.pincode,
            user_address.district,
            user_address.state,
        )
        return (formatted, user_address), None

    if address_text and address_text != 'No address provided':
        return (address_text, None), None

    default_address = user.addresses_set.filter(is_default=True).first()
    if default_address:
        formatted = _format_address_snapshot(
            default_address.address,
            default_address.pincode,
            default_address.district,
            default_address.state,
        )
        return (formatted, default_address), None

    if user.address and user.pincode:
        formatted = _format_address_snapshot(
            user.address,
            user.pincode,
            user.district,
            user.state,
        )
        return (formatted, None), None

    return None, Response({
        'error': 'address_missing',
        'message': 'Please add a delivery address before placing your order.',
    }, status=400)

@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def initiate_payment(request):
    items = request.data.get('items')
    from_cart = request.data.get('from_cart')
    tx_amount = request.data.get('tx_amount')
    payment_mode = request.data.get('payment_mode')

    query = Q(id=items[0]['id'])
    for item in items:
        query = query | Q(id=item['id'])

    product_options = ProductOption.objects.filter(query)

    ordered_products = []
    server_tx_amount = 0
    for option in product_options:
        for item in items:
            if str(option.id) == item['id']:
                option.quantity = option.quantity - item['quantity']
                unit_price = option.effective_offer_price()
                order_tx_price = (unit_price * item['quantity']) + option.product.delivery_charge
                server_tx_amount = server_tx_amount + order_tx_price

                order_option = OrderedProduct()
                order_option.quantity = item['quantity']
                order_option.product_option = option
                order_option.vendor = getattr(option.product, 'vendor', None)
                order_option.product_price = unit_price
                order_option.delivery_price = option.product.delivery_charge
                order_option.tx_price = order_tx_price
                ordered_products.append(order_option)

    try:
        client_amount = parse_price(tx_amount)
        server_amount = parse_price(server_tx_amount)
    except ValueError:
        return Response("invalid_amount", 400)

    if abs(client_amount - server_amount) > parse_price('0.01'):
        return Response("amount_mismatched", 400)

    order = Order()
    order.user = request.user
    order.from_cart = from_cart
    order.tx_amount = server_tx_amount
    order.address = request.user.name + "\n" \
                    + request.user.contact_no + "\n" \
                    + request.user.address + "\n" \
                    + str(request.user.pincode) \
                    + request.user.district + "\n" \
                    + request.user.state + "\n"
    order.payment_mode = payment_mode
    order.pending_orders = len(ordered_products)
    order.tx_status = 'INITIATED'
    shop = next((row.product.vendor for row in product_options if getattr(row.product, 'vendor_id', None)), None)
    order.vendor = shop
    order.save()

    for ordered_product in ordered_products:
        ordered_product.order = order
        ordered_product.save()

    for option in product_options:
        option.save()

    if payment_mode == 'COD':
        data = {
            "token": "",
            "orderId": order.id,
            "tx_amount": server_tx_amount,
            "appId": CF_ID,
            "orderCurrency": "INR",
        }
        return Response(data)

    headers = {
        'Content-Type': 'application/json',
        'x-client-id': CF_ID,
        'x-client-secret': CF_KEY,
    }

    data = {
        "orderId": str(order.id),
        "orderAmount": server_tx_amount,
        "orderCurrency": "INR",
    }

    response = requests.post("https://test.cashfree.com/api/v2/cftoken/order",
                             headers=headers, data=json.dumps(data))
    if response.json()['status'] == 'OK':
        data = {
            "token": response.json()['cftoken'],
            "orderId": order.id,
            "tx_amount": server_tx_amount,
            "appId": CF_ID,
            "orderCurrency": "INR",
        }
        return Response(data)
    else:
        print(response.json())
        order.tx_status = "FAILED"
        order.tx_msg = "CLICKWELL_SERVER_MSG: Failed to generate cftoken"
        order.save()
        return Response("Something went wrong", 400)


@api_view(['POST'])
def notify_url(request):
    try:
        # Parse incoming data
        data = request.data
        order_id = data.get('orderId')
        tx_status = data.get('txStatus')
        tx_msg = data.get('txMsg', '')
        payment_mode = data.get('paymentMode')
        tx_time = data.get('txTime')
        reference_id = data.get('referenceId', '')
        order_amount = data.get('orderAmount', '')

        # Log the incoming request data for debugging
        print(f"Incoming notify_url data: {data}")

        # Validate incoming order_id
        if not order_id:
            return Response(
                {'status': 'error', 'message': 'Order ID is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch the order based on `orderId`
        if payment_mode == 'COD':
            # Fetch by UUID for COD
            order = get_object_or_404(Order, id=order_id)
        else:
            # Fetch by tx_id for online payments
            order = get_object_or_404(Order, tx_id=order_id)

        # Normalize the order amount for comparison (supports decimal rupee amounts).
        try:
            if payment_mode == 'COD':
                client_order_amount = parse_price(order_amount)
            else:
                client_order_amount = parse_price(order_amount) / Decimal('100')
            server_order_amount = parse_price(order.tx_amount)
        except ValueError:
            return Response(
                {'status': 'error', 'message': 'Invalid order amount.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if abs(client_order_amount - server_order_amount) > Decimal('0.01'):
            print(
                f"Order amount mismatch: Received {client_order_amount}, "
                f"Expected {server_order_amount}"
            )
            return Response(
                {'status': 'error', 'message': 'Order amount mismatch.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update the order fields
        order.tx_status = tx_status
        order.tx_msg = tx_msg
        order.tx_time = tx_time
        order.payment_mode = payment_mode
        order.tx_id = reference_id
        order.save()

        if tx_status == 'SUCCESS' and order.from_cart:
            ordered_option_ids = order.orders_set.values_list(
                'product_option_id', flat=True
            )
            _clear_user_cart_items(order.user, ordered_option_ids)

        # Log success
        print(f"Order {order.id} updated successfully with status {tx_status}")

        # Return a success response
        return Response(
            {'status': 'success', 'message': 'Order updated successfully.'},
            status=status.HTTP_200_OK
        )

    except Order.MultipleObjectsReturned:
        print(f"Multiple orders found for orderId: {order_id}")
        return Response(
            {'status': 'error', 'message': f'Multiple orders found for orderId: {order_id}'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Order.DoesNotExist:
        print(f"No order found for orderId: {order_id}")
        return Response(
            {'status': 'error', 'message': f'No order found for orderId: {order_id}'},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        print(f"Exception in notify_url: {str(e)}")
        return Response(
            {'status': 'error', 'message': 'Internal Server Error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _order_delivery_fields(data):
    raw_type = str(data.get('delivery_type') or '').strip().lower()
    if raw_type in ('quick', 'express'):
        delivery_type = 'quick'
    elif raw_type == 'scheduled':
        delivery_type = 'scheduled'
    elif data.get('delivery_slot'):
        delivery_type = 'scheduled'
    elif data.get('delivery_eta') or data.get('express') is True:
        delivery_type = 'quick'
    else:
        delivery_type = ''
    date_text = str(data.get('delivery_date') or '').strip()[:10]
    delivery_date = None
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_text):
        delivery_date = datetime.date.fromisoformat(date_text)
    return {
        'delivery_type': delivery_type,
        'delivery_date': delivery_date,
        'delivery_slot': str(data.get('delivery_slot') or '').strip()[:120],
        'delivery_eta': str(data.get('delivery_eta') or '').strip()[:120],
    }


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def initiate_order(request):
    """
    Handles the creation of an order with support for COD and Razorpay payments.
    Updated to use centralized delivery charge calculation.
    """
    try:
        user = request.user  # Now properly authenticated
        items = request.data.get('items')
        from_cart = request.data.get('from_cart', False)
        tx_amount = request.data.get('tx_amount')
        payment_mode = request.data.get('payment_mode', 'ONLINE')
        address = request.data.get('address', 'No address provided')
        address_id = request.data.get('address_id')
        order_for_someone_else = bool(request.data.get('order_for_someone_else', False))
        raw_contact_name = (request.data.get('delivery_contact_name') or '').strip()
        raw_contact_phone = (request.data.get('delivery_contact_phone') or '').strip()

        resolved, address_error = _resolve_order_address(
            user, address_id, address, order_for_someone_else
        )
        if address_error:
            return address_error
        address, user_address = resolved

        if raw_contact_name:
            delivery_contact_name = raw_contact_name
        elif user_address and (user_address.name or '').strip():
            delivery_contact_name = user_address.name.strip()
        else:
            delivery_contact_name = (user.fullname or user.name or '').strip()

        if raw_contact_phone:
            delivery_contact_phone = raw_contact_phone
        elif user_address and (user_address.contact_no or '').strip():
            delivery_contact_phone = user_address.contact_no.strip()
        else:
            delivery_contact_phone = (user.phone or user.contact_no or '').strip()

        # FIXED: Better validation with detailed error messages
        if not items:
            return Response({
                "error": "data_missing",
                "message": "Items list is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        if tx_amount is None:
            return Response({
                "error": "data_missing",
                "message": "Transaction amount is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        # FIXED: Validate items structure
        if not isinstance(items, list) or len(items) == 0:
            return Response({
                "error": "invalid_data",
                "message": "Items must be a non-empty list"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate each item
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                return Response({
                    "error": "invalid_data",
                    "message": f"Item {i} must be an object"
                }, status=status.HTTP_400_BAD_REQUEST)

            if 'id' not in item or 'quantity' not in item:
                return Response({
                    "error": "invalid_data",
                    "message": f"Item {i} must have 'id' and 'quantity' fields"
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                quantity = int(item['quantity'])
                if quantity <= 0:
                    return Response({
                        "error": "invalid_data",
                        "message": f"Item {i} quantity must be greater than 0"
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError):
                return Response({
                    "error": "invalid_data",
                    "message": f"Item {i} quantity must be a valid number"
                }, status=status.HTTP_400_BAD_REQUEST)

        # FIXED: Better query building logic
        product_ids = [item['id'] for item in items]
        query = Q(id__in=product_ids)

        try:
            product_options = ProductOption.objects.filter(query).select_related('product__vendor')

            if not product_options.exists():
                return Response({
                    "error": "products_not_found",
                    "message": "No products found for the given IDs"
                }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                "error": "database_error",
                "message": f"Error fetching products: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # UPDATED: Calculate items amount first (without individual delivery charges)
        ordered_products = []
        server_items_amount = Decimal('0')
        product_lookup = {str(option.id): option for option in product_options}

        for item in items:
            item_id = str(item['id'])
            quantity = int(item['quantity'])

            if item_id not in product_lookup:
                return Response({
                    "error": "product_not_found",
                    "message": f"Product with ID {item_id} not found"
                }, status=status.HTTP_404_NOT_FOUND)

            option = product_lookup[item_id]

            # Reject out-of-stock and insufficient quantity before placing order.
            if option.quantity <= 0:
                return Response({
                    "error": "out_of_stock",
                    "message": f"{option.product.title} is out of stock",
                    "available_quantity": 0,
                }, status=status.HTTP_400_BAD_REQUEST)

            if option.quantity < quantity:
                return Response({
                    "error": "insufficient_stock",
                    "message": f"Only {option.quantity} units available for {option.product.title}",
                    "available_quantity": option.quantity,
                }, status=status.HTTP_400_BAD_REQUEST)

            # FIXED: Better error handling for price calculation
            try:
                offer_price = option.effective_offer_price()

                # Reduce stock temporarily (will be saved later)
                option.quantity -= quantity

                # Calculate item price (without delivery charge)
                item_price = Decimal(str(offer_price)) * quantity
                server_items_amount += item_price

                # Prepare OrderedProduct (delivery will be added later)
                ordered_product = OrderedProduct(
                    product_option=option,
                    vendor=getattr(option.product, 'vendor', None),
                    product_price=offer_price,
                    tx_price=item_price,  # Will be updated with delivery portion
                    delivery_price=0,  # Will be calculated centrally
                    quantity=quantity
                )
                ordered_products.append(ordered_product)

            except (AttributeError, TypeError) as e:
                return Response({
                    "error": "price_calculation_error",
                    "message": f"Error calculating price for {option.product.title}: {str(e)}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # NEW: Apply centralized delivery charge calculation
        try:
            shop = next((row.product.vendor for row in product_options if row.product.vendor_id), None)
            delivery_charge, _, _ = _delivery_charge_for(server_items_amount, shop)
            server_tx_amount = server_items_amount + delivery_charge

            # Debug logging
            print(f"🔍 Order Calculation Debug:")
            print(f"   Items amount: ₹{server_items_amount}")
            print(f"   Delivery charge: ₹{delivery_charge}")
            print(f"   Server total: ₹{server_tx_amount}")
            print(f"   Client total: ₹{tx_amount}")

        except Exception as e:
            return Response({
                "error": "delivery_calculation_error",
                "message": f"Failed to calculate delivery charge: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # FIXED: Better amount comparison with detailed logging
        try:
            client_amount = parse_price(tx_amount)
            server_amount = server_tx_amount.quantize(Decimal('0.01'))

            # Allow small floating point differences (1 cent tolerance)
            if abs(client_amount - server_amount) > Decimal('0.01'):
                return Response({
                    "error": "amount_mismatched",
                    "message": f"Amount mismatch: client={client_amount}, server={server_amount}",
                    "client_amount": client_amount,
                    "server_amount": server_amount,
                    "items_amount": server_items_amount,
                    "delivery_charge": delivery_charge,
                    "breakdown": {
                        "items_total": server_items_amount,
                        "delivery_charge": delivery_charge,
                        "calculated_total": server_amount
                    }
                }, status=status.HTTP_400_BAD_REQUEST)

        except (ValueError, TypeError) as e:
            return Response({
                "error": "invalid_amount",
                "message": f"Invalid transaction amount: {str(e)}"
            }, status=status.HTTP_400_BAD_REQUEST)

        # FIXED: Use transaction to ensure data consistency
        try:
            with transaction.atomic():
                # Create the order in the database
                order_latitude = None
                order_longitude = None
                if user_address is not None:
                    order_latitude = user_address.latitude
                    order_longitude = user_address.longitude

                delivery_fields = _order_delivery_fields(request.data)
                order = Order.objects.create(
                    user=user,
                    vendor=shop,
                    tx_amount=server_tx_amount,
                    payment_mode=payment_mode,
                    address=address,
                    from_cart=from_cart,
                    tx_status='INITIATED',
                    order_for_someone_else=order_for_someone_else,
                    delivery_contact_name=delivery_contact_name,
                    delivery_contact_phone=delivery_contact_phone,
                    user_address=user_address,
                    latitude=order_latitude,
                    longitude=order_longitude,
                    **delivery_fields,
                )

                # NEW: Distribute delivery charge among products
                # Simple approach: assign all delivery charge to the first product
                if ordered_products and delivery_charge > 0:
                    ordered_products[0].delivery_price = delivery_charge
                    ordered_products[0].tx_price += delivery_charge

                # Save ordered products
                for op in ordered_products:
                    op.order = order
                    op.save()

                # Save updated stock quantities
                for option in product_options:
                    option.save()

                # Handle COD orders
                if payment_mode.upper() == "COD":
                    order.tx_status = 'SUCCESS'
                    order.tx_msg = 'Cash on Delivery selected'
                    order.payment_mode = 'COD'
                    order.save()

                    if from_cart:
                        _clear_user_cart_items(user, product_ids)

                    return Response({
                        "orderId": str(order.id),
                        "orderedProductId": str(ordered_products[0].id) if ordered_products else str(order.id),
                        "orderAmount": str(server_tx_amount),
                        "paymentMode": "COD",
                        "message": "Order placed successfully with Cash on Delivery.",
                        "breakdown": {
                            "items_total": server_items_amount,
                            "delivery_charge": delivery_charge,
                            "final_total": server_tx_amount
                        }
                    }, status=status.HTTP_200_OK)

                # Handle Razorpay orders
                try:
                    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
                    amount_in_paise = int(server_tx_amount * 100)

                    razorpay_order_data = {
                        "amount": amount_in_paise,
                        "currency": "INR",
                        "receipt": str(order.id),
                        "payment_capture": 1,
                    }

                    rzp_order = client.order.create(data=razorpay_order_data)

                    # Store Razorpay order ID in the database
                    order.tx_id = rzp_order.get("id")
                    order.save()

                    return Response({
                        "orderId": rzp_order.get("id"),
                        "razorpayKey": RAZORPAY_KEY_ID,
                        "amount": amount_in_paise,
                        "currency": "INR",
                        "clickwellOrderId": str(order.id),
                        "breakdown": {
                            "items_total": server_items_amount,
                            "delivery_charge": delivery_charge,
                            "final_total": server_tx_amount
                        }
                    }, status=status.HTTP_200_OK)

                except Exception as e:
                    order.tx_status = 'FAILED'
                    order.tx_msg = f"Razorpay error: {str(e)}"
                    order.save()

                    return Response({
                        "error": "payment_gateway_error",
                        "message": "Failed to create payment order",
                        "details": str(e)
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"Error creating order: {str(e)}")
            return Response({
                "error": "order_creation_failed",
                "message": "Failed to create order",
                "details": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Exception as e:
        logger.error(f"Unexpected error in initiate_order: {str(e)}")
        return Response({
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _line_image_url(option):
    images = list(option.images_set.all())
    if not images:
        return None
    images.sort(key=lambda row: row.position)
    image = images[0].image
    if not image:
        return None
    try:
        return image.url
    except Exception:
        return None


def _rollup_order_status(statuses):
    if not statuses:
        return 'ORDERED'
    if all(status == 'CANCELLED' for status in statuses):
        return 'CANCELLED'
    if any(status == 'OUT_FOR_DELIVERY' for status in statuses):
        return 'OUT_FOR_DELIVERY'
    if any(status == 'ORDERED' for status in statuses):
        return 'ORDERED'
    if all(status == 'DELIVERED' for status in statuses):
        return 'DELIVERED'
    return statuses[0]


def _order_list_card(order):
    items = list(order.orders_set.all())
    first = items[0] if items else None
    images = []
    option_ids = []
    qty = 0
    shop = ''
    for item in items:
        option = item.product_option
        option_ids.append(str(option.id))
        qty += item.quantity or 1
        url = _line_image_url(option)
        if url and url not in images:
            images.append(url)
        if not shop:
            vendor = getattr(option.product, 'vendor', None)
            shop = getattr(vendor, 'shop_name', '') or ''
    amount = order.tx_amount
    if not amount:
        amount = sum((item.tx_price or 0) for item in items)
    return {
        'id': str(first.id) if first else str(order.id),
        'order_id': str(order.id),
        'title': first.product_option.__str__() if first else '',
        'shop_name': shop,
        'image': images[0] if images else None,
        'images': images,
        'item_count': qty,
        'option_ids': option_ids,
        'amount': str(amount or 0),
        'created_at': format_order_datetime(order.created_at),
        'quantity': qty,
        'status': _rollup_order_status([item.status for item in items]),
        'rating': max((item.rating or 0) for item in items) if items else 0,
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def orders(request):
    user = _signed_in_user(request)
    if user is None:
        return Response({'count': 0, 'next': None, 'previous': None, 'results': []})
    orders = (
        Order.objects.filter(user=user)
        .prefetch_related(
            'orders_set__product_option__product__vendor',
            'orders_set__product_option__images_set',
        )
        .order_by('-created_at')
    )
    pagination = LimitOffsetPagination()
    queryset = pagination.paginate_queryset(orders, request)
    data = [_order_list_card(order) for order in queryset]
    return pagination.get_paginated_response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def orderdetails(request):
    lookup = (request.GET.get('id') or '').strip()
    qs = OrderedProduct.objects.select_related(
        'order', 'order__user', 'order__user_address',
        'product_option', 'product_option__product',
        'product_option__product__vendor',
    )
    line = qs.filter(id=lookup).first()
    if line is None and lookup:
        line = qs.filter(order_id=lookup).order_by('created_at').first()
    user = _signed_in_user(request)
    if line is None or (user is not None and line.order.user_id != user.id):
        return Response(
            {'detail': 'Order not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    data = OrderDetailsSerializer(line, many=False, context={'request': request}).data
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def updaterating(request):
    orderId = request.GET.get('id')
    new_rating = int(request.GET.get('rating'))

    order = get_object_or_404(OrderedProduct, id=orderId)
    initial_rating = order.rating
    order.rating = new_rating

    if initial_rating == 1:
        order.product_option.product.star_1 -= 1
    elif initial_rating == 2:
        order.product_option.product.star_2 -= 1
    elif initial_rating == 3:
        order.product_option.product.star_3 -= 1
    elif initial_rating == 4:
        order.product_option.product.star_4 -= 1
    elif initial_rating == 5:
        order.product_option.product.star_5 -= 1

    if new_rating == 1:
        order.product_option.product.star_1 += 1
    elif new_rating == 2:
        order.product_option.product.star_2 += 1
    elif new_rating == 3:
        order.product_option.product.star_3 += 1
    elif new_rating == 4:
        order.product_option.product.star_4 += 1
    elif new_rating == 5:
        order.product_option.product.star_5 += 1

    order.product_option.product.save()
    order.save()

    return Response('updated')


# Grocery intent → brand/product keywords (Blinkit-style “search biscuit → Parle, Oreo…”)
SEARCH_INTENT_KEYWORDS = {
    'biscuit': ['parle', 'marie', 'glucose', 'oreo', 'britannia', 'sunfeast', 'good day', 'monaco', 'krackjack', 'biscuit'],
    'biscuits': ['parle', 'marie', 'glucose', 'oreo', 'britannia', 'sunfeast', 'good day', 'monaco', 'biscuit'],
    'oil': ['oil', 'saffola', 'fortune', 'dhara', 'sunflower', 'mustard', 'coconut', 'olive', 'groundnut'],
    'rice': ['rice', 'basmati', 'india gate', 'kohinoor', 'fortune'],
    'chocolate': ['chocolate', 'cadbury', 'dairy milk', 'silk', 'kitkat', '5 star', 'gems', 'perk', 'eclairs'],
    'tea': ['tea', 'tata', 'red label', 'lipton', 'green tea'],
    'soap': ['soap', 'lux', 'dove', 'pears', 'lifebuoy', 'dettol', 'santoor', 'cinthol', 'rexona'],
    'shampoo': ['shampoo', 'pantene', 'tresemme', 'sunsilk'],
    'detergent': ['surf', 'ariel', 'tide', 'wheel', 'nirma', 'ghadi', 'rin', 'washing', 'detergent'],
    'washing powder': ['surf', 'ariel', 'tide', 'wheel', 'nirma', 'ghadi', 'rin', 'washing'],
    'toothpaste': ['toothpaste', 'colgate', 'pepsodent', 'close up', 'sensodyne', 'dabur'],
    'dal': ['dal', 'moong', 'chana', 'toor', 'urad'],
    'atta': ['atta', 'flour', 'chakki', 'aashirvaad', 'fortune', 'patanjali'],
    'milk': ['milk', 'amul', 'dairy', 'cream', 'curd', 'paneer', 'lassi'],
    'noodles': ['noodles', 'maggi', 'yippee', 'pasta', 'hakka'],
    'snacks': ['lays', 'kurkure', 'haldiram', 'namkeen', 'mixture', 'bhujia', 'chips', 'snack'],
    'coffee': ['coffee', 'nescafe', 'bru', 'instant'],
    'sauce': ['sauce', 'kissan', 'maggi', 'tomato', 'chilli'],
    'pickle': ['pickle', 'achar', 'patanjali', 'nilons'],
    'achar': ['pickle', 'achar', 'patanjali', 'nilons'],
    'honey': ['honey', 'dabur', 'patanjali'],
    'salt': ['salt', 'tata', 'rock salt'],
    'ghee': ['ghee', 'amul', 'patanjali'],
    'butter': ['butter', 'amul', 'britannia'],
    'bread': ['bread', 'britannia', 'pav'],
    'egg': ['egg', 'eggs'],
    'eggs': ['egg', 'eggs'],
    'vegetable': ['vegetable', 'onion', 'potato', 'tomato'],
    'vegetables': ['vegetable', 'onion', 'potato', 'tomato'],
    'fruit': ['fruit', 'apple', 'banana', 'orange'],
    'fruits': ['fruit', 'apple', 'banana', 'orange'],
    'cleaning': ['cleaner', 'lizol', 'harpic', 'domex', 'colin', 'mop', 'detergent'],
    'hair oil': ['hair', 'parachute', 'amla', 'dove', 'livon'],
}


def _search_intent_terms(query_lower):
    """Expand query using intent map + live category names from DB."""
    terms = set()
    keywords = [k for k in query_lower.split() if len(k) >= 2]

    for key, brand_list in SEARCH_INTENT_KEYWORDS.items():
        if query_lower == key or key in query_lower or query_lower in key:
            terms.update(brand_list)
        for kw in keywords:
            if kw == key or (len(kw) >= 3 and (kw in key or key.startswith(kw))):
                terms.update(brand_list)

    for cat_name in Category.objects.filter(name__icontains=query_lower).values_list('name', flat=True)[:5]:
        terms.add(cat_name.lower())

    return terms


def _build_product_search_q(query_lower, intent_terms):
    keywords = [k for k in query_lower.split() if k.strip()]
    combined = Q()

    for kw in keywords:
        combined |= (
            Q(product__title__icontains=kw)
            | Q(option__icontains=kw)
            | Q(product__category__name__icontains=kw)
            | Q(product__description__icontains=kw)
        )

    if len(query_lower) >= 2:
        combined |= Q(product__title__icontains=query_lower)

    for term in intent_terms:
        combined |= Q(product__title__icontains=term) | Q(option__icontains=term)

    matching_cats = Category.objects.filter(name__icontains=query_lower)
    if matching_cats.exists():
        combined |= Q(product__category__in=matching_cats)

    return combined


def _search_suggest_payload(query, vendor=None):
    query = query.strip()
    if len(query) < 1:
        popular = list(Category.objects.order_by('position').values_list('name', flat=True)[:12])
        return {'categories': popular, 'products': [], 'suggestions': popular}

    categories = []
    seen = set()

    for cat in Category.objects.filter(name__icontains=query).order_by('position')[:5]:
        key = cat.name.lower()
        if key not in seen:
            categories.append(cat.name)
            seen.add(key)

    options = ProductOption.objects.filter(
        Q(product__title__icontains=query) | Q(option__icontains=query)
        | Q(product__category__name__icontains=query)
    )
    if vendor:
        options = options.filter(product__vendor_id=vendor)
    options = (
        options
        .select_related('product', 'product__category')
        .prefetch_related('images_set')
        .order_by('-quantity', 'product__title')[:12]
    )

    products = [_serialize_option_for_catalog(opt) for opt in options]
    suggestions = categories + [p['title'] for p in products[:6]]

    return {
        'categories': categories,
        'products': products[:10],
        'suggestions': suggestions[:10],
    }


@api_view(['GET'])
def search(request):
    """
    Smart product search for quick-commerce app.

    Modes:
      ?query=milk&limit=20           — paginated product grid
      ?query=mil&suggest=1           — autocomplete suggestions + preview
      ?popular=1                     — trending category names for chips
    """
    if request.GET.get('popular') in ('1', 'true', 'yes'):
        names = list(Category.objects.order_by('position').values_list('name', flat=True)[:14])
        return Response({'popular': names})

    query_raw = request.GET.get('query', '').strip()
    if request.GET.get('suggest') in ('1', 'true', 'yes'):
        return Response(_search_suggest_payload(query_raw, request.GET.get('vendor')))

    if len(query_raw) < 2:
        pagination = LimitOffsetPagination()
        return pagination.get_paginated_response([])

    query_lower = query_raw.lower()
    intent_terms = _search_intent_terms(query_lower)
    combined = _build_product_search_q(query_lower, intent_terms)

    if not combined:
        pagination = LimitOffsetPagination()
        return pagination.get_paginated_response([])

    keywords = [k for k in query_lower.split() if k]
    ranking_cases = []

    for i, kw in enumerate(keywords):
        ranking_cases.extend([
            When(product__title__istartswith=kw, then=Value(920 - i * 5)),
            When(product__title__icontains=kw, then=Value(860 - i * 5)),
            When(option__icontains=kw, then=Value(820 - i * 5)),
            When(product__category__name__icontains=kw, then=Value(780 - i * 5)),
        ])

    if len(query_lower) >= 2:
        ranking_cases.append(When(product__title__icontains=query_lower, then=Value(900)))

    for term in intent_terms:
        ranking_cases.append(When(product__title__icontains=term, then=Value(650)))
        ranking_cases.append(When(option__icontains=term, then=Value(620)))

    ranking_cases.append(When(product__description__icontains=query_lower, then=Value(350)))
    ranking_cases.append(When(quantity__gt=0, then=Value(80)))

    products = ProductOption.objects.filter(combined)
    if request.GET.get('vendor'):
        products = products.filter(product__vendor_id=request.GET.get('vendor'))
    products = (
        products
        .select_related('product', 'product__category')
        .prefetch_related('images_set')
        .annotate(
            relevance_score=Case(
                *ranking_cases,
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by('-relevance_score', '-quantity', 'product__title', 'option')
        .distinct()
    )

    pagination = LimitOffsetPagination()
    page = pagination.paginate_queryset(products, request)
    data = [_serialize_option_for_catalog(opt) for opt in page]
    return pagination.get_paginated_response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def updateinfo(request):
    phone = request.data.get('phone')
    email = request.data.get('email')
    name = request.data.get('fullname')
    password = request.data.get('password')

    if not email or not phone or not name or not password:
        return Response('params_missing', 400)

    if check_password(password, request.user.password):
        if phone != request.user.phone:
            if User.objects.filter(phone=phone).exists():
                return Response('phone already exists', 400)
            otp_obj = get_object_or_404(Otp, phone=phone, verified=True)
            otp_obj.delete()

        if email != request.user.email:
            if User.objects.filter(email=email).exists():
                return Response('email already exists', 400)

        user = request.user
        user.phone = phone
        user.email = email
        user.fullname = name
        user.save()
        return Response('updated_successfully')
    else:
        return Response('incorrect_password', 401)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def update_phone_request_otp(request):
    phone = request.data.get('phone')
    password = request.data.get('password')

    if check_password(password, request.user.password):
        if not phone:
            return Response('params_missing', 400)

        if User.objects.filter(phone=phone).exists():
            return Response('phone already exists', 400)
        else:
            return send_otp(phone)
    else:
        return Response('incorrect_password', 401)


@api_view(['POST'])
@permission_classes([IsAuthenticatedUser])
def change_password(request):
    old_password = request.data.get('old_password')
    new_password = request.data.get('new_password')

    if check_password(old_password, request.user.password):
        request.user.password = make_password(new_password)
        request.user.save()
        Token.objects.filter(user=request.user).delete()
        return Response('password_updated')
    else:
        return Response('incorrect_password', 401)



@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def notifications(request):
    pagination = LimitOffsetPagination()

    request.user.notifications_set.filter(seen=False).update(seen=True)

    notifications_set = request.user.notifications_set.all().order_by('-created_at')

    queryset = pagination.paginate_queryset(notifications_set, request)

    data = NotificationSerializer(queryset, many=True).data
    return pagination.get_paginated_response(data)




@api_view(['POST'])
def forgot_password(request):
    phone = request.data.get('phone')

    if not phone:
        return Response({'error': 'Phone number is missing.'}, status=400)

    try:
        user = User.objects.get(phone=phone)
        # Proceed to send OTP to the user's phone
        send_otp(phone)  # Assuming this function is defined elsewhere and handles OTP sending
        return Response({'message': 'OTP sent successfully.'}, status=200)
    except ObjectDoesNotExist:
        return Response({'error': 'Phone number not found.'}, status=404)


def privacy_policy(request):
    return render(request, 'privacy_policy.html')




class PrivacyPolicyAPIView(APIView):
    def get(self, request):
        response = render(request, 'privacy_policy.html')
        html_content = response.content.decode('utf-8')
        data = {
            'content': html_content
        }
        return Response(data)


def contact_us(request):
    return render(request, 'contact_us.html')

class ContactUsAPIView(APIView):
    def get(self,request):
        response = render(request,'contact_us.html')
        html_contact = response.content.decode('utf-8')
        data = {
            'content': html_contact
        }
        return Response(data)


@api_view(['POST'])
def forgotpassword(request):
    phone = request.data.get('phone')

    if not phone:
        return Response({'error': 'Phone number is missing.'}, status=400)

    try:
        # Validate and retrieve the user by phone
        user = User.objects.get(phone=phone)
        # Assuming send_otp function returns True on success, False otherwise
        if send_otp(phone):  # This sends the OTP and checks if sending was successful
            return Response({'message': 'OTP sent successfully.'}, status=200)
        else:
            # Handling case where OTP sending failed
            return Response({'error': 'Failed to send OTP.'}, status=500)
    except User.DoesNotExist:
        return Response({'error': 'Phone number not found.'}, status=404)




@api_view(['POST'])
def verify_pass_otp(request): #Todo True
    phone = request.data.get('phone')
    otp = request.data.get('otp')

    # Ensure otp is an integer
    try:
        otp = int(otp)
    except ValueError:
        return Response('OTP must be a number.', status=400)

    otp_obj = get_object_or_404(Otp, phone=phone, verified=False)

    if otp_obj.validity.replace(tzinfo=None) > datetime.datetime.utcnow():
        if otp_obj.otp == otp:
            otp_obj.verified = True
            otp_obj.save()
            return Response('OTP verified successfully.')
        else:
            return Response('Incorrect OTP.', status=400)
    else:
        return Response('OTP expired.', status=400)






logger = logging.getLogger(__name__)
class ChangePasswordView(APIView): #todo TRUE
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        new_password = request.data.get('new_password')
        logger.info(f"Attempting to change password for user: {request.user.username}")

        if not new_password:
            return Response({'error': 'New password is required.'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.password = make_password(new_password)
        request.user.save()

        return Response({'message': 'Password changed successfully.'}, status=status.HTTP_200_OK)


@api_view(['POST']) #todo true API
def newpassword(request):
    phone = request.data.get('phone')
    password1 = request.data.get('password1')
    password2 = request.data.get('password2')

    # Attempt to find the user by phone number
    user = User.objects.filter(phone=phone).first()
    if not user:
        return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Check password length
    if len(password1) < 8:
        return Response({'error': 'Password length must be at least 8 characters!'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if passwords match
    if password1 != password2:
        return Response({'error': 'Passwords do not match!'}, status=status.HTTP_400_BAD_REQUEST)

    # Set the new password
    user.password = make_password(password1)
    user.save()

    # Log the user out from all sessions by deleting their token
    Token.objects.filter(user=user).delete()

    # Return a success message
    return Response({'message': 'Password updated successfully.'}, status=status.HTTP_200_OK)





# @api_view(['GET'])
# def order_list(request):
#     orders = Order.objects.all().order_by('-created_at')
#     serializer = OrderDetailSerializer(orders, many=True)
#     return Response({"data": serializer.data})

def _parse_query_day(raw):
    text = str(raw or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
        if timezone.is_aware(parsed):
            parsed = timezone.localtime(parsed)
        return parsed.date()
    except ValueError:
        return None


def _month_bounds(raw):
    today = timezone.localdate()
    try:
        year_text, month_text = str(raw or '').split('-')[:2]
        year, month = int(year_text), int(month_text)
        start = datetime.date(year, month, 1)
    except (TypeError, ValueError):
        start = today.replace(day=1)
    if start.month == 12:
        end = datetime.date(start.year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end = datetime.date(start.year, start.month + 1, 1) - datetime.timedelta(days=1)
    return start, end


def _calendar_product_title(product):
    try:
        return product.product_option.product.title or ''
    except Exception:
        return ''


def _calendar_user_name(product):
    order = product.order
    name = (getattr(order, 'delivery_contact_name', '') or '').strip()
    if name:
        return name
    user = getattr(order, 'user', None)
    if user is None:
        return ''
    return (getattr(user, 'fullname', '') or getattr(user, 'name', '') or '').strip()


def _calendar_delivery_label(order):
    kind = getattr(order, 'delivery_type', '') or ''
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


def _delivery_calendar_counts(queryset, month_raw):
    start, end = _month_bounds(month_raw)
    month_qs = queryset.filter(
        Q(order__delivery_date__gte=start, order__delivery_date__lte=end)
        | Q(order__delivery_date__isnull=True, created_at__date__gte=start, created_at__date__lte=end)
    ).select_related('order__user', 'product_option__product')
    counts = {}
    days = {}
    for product in month_qs:
        day = getattr(product.order, 'delivery_date', None)
        if day is None:
            created = product.created_at
            if timezone.is_aware(created):
                created = timezone.localtime(created)
            day = created.date()
        if start <= day <= end:
            key = day.isoformat()
            counts[key] = counts.get(key, 0) + 1
            option = ''
            try:
                option = product.product_option.option or ''
            except Exception:
                option = ''
            days.setdefault(key, []).append({
                'id': str(product.id),
                'product_title': _calendar_product_title(product),
                'product_option': option,
                'user_name': _calendar_user_name(product),
                'status': product.status or '',
                'delivery_slot': getattr(product.order, 'delivery_slot', '') or '',
                'delivery_label': _calendar_delivery_label(product.order),
            })
    return counts, days


@api_view(['GET'])
@authentication_classes([DeliveryTokenAuthentication])
@permission_classes([IsDeliveryAuthenticated])
def ordered_product_list(request):
    """
    API endpoint for paginated ordered products list
    Supports: page, page_size, status, search, from_date, to_date parameters
    """
    try:
        # Get pagination parameters
        page = request.GET.get('page', 1)
        page_size = request.GET.get('page_size', 15)  # Default to 15 per page

        # Convert to integers with validation
        try:
            page = int(page)
            page_size = int(page_size)
        except (ValueError, TypeError):
            return Response({
                'error': 'Invalid page or page_size parameter. Must be integers.',
                'data': [],
                'total_count': 0,
                'current_page': 1,
                'total_pages': 1,
                'has_next': False,
                'has_previous': False
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate page_size limits (prevent abuse)
        if page_size < 1:
            page_size = 15
        elif page_size > 100:  # Maximum 100 items per page
            page_size = 100

        if page < 1:
            page = 1

        # Base queryset - FIXED: removed related_products prefetch
        queryset = OrderedProduct.objects.select_related(
            'order__user',
            'order__user_address',
            'product_option__product__vendor',
        ).all().order_by('-created_at')

        # Apply filters
        # Status filter
        status_filter = request.GET.get('status')
        if status_filter:
            queryset = queryset.filter(status__icontains=status_filter)

        # Search filter (search in product title, user name, etc.)
        search_query = request.GET.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(product_title__icontains=search_query) |
                Q(order__user__fullname__icontains=search_query) |
                Q(order__user__email__icontains=search_query) |
                Q(order__user__phone__icontains=search_query)
            )

        # Calendar dots use the list before a single-day filter.
        calendar_counts, calendar_days = _delivery_calendar_counts(queryset, request.GET.get('month'))

        # Date range filters: scheduled day when set, otherwise order created day.
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        from_day = _parse_query_day(from_date)
        to_day = _parse_query_day(to_date)
        if from_day or to_day:
            day_q = Q()
            if from_day and to_day:
                day_q = (
                    Q(order__delivery_date__gte=from_day, order__delivery_date__lte=to_day)
                    | Q(
                        order__delivery_date__isnull=True,
                        created_at__date__gte=from_day,
                        created_at__date__lte=to_day,
                    )
                )
            elif from_day:
                day_q = (
                    Q(order__delivery_date__gte=from_day)
                    | Q(order__delivery_date__isnull=True, created_at__date__gte=from_day)
                )
            else:
                day_q = (
                    Q(order__delivery_date__lte=to_day)
                    | Q(order__delivery_date__isnull=True, created_at__date__lte=to_day)
                )
            queryset = queryset.filter(day_q)

        # Get total count before pagination
        total_count = queryset.count()

        # Calculate total pages
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

        # Apply pagination
        paginator = Paginator(queryset, page_size)

        try:
            paginated_orders = paginator.page(page)
        except PageNotAnInteger:
            # If page is not an integer, deliver first page
            paginated_orders = paginator.page(1)
            page = 1
        except EmptyPage:
            # If page is out of range, deliver last page
            page = paginator.num_pages
            paginated_orders = paginator.page(page)

        # Serialize the data
        serializer = ItemOrderSerializer(
            paginated_orders.object_list,
            many=True,
            context={'request': request}
        )

        # Prepare response with pagination metadata
        response_data = {
            'data': serializer.data,
            'total_count': total_count,
            'current_page': page,
            'total_pages': total_pages,
            'page_size': page_size,
            'has_next': paginated_orders.has_next(),
            'has_previous': paginated_orders.has_previous(),
            'next_page': page + 1 if paginated_orders.has_next() else None,
            'previous_page': page - 1 if paginated_orders.has_previous() else None,
            'count_on_page': len(paginated_orders.object_list),
            'calendar': calendar_counts,
            'calendar_days': calendar_days,
        }

        # Add debug info (remove in production)
        if request.GET.get('debug'):
            response_data['debug'] = {
                'requested_page': request.GET.get('page', 1),
                'requested_page_size': request.GET.get('page_size', 15),
                'applied_filters': {
                    'status': status_filter,
                    'search': search_query,
                    'from_date': str(from_date) if from_date else None,
                    'to_date': str(to_date) if to_date else None,
                },
                'queryset_count_before_pagination': total_count,
                'model_fields': [field.name for field in OrderedProduct._meta.fields],
            }

        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        # Log the error in production
        print(f"Error in ordered_product_list: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

        return Response({
            'error': 'An error occurred while fetching orders.',
            'data': [],
            'total_count': 0,
            'current_page': 1,
            'total_pages': 1,
            'has_next': False,
            'has_previous': False
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Alternative minimal version if you're still getting errors
@api_view(['GET'])
def ordered_product_list_minimal(request):
    """
    Minimal version for testing - gradually add features once this works
    """
    try:
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 15))

        # Validate
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 15

        # Simple queryset - just get the orders
        queryset = OrderedProduct.objects.select_related(
            'order',
            'order__user',
            'order__user_address',
            'product_option',
            'product_option__product',
        ).order_by('-created_at')

        # Get total count
        total_count = queryset.count()

        # Calculate pagination
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
        start = (page - 1) * page_size
        end = start + page_size

        # Get the slice of data
        orders = queryset[start:end]

        # Serialize
        serializer = ItemOrderSerializer(orders, many=True, context={'request': request})

        # Response
        return Response({
            'data': serializer.data,
            'total_count': total_count,
            'current_page': page,
            'total_pages': total_pages,
            'page_size': page_size,
            'has_next': page < total_pages,
            'has_previous': page > 1,
            'count_on_page': len(orders),
        })

    except Exception as e:
        print(f"Error in minimal ordered_product_list: {str(e)}")
        return Response({
            'error': str(e),
            'data': [],
            'total_count': 0,
            'current_page': 1,
            'total_pages': 1,
            'has_next': False,
            'has_previous': False
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['POST'])
@authentication_classes([DeliveryTokenAuthentication])
@permission_classes([IsDeliveryAuthenticated])
def update_order_status(request):
    ordered_product_id = request.data.get('id')
    new_status = request.data.get('status')

    if not ordered_product_id or not new_status:
        return Response({
            'success': False,
            'error': 'Missing parameters',
            'message': 'Both id and status are required'
        }, status=http_status.HTTP_400_BAD_REQUEST)

    # Validate status
    valid_statuses = ['ORDERED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'CANCELLED']
    if new_status not in valid_statuses:
        return Response({
            'success': False,
            'error': 'Invalid status',
            'message': f'Status must be one of: {", ".join(valid_statuses)}'
        }, status=http_status.HTTP_400_BAD_REQUEST)

    try:
        ordered_product = OrderedProduct.objects.select_related('order').get(id=ordered_product_id)
        old_status = ordered_product.status
        ordered_product.status = new_status
        ordered_product.save()
        from backend.vendor_orders_views import assign_delivery_handler
        assign_delivery_handler(ordered_product.order, request.user)

        notify_order_status_change(ordered_product, new_status, old_status=old_status)

        serializer = OrderItemSerializer(ordered_product, context={'request': request})

        return Response({
            'success': True,
            'message': f'Status updated successfully from {old_status} to {new_status}',
            'product': serializer.data
        }, status=http_status.HTTP_200_OK)

    except OrderedProduct.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Ordered product not found',
            'message': f'No ordered product found with id: {ordered_product_id}'
        }, status=http_status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error updating order status: {str(e)}")
        return Response({
            'success': False,
            'error': 'Internal server error',
            'message': 'An error occurred while updating the order status'
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticatedUser])
def delete_account(request):
    """
    Deletes the authenticated user's account.
    """
    user = request.user
    try:
        user.delete()
        return Response("Account deleted successfully")
    except Exception as e:
        return Response({"error": str(e)}, status=500)


def fast2sms_verification(request):
    return render(request, "fast2sms_verification.html")



@api_view(['GET'])
def get_phone_number(request):
    contact = ContactInfo.objects.first()
    number = contact.phone_number.strip() if contact and contact.phone_number else '9999999999'
    return Response({'phone_number': number})


def _signed_in_vendor(request):
    from backend.vendor_auth_views import _vendor_from_request
    return _vendor_from_request(request)


def _vendor_required(request):
    vendor = _signed_in_vendor(request)
    if vendor is None:
        return None, JsonResponse({'error': 'Sign in again.'}, status=401)
    return vendor, None


def _owned_product(request, product_id):
    vendor, error = _vendor_required(request)
    if error is not None:
        return None, error
    try:
        product = Product.objects.get(id=product_id, vendor=vendor)
    except Product.DoesNotExist:
        return None, JsonResponse({'error': 'Product not found'}, status=404)
    return product, None


@api_view(['GET'])
def all_products(request):
    """
    Full catalog when called without limit.
    With limit and offset, return one page. q searches the whole catalog.
    stock=out_of_stock keeps products whose every option quantity is 0.
    A signed-in vendor sees only that shop's products.
    """
    products = Product.objects.select_related('category').prefetch_related(
        'options_set__images_set',
    ).order_by('-created_at')
    vendor = _signed_in_vendor(request)
    if vendor is not None:
        products = products.filter(vendor=vendor)
    query = (request.GET.get('q') or '').strip()
    if query:
        products = products.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(barcode__icontains=query) |
            Q(options_set__option__icontains=query)
        ).distinct()

    if (request.GET.get('stock') or '').strip() == 'out_of_stock':
        products = products.annotate(
            option_count=Count('options_set', distinct=True),
            in_stock_count=Count(
                'options_set',
                filter=Q(options_set__quantity__gt=0),
                distinct=True,
            ),
        ).filter(option_count__gt=0, in_stock_count=0)

    limit_raw = request.GET.get('limit')
    if limit_raw is None:
        data = ProductSerializer(products, many=True, context={'request': request}).data
        return Response(data)

    try:
        limit = min(max(int(limit_raw), 1), 100)
        offset = max(int(request.GET.get('offset') or 0), 0)
    except (TypeError, ValueError):
        return Response({'error': 'limit and offset must be whole numbers.'}, status=400)

    total = products.count()
    page = products[offset:offset + limit]
    return Response({
        'count': total,
        'offset': offset,
        'limit': limit,
        'results': ProductSerializer(page, many=True, context={'request': request}).data,
    })


@api_view(['GET'])
def vendor_catalog_summary(request):
    vendor = _signed_in_vendor(request)
    if vendor is None:
        return Response({'error': 'Sign in again.'}, status=401)

    products = Product.objects.filter(vendor=vendor)
    annotated = products.annotate(
        option_count=Count('options_set', distinct=True),
        in_stock_count=Count(
            'options_set',
            filter=Q(options_set__quantity__gt=0),
            distinct=True,
        ),
        low_option_count=Count(
            'options_set',
            filter=Q(options_set__quantity__gt=0, options_set__quantity__lte=5),
            distinct=True,
        ),
    )
    subcategory_names = set()
    for chips, legacy in products.values_list('subcategories', 'subcategory'):
        items = chips if isinstance(chips, list) else []
        if not items and legacy:
            items = [part.strip() for part in str(legacy).split(',')]
        for name in items:
            cleaned = str(name or '').strip()
            if cleaned:
                subcategory_names.add(cleaned.casefold())

    latest = products.select_related('category').prefetch_related(
        'options_set__images_set',
    ).order_by('-created_at')[:6]
    return Response({
        'total': products.count(),
        'in_stock': annotated.filter(in_stock_count__gt=0, low_option_count=0).count(),
        'low_stock': annotated.filter(in_stock_count__gt=0, low_option_count__gt=0).count(),
        'out_of_stock': annotated.filter(option_count__gt=0, in_stock_count=0).count(),
        'unclassified': annotated.filter(option_count=0).count(),
        'categories': Category.objects.count(),
        'subcategories': len(subcategory_names),
        'latest': ProductSerializer(latest, many=True, context={'request': request}).data,
    })


@api_view(['PUT'])
@csrf_exempt
def update_product(request, product_id):
    """
    Update product details
    URL: /api/products/<product_id>/update/
    """
    try:
        product, error = _owned_product(request, product_id)
        if error is not None:
            return error

        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        product.title = data.get('title', product.title)
        product.description = data.get('description', product.description)
        if 'price' in data:
            product.price = parse_price(data['price'])
        if 'offer_price' in data:
            product.offer_price = parse_price(data['offer_price'])
        if 'delivery_charge' in data:
            product.delivery_charge = parse_price(data['delivery_charge'])
        product.cod = data.get('cod', product.cod)
        _apply_product_category_and_subcategory(product, data)
        if 'barcode' in data:
            product.barcode = normalize_barcode(data.get('barcode'))

        product.save()

        serializer = ProductSerializer(product, context={'request': request})
        return JsonResponse(serializer.data)

    except Category.DoesNotExist:
        return JsonResponse({'error': 'Category not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['PUT'])
@csrf_exempt
def update_product_option(request, option_id):
    """
    Update product option details
    URL: /api/product-options/<option_id>/update/
    """
    try:
        vendor, error = _vendor_required(request)
        if error is not None:
            return error
        option = ProductOption.objects.select_related('product').get(id=option_id, product__vendor=vendor)

        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        # Update option fields
        option.option = data.get('option', option.option)
        option.quantity = data.get('quantity', option.quantity)
        if 'price' in data:
            option.price = parse_price(data['price'])
        if 'offer_price' in data:
            option.offer_price = parse_price(data['offer_price'])

        option.save()

        # Return updated option
        serializer = ProductOptionSerializer(option, context={'request': request})
        return JsonResponse(serializer.data)

    except ProductOption.DoesNotExist:
        return JsonResponse({'error': 'Product option not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['POST'])
@csrf_exempt
def upload_product_image(request):
    """
    Upload new product image
    URL: /api/product-images/upload/
    """
    try:
        option_id = request.POST.get('product_option')
        position = int(request.POST.get('position', 0))
        image_file = request.FILES.get('image')

        if not image_file:
            return JsonResponse({'error': 'No image file provided'}, status=400)

        if not option_id:
            return JsonResponse({'error': 'Product option ID is required'}, status=400)

        vendor, error = _vendor_required(request)
        if error is not None:
            return error
        try:
            option = ProductOption.objects.select_related('product').get(id=option_id, product__vendor=vendor)
        except ProductOption.DoesNotExist:
            return JsonResponse({'error': 'Product option not found'}, status=404)

        # Create new product image
        product_image = ProductImage.objects.create(
            product_option=option,
            image=image_file,
            position=position
        )

        # Return image information
        return JsonResponse({
            'id': product_image.id,
            'image': request.build_absolute_uri(product_image.image.url),
            'position': product_image.position,
            'product_option': str(option.id)
        }, status=201)

    except ValueError as e:
        return JsonResponse({'error': f'Invalid position value: {e}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['DELETE'])
@csrf_exempt
def delete_product_image(request, image_id):
    """
    Delete product image
    URL: /api/product-images/<image_id>/delete/
    """
    try:
        vendor, error = _vendor_required(request)
        if error is not None:
            return error
        # Try to find image by ID (if you have proper image IDs)
        try:
            image = ProductImage.objects.select_related('product_option__product').get(
                id=image_id,
                product_option__product__vendor=vendor,
            )
        except (ProductImage.DoesNotExist, ValueError):
            # If direct ID doesn't work, try to parse the composite ID
            # Format: image_{option_id}_{index}
            if image_id.startswith('image_'):
                parts = image_id.split('_')
                if len(parts) >= 3:
                    option_id = parts[1]
                    index = int(parts[2])

                    option = ProductOption.objects.select_related('product').get(id=option_id, product__vendor=vendor)
                    images = option.images_set.all().order_by('position')

                    if index < len(images):
                        image = images[index]
                    else:
                        return JsonResponse({'error': 'Image index out of range'}, status=404)
                else:
                    return JsonResponse({'error': 'Invalid image ID format'}, status=400)
            else:
                return JsonResponse({'error': 'Image not found'}, status=404)

        # Delete the image file from storage
        if image.image:
            try:
                image.image.delete(save=False)
            except:
                pass  # Continue even if file deletion fails

        # Delete the database record
        image.delete()

        return JsonResponse({'message': 'Image deleted successfully'}, status=200)

    except ProductOption.DoesNotExist:
        return JsonResponse({'error': 'Product option not found'}, status=404)
    except ValueError as e:
        return JsonResponse({'error': f'Invalid image ID: {e}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['GET'])
def get_product_details(request, product_id):
    """
    Get detailed product information
    URL: /api/products/<product_id>/
    """
    try:
        product, error = _owned_product(request, product_id)
        if error is not None:
            return error
        serializer = ProductSerializer(product, context={'request': request})
        return JsonResponse(serializer.data)

    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['POST'])
@csrf_exempt
def create_product(request):
    """
    Create a new product
    URL: /api/products/create/
    """
    try:
        vendor, error = _vendor_required(request)
        if error is not None:
            return error
        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        # Get category
        from backend.models import Category
        category = Category.objects.get(id=data.get('category'))
        names = _subcategory_names_from_request(data) or []

        product = Product.objects.create(
            vendor=vendor,
            category=category,
            subcategory=', '.join(names),
            subcategories=names,
            barcode=normalize_barcode(data.get('barcode', '')),
            title=data.get('title'),
            description=data.get('description', ''),
            price=data.get('price'),
            offer_price=data.get('offer_price'),
            delivery_charge=data.get('delivery_charge', 0),
            cod=data.get('cod', False)
        )

        serializer = ProductSerializer(product, context={'request': request})
        return JsonResponse(serializer.data, status=201)

    except Category.DoesNotExist:
        return JsonResponse({'error': 'Category not found'}, status=404)
    except KeyError as e:
        return JsonResponse({'error': f'Missing required field: {e}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['DELETE'])
@csrf_exempt
def delete_product(request, product_id):
    """
    Delete a product
    URL: /api/products/<product_id>/delete/
    """
    try:
        product, error = _owned_product(request, product_id)
        if error is not None:
            return error

        # Delete associated images
        for option in product.options_set.all():
            for image in option.images_set.all():
                if image.image:
                    try:
                        image.image.delete(save=False)
                    except:
                        pass

        # Delete the product (cascade will handle related objects)
        product.delete()

        return JsonResponse({'message': 'Product deleted successfully'}, status=200)

    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

################ new APis for ClickwellXvijayshree app

@api_view(['POST'])
@csrf_exempt
def create_product_option(request):
    """
    Create a new product option
    URL: /api/product-options/create/
    """
    try:
        vendor, error = _vendor_required(request)
        if error is not None:
            return error
        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        product = Product.objects.get(id=data.get('product'), vendor=vendor)

        # Create product option
        product_option = ProductOption.objects.create(
            product=product,
            option=data.get('option'),
            quantity=data.get('quantity', 0),
            price=parse_price(data.get('price', 0)),
            offer_price=parse_price(data.get('offer_price', 0)),
        )

        serializer = ProductOptionSerializer(product_option, context={'request': request})
        return JsonResponse(serializer.data, status=201)

    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except KeyError as e:
        return JsonResponse({'error': f'Missing required field: {e}'}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['GET'])
def get_categories(request):
    """
    Get all categories
    URL: /api/categories/
    """
    try:
        categories = Category.objects.all().order_by('position')
        data = CategorySerializer(categories, many=True).data
        return Response(data)
    except Exception as e:
        return Response({'error': str(e)}, status=500)


def _category_payload(request, category):
    data = CategorySerializer(category, context={'request': request}).data
    data['product_count'] = category.products_set.count()
    return data


@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_categories(request):
    vendor, error = _vendor_required(request)
    if error is not None:
        return error
    if request.method == 'GET':
        rows = Category.objects.all().order_by('position', 'id')
        return Response([_category_payload(request, category) for category in rows])

    name = str(request.data.get('name') or '').strip()
    if not name:
        return Response({'error': 'Enter a category name.'}, status=400)
    if len(name) > 50:
        return Response({'error': 'Use a shorter category name.'}, status=400)
    if Category.objects.filter(name__iexact=name).exists():
        return Response({'error': 'That category already exists.'}, status=400)
    last = Category.objects.order_by('-position', '-id').first()
    category = Category(name=name, position=(last.position + 1) if last else 0)
    image = request.FILES.get('image')
    if image:
        category.image = image
    category.save()
    return Response(_category_payload(request, category), status=201)


@api_view(['DELETE'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_category_detail(request, category_id):
    vendor, error = _vendor_required(request)
    if error is not None:
        return error
    category = Category.objects.filter(id=category_id).first()
    if category is None:
        return Response({'error': 'Category not found.'}, status=404)
    if category.products_set.exists() or category.slides_set.exists() or category.pageitems_set.exists():
        return Response(
            {'error': 'This category still has products or store home items. Move them before deleting.'},
            status=400,
        )
    category.delete()
    return Response({'ok': True})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_category_order(request):
    """Save the shop-home category order. ids is every category, first to last."""
    vendor, error = _vendor_required(request)
    if error is not None:
        return error
    raw = request.data.get('ids')
    if not isinstance(raw, list) or not raw:
        return Response({'error': 'Send the categories in order.'}, status=400)
    ids = []
    for value in raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            return Response({'error': 'Send the categories in order.'}, status=400)
    known = {category.id: category for category in Category.objects.filter(id__in=ids)}
    if len(known) != len(set(ids)) or Category.objects.exclude(id__in=ids).exists():
        return Response({'error': 'Include every category.'}, status=400)
    for index, category_id in enumerate(ids):
        category = known[category_id]
        if category.position != index:
            category.position = index
            category.save(update_fields=['position'])
    rows = Category.objects.all().order_by('position', 'id')
    return Response([_category_payload(request, category) for category in rows])


def _subcategory_names_from_request(data):
    """Return resolved chips when the client sent them, otherwise None."""
    if 'subcategories' in data:
        return resolve_subcategory_names(data.get('subcategories'))
    if 'subcategory' in data:
        return resolve_subcategory_names(data.get('subcategory'))
    return None


def _apply_subcategory_names(product, names):
    product.subcategories = names
    product.subcategory = ', '.join(names)


def _apply_product_category_and_subcategory(product, data):
    """Update category and subcategory chips only when the client sends those keys."""
    if data.get('category'):
        product.category = Category.objects.get(id=data.get('category'))
    names = _subcategory_names_from_request(data)
    if names is not None:
        _apply_subcategory_names(product, names)


@api_view(['GET'])
def subcategory_suggestions(request):
    """
    Distinct subcategory chips already saved on products.
    Prefix match: q=B returns Biscuit and every other saved name that starts with B.
    """
    query = (request.GET.get('q') or '').strip().casefold()
    vendor = _signed_in_vendor(request)
    results = [
        name
        for key, name in known_subcategory_spellings(vendor.id if vendor is not None else None).items()
        if not query or key.startswith(query)
    ]
    results.sort(key=str.casefold)
    return Response(results)


@api_view(['GET'])
def category_products(request):
    """
    Paginated product options for a category (Blinkit-style category listing).
    URL: /api/category_products/?category=<id>&limit=20
    """
    category_id = request.GET.get('category')
    if not category_id:
        return Response({'error': 'category parameter is required'}, status=400)

    pagination = LimitOffsetPagination()
    queryset = (
        ProductOption.objects.filter(product__category_id=category_id)
        .select_related('product')
        .prefetch_related('images_set')
        .order_by('product__title', 'option')
    )
    if request.GET.get('vendor'):
        queryset = queryset.filter(product__vendor_id=request.GET.get('vendor'))
    page = pagination.paginate_queryset(queryset, request)
    data = [_serialize_option_for_catalog(opt) for opt in page]
    return pagination.get_paginated_response(data)


# Updated create_product function with better error handling
@api_view(['POST'])
@csrf_exempt
def create_product_enhanced(request):
    """
    Create a new product with enhanced error handling
    URL: /api/products/create/
    """
    try:
        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        # Validate required fields
        required_fields = ['title', 'price', 'offer_price', 'category']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Missing required field: {field}'}, status=400)

        # Get category
        try:
            category = Category.objects.get(id=data.get('category'))
        except Category.DoesNotExist:
            return JsonResponse({'error': 'Category not found'}, status=404)

        try:
            price = parse_price(data.get('price'))
            offer_price = parse_price(data.get('offer_price'))
            delivery_charge = parse_price(data.get('delivery_charge', 0))
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)

        names = _subcategory_names_from_request(data) or []
        product = Product.objects.create(
            category=category,
            subcategory=', '.join(names),
            subcategories=names,
            barcode=normalize_barcode(data.get('barcode', '')),
            title=data.get('title'),
            description=data.get('description', ''),
            price=price,
            offer_price=offer_price,
            delivery_charge=delivery_charge,
            cod=data.get('cod', False)
        )

        serializer = ProductSerializer(product, context={'request': request})
        return JsonResponse(serializer.data, status=201)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Updated product endpoints with better validation
@api_view(['PUT'])
@csrf_exempt
def update_product_enhanced(request, product_id):
    """
    Update product details with enhanced validation
    URL: /api/products/<product_id>/update/
    """
    try:
        product = Product.objects.get(id=product_id)

        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        product.title = data.get('title', product.title)
        product.description = data.get('description', product.description)
        if 'price' in data:
            product.price = parse_price(data['price'])
        if 'offer_price' in data:
            product.offer_price = parse_price(data['offer_price'])
        if 'delivery_charge' in data:
            product.delivery_charge = parse_price(data['delivery_charge'])
        product.cod = data.get('cod', product.cod)
        _apply_product_category_and_subcategory(product, data)
        if 'barcode' in data:
            product.barcode = normalize_barcode(data.get('barcode'))

        product.save()

        serializer = ProductSerializer(product, context={'request': request})
        return JsonResponse(serializer.data)

    except Category.DoesNotExist:
        return JsonResponse({'error': 'Category not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['PUT'])
@csrf_exempt
def update_product_option_enhanced(request, option_id):
    """
    Update product option details with enhanced validation
    URL: /api/product-options/<option_id>/update/
    """
    try:
        option = ProductOption.objects.get(id=option_id)

        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        # Validate quantity if provided
        if 'quantity' in data:
            try:
                quantity = int(data['quantity'])
                if quantity < 0:
                    return JsonResponse({'error': 'Quantity must be non-negative'}, status=400)
            except (ValueError, TypeError):
                return JsonResponse({'error': 'Quantity must be a valid number'}, status=400)

        # Update option fields
        option.option = data.get('option', option.option)
        option.quantity = data.get('quantity', option.quantity)
        if 'price' in data:
            option.price = parse_price(data['price'])
        if 'offer_price' in data:
            option.offer_price = parse_price(data['offer_price'])

        option.save()

        # Return updated option
        serializer = ProductOptionSerializer(option, context={'request': request})
        return JsonResponse(serializer.data)

    except ProductOption.DoesNotExist:
        return JsonResponse({'error': 'Product option not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['POST'])
@csrf_exempt
def upload_product_image_enhanced(request):
    """
    Upload new product image with enhanced validation
    URL: /api/product-images/upload/
    """
    try:
        option_id = request.POST.get('product_option')
        position = request.POST.get('position', 0)
        image_file = request.FILES.get('image')

        if not image_file:
            return JsonResponse({'error': 'No image file provided'}, status=400)

        if not option_id:
            return JsonResponse({'error': 'Product option ID is required'}, status=400)

        # Validate position
        try:
            position = int(position)
            if position < 0:
                return JsonResponse({'error': 'Position must be non-negative'}, status=400)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Position must be a valid number'}, status=400)

        # Get the product option
        try:
            option = ProductOption.objects.get(id=option_id)
        except ProductOption.DoesNotExist:
            return JsonResponse({'error': 'Product option not found'}, status=404)

        # Validate image file
        if image_file.size > 5 * 1024 * 1024:  # 5MB limit
            return JsonResponse({'error': 'Image file too large (max 5MB)'}, status=400)

        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
        if image_file.content_type not in allowed_types:
            return JsonResponse({'error': 'Invalid image format. Allowed: JPEG, PNG, WebP'}, status=400)

        # Create new product image
        product_image = ProductImage.objects.create(
            product_option=option,
            image=image_file,
            position=position
        )

        # Return image information
        return JsonResponse({
            'id': product_image.id,
            'image': request.build_absolute_uri(product_image.image.url),
            'position': product_image.position,
            'product_option': str(option.id)
        }, status=201)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['DELETE'])
@csrf_exempt
def delete_product_image_enhanced(request, image_id):
    """
    Delete product image with enhanced error handling
    URL: /api/product-images/<image_id>/delete/
    """
    try:
        # Try to find image by ID (if you have proper image IDs)
        try:
            image = ProductImage.objects.get(id=image_id)
        except (ProductImage.DoesNotExist, ValueError):
            # If direct ID doesn't work, try to parse the composite ID
            # Format: image_{option_id}_{index}
            if image_id.startswith('image_'):
                parts = image_id.split('_')
                if len(parts) >= 3:
                    option_id = parts[1]
                    index = int(parts[2])

                    try:
                        option = ProductOption.objects.get(id=option_id)
                        images = option.images_set.all().order_by('position')

                        if index < len(images):
                            image = images[index]
                        else:
                            return JsonResponse({'error': 'Image index out of range'}, status=404)
                    except ProductOption.DoesNotExist:
                        return JsonResponse({'error': 'Product option not found'}, status=404)
                    except ValueError:
                        return JsonResponse({'error': 'Invalid image index'}, status=400)
                else:
                    return JsonResponse({'error': 'Invalid image ID format'}, status=400)
            else:
                return JsonResponse({'error': 'Image not found'}, status=404)

        # Delete the image file from storage
        if image.image:
            try:
                image.image.delete(save=False)
            except:
                pass  # Continue even if file deletion fails

        # Delete the database record
        image.delete()

        return JsonResponse({'message': 'Image deleted successfully'}, status=200)

    except ValueError as e:
        return JsonResponse({'error': f'Invalid image ID: {e}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Additional utility function for bulk operations
@api_view(['POST'])
@csrf_exempt
def bulk_update_stock(request):
    """
    Bulk update stock quantities for multiple products
    URL: /api/bulk-update-stock/
    """
    try:
        data = request.data if hasattr(request, 'data') else json.loads(request.body)

        if 'updates' not in data:
            return JsonResponse({'error': 'Updates array is required'}, status=400)

        updated_count = 0
        errors = []

        for update in data['updates']:
            try:
                option_id = update.get('option_id')
                quantity = update.get('quantity')

                if not option_id or quantity is None:
                    errors.append(f"Missing option_id or quantity in update")
                    continue

                option = ProductOption.objects.get(id=option_id)
                option.quantity = int(quantity)
                option.save()
                updated_count += 1

            except ProductOption.DoesNotExist:
                errors.append(f"Product option {option_id} not found")
            except (ValueError, TypeError):
                errors.append(f"Invalid quantity for option {option_id}")
            except Exception as e:
                errors.append(f"Error updating option {option_id}: {str(e)}")

        return JsonResponse({
            'message': f'Successfully updated {updated_count} product options',
            'updated_count': updated_count,
            'errors': errors
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@api_view(['POST'])
@authentication_classes([DeliveryTokenAuthentication])
@permission_classes([IsDeliveryAuthenticated])
def update_all_order_products_status_enhanced(request):
    """
    Enhanced API to update all products in an order to the same status

    Expected payload:
    {
        "product_id": "uuid-of-any-product-in-order",
        "status": "DELIVERED",
        "update_mode": "all" // "all", "others", or "selective"
    }
    """
    product_id = request.data.get('product_id')
    new_status = request.data.get('status')
    update_mode = request.data.get('update_mode', 'all')

    # Validate required parameters
    if not product_id or not new_status:
        return Response({
            'error': 'Both product_id and status are required',
            'valid_statuses': ['ORDERED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'CANCELLED']
        }, status=http_status.HTTP_400_BAD_REQUEST)

    # Validate status value
    valid_statuses = ['ORDERED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'CANCELLED']
    if new_status not in valid_statuses:
        return Response({
            'error': 'Invalid status',
            'valid_statuses': valid_statuses
        }, status=http_status.HTTP_400_BAD_REQUEST)

    try:
        # Find the reference product to get its order
        reference_product = OrderedProduct.objects.get(id=product_id)
        order_id = reference_product.order.id

        # Get all products in the same order based on update mode
        if update_mode == 'all':
            # Update ALL products in the order
            products_to_update = OrderedProduct.objects.filter(order__id=order_id)
        elif update_mode == 'others':
            # Update all OTHER products (excluding the reference product)
            products_to_update = OrderedProduct.objects.filter(
                order__id=order_id
            ).exclude(id=product_id)
        else:
            return Response({
                'error': 'Invalid update_mode. Must be "all" or "others"'
            }, status=http_status.HTTP_400_BAD_REQUEST)

        if not products_to_update.exists():
            return Response({
                'message': 'No products found to update',
                'order_id': str(order_id)
            }, status=http_status.HTTP_200_OK)

        products_list = list(
            products_to_update.select_related('product_option', 'order', 'order__user')
        )
        changed_count = sum(1 for product in products_list if product.status != new_status)

        # Use transaction to ensure all updates succeed or fail together
        with transaction.atomic():
            from backend.vendor_orders_views import handler_update_kwargs
            update_fields = {'status': new_status}
            update_fields.update(handler_update_kwargs(request.user))
            updated_count = products_to_update.update(**update_fields)

            # Get all products in the order for response
            all_order_products = OrderedProduct.objects.filter(order__id=order_id)

            if changed_count > 0:
                if changed_count == 1:
                    changed_product = next(
                        product for product in products_list if product.status != new_status
                    )
                    notify_order_status_change(
                        changed_product,
                        new_status,
                        old_status=changed_product.status,
                    )
                else:
                    notify_order_bulk_status_change(
                        reference_product.order,
                        new_status,
                        reference_product=reference_product,
                        item_count=changed_count,
                    )

            # Log the bulk update
            logger.info(f"Bulk status update: Order {order_id}, {updated_count} products updated to {new_status}")

            # Serialize all products in the order
            serializer = ItemOrderSerializer(all_order_products, many=True, context={'request': request})

            return Response({
                'success': True,
                'message': f'Successfully updated {updated_count} products to {new_status}',
                'order_id': str(order_id),
                'reference_product_id': str(product_id),
                'updated_count': updated_count,
                'new_status': new_status,
                'update_mode': update_mode,
                'all_order_products': serializer.data
            }, status=http_status.HTTP_200_OK)

    except OrderedProduct.DoesNotExist:
        return Response({
            'error': 'Product not found'
        }, status=http_status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error in bulk status update: {str(e)}")
        return Response({
            'error': 'An error occurred while updating order status',
            'details': str(e)
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([DeliveryTokenAuthentication])
@permission_classes([IsDeliveryAuthenticated])
def update_order_with_confirmation(request):
    """
    API that handles order status updates with confirmation for bulk actions

    Expected payload:
    {
        "product_id": "uuid",
        "status": "DELIVERED",
        "apply_to_all": true,  // If true, applies to all products in order
        "confirmed": false     // Set to true if user confirmed bulk action
    }
    """
    product_id = request.data.get('product_id')
    new_status = request.data.get('status')
    apply_to_all = request.data.get('apply_to_all', False)
    confirmed = request.data.get('confirmed', False)

    if not product_id or not new_status:
        return Response({
            'error': 'Both product_id and status are required'
        }, status=http_status.HTTP_400_BAD_REQUEST)

    try:
        # Find the reference product
        reference_product = OrderedProduct.objects.get(id=product_id)
        order_id = reference_product.order.id

        # Get all products in the same order
        all_order_products = OrderedProduct.objects.filter(order__id=order_id)
        total_products = all_order_products.count()

        # If applying to all and there are multiple products, check if confirmation is needed
        if apply_to_all and total_products > 1 and not confirmed:
            # Return confirmation request
            other_products = all_order_products.exclude(id=product_id)
            other_products_data = []

            for product in other_products:
                other_products_data.append({
                    'id': str(product.id),
                    'title': product.product_option.product.title,
                    'option': product.product_option.option,
                    'current_status': product.status,
                    'quantity': product.quantity
                })

            return Response({
                'confirmation_required': True,
                'message': f'This will update {total_products} products in this order to "{new_status}". Do you want to continue?',
                'order_id': str(order_id),
                'total_products': total_products,
                'other_products': other_products_data,
                'new_status': new_status
            }, status=http_status.HTTP_200_OK)

        # Proceed with update
        if apply_to_all:
            products_list = list(
                all_order_products.select_related('product_option', 'order', 'order__user')
            )
            changed_count = sum(
                1 for product in products_list if product.status != new_status
            )

            # Update all products in the order
            with transaction.atomic():
                from backend.vendor_orders_views import handler_update_kwargs
                update_fields = {'status': new_status}
                update_fields.update(handler_update_kwargs(request.user))
                updated_count = all_order_products.update(**update_fields)

                if changed_count > 0:
                    if changed_count == 1:
                        changed_product = next(
                            product for product in products_list
                            if product.status != new_status
                        )
                        notify_order_status_change(
                            changed_product,
                            new_status,
                            old_status=changed_product.status,
                        )
                    else:
                        notify_order_bulk_status_change(
                            reference_product.order,
                            new_status,
                            reference_product=reference_product,
                            item_count=changed_count,
                        )

                # Get updated data
                updated_products = OrderedProduct.objects.filter(order__id=order_id)
                serializer = ItemOrderSerializer(updated_products, many=True, context={'request': request})

                return Response({
                    'success': True,
                    'message': f'Successfully updated all {updated_count} products to {new_status}',
                    'updated_count': updated_count,
                    'products': serializer.data
                }, status=http_status.HTTP_200_OK)
        else:
            # Update only the single product
            old_status = reference_product.status
            reference_product.status = new_status
            reference_product.save()
            from backend.vendor_orders_views import assign_delivery_handler
            assign_delivery_handler(reference_product.order, request.user)

            notify_order_status_change(
                reference_product,
                new_status,
                old_status=old_status,
            )

            serializer = ItemOrderSerializer(reference_product, context={'request': request})

            return Response({
                'success': True,
                'message': f'Successfully updated product status to {new_status}',
                'product': serializer.data
            }, status=http_status.HTTP_200_OK)

    except OrderedProduct.DoesNotExist:
        return Response({
            'error': 'Product not found'
        }, status=http_status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Error updating order status: {str(e)}")
        return Response({
            'error': 'An error occurred while updating order status',
            'details': str(e)
        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)


_TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


def _clock_minutes(value):
    match = _TIME_RE.match(str(value or '').strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _clean_delivery_timing(data):
    try:
        quick_min = int(data.get('quick_min_minutes'))
        quick_max = int(data.get('quick_max_minutes'))
    except (TypeError, ValueError):
        return None, 'Enter whole numbers for the quick delivery minutes.'
    if quick_min < 1 or quick_max > 240 or quick_max <= quick_min:
        return None, 'Quick delivery needs a start minute and a later end minute, up to 240.'

    raw_slots = data.get('slots') or []
    if not isinstance(raw_slots, list):
        return None, 'Compatible timing must be a list of time windows.'

    slots = []
    seen = set()
    for slot in raw_slots:
        if not isinstance(slot, dict):
            return None, 'Each compatible window needs a start and an end.'
        start = str(slot.get('start') or '').strip()
        end = str(slot.get('end') or '').strip()
        start_minutes = _clock_minutes(start)
        end_minutes = _clock_minutes(end)
        if start_minutes is None or end_minutes is None:
            return None, 'Use a start and end time for each compatible window.'
        if end_minutes <= start_minutes:
            return None, 'Each compatible window must end after it starts.'
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        slots.append({'start': start, 'end': end})
        if len(slots) >= 24:
            break

    open_time = _normalize_clock(data.get('open_time'), '09:00')
    close_time = _normalize_clock(data.get('close_time'), '22:00')
    if open_time is None or close_time is None:
        return None, 'Use an opening time and a closing time.'
    if _clock_minutes(close_time) <= _clock_minutes(open_time):
        return None, 'Closing time must be after opening time.'

    raw_days = data.get('closed_days') or []
    if not isinstance(raw_days, list):
        return None, 'Closed days must be a list of weekdays.'
    closed_days = []
    for day in raw_days:
        key = str(day or '').strip().lower()
        if key not in _WEEKDAYS:
            return None, 'Choose a weekday to close the shop.'
        if key not in closed_days:
            closed_days.append(key)
    closed_days.sort(key=_WEEKDAYS.index)

    closed_dates, date_error = _clean_closed_dates(data.get('closed_dates') or [])
    if date_error:
        return None, date_error

    return {
        'quick_enabled': bool(data.get('quick_enabled')),
        'quick_min_minutes': quick_min,
        'quick_max_minutes': quick_max,
        'slots': slots,
        'open_time': open_time,
        'close_time': close_time,
        'closed_days': closed_days,
        'closed_dates': closed_dates,
    }, None


def _clean_closed_dates(raw_dates):
    if not isinstance(raw_dates, list):
        return None, 'Closed dates must be a list of calendar dates.'
    today = datetime.date.today()
    earliest = today - datetime.timedelta(days=366)
    latest = today + datetime.timedelta(days=366 * 3)
    dates = []
    for item in raw_dates:
        text = str(item or '').strip()[:10]
        if not _DATE_RE.match(text):
            return None, 'Choose a calendar date to close the shop.'
        try:
            parsed = datetime.date.fromisoformat(text)
        except ValueError:
            return None, 'Choose a real calendar date.'
        if parsed < earliest or parsed > latest:
            return None, 'Choose a shop closure date within the next few years.'
        if text not in dates:
            dates.append(text)
        if len(dates) >= 366:
            break
    dates.sort()
    return dates, None


def _normalize_clock(value, fallback):
    text = str(value or '').strip()
    if len(text) >= 5:
        text = text[:5]
    if _clock_minutes(text) is None:
        text = fallback
    return text if _clock_minutes(text) is not None else None


def _stored_clock(value, fallback):
    if hasattr(value, 'strftime'):
        return value.strftime('%H:%M')
    text = str(value or '')[:5]
    return text if _clock_minutes(text) is not None else fallback


def _pretty_clock(value):
    text = _stored_clock(value, '09:00')
    hour, minute = [int(part) for part in text.split(':')]
    period = 'AM' if hour < 12 else 'PM'
    hour12 = hour % 12 or 12
    if minute == 0:
        return f'{hour12} {period}'
    return f'{hour12}:{minute:02d} {period}'


_MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
_DAY_LABELS = {
    'monday': 'Monday',
    'tuesday': 'Tuesday',
    'wednesday': 'Wednesday',
    'thursday': 'Thursday',
    'friday': 'Friday',
    'saturday': 'Saturday',
    'sunday': 'Sunday',
}


def _clock_parts(value):
    text = _stored_clock(value, '09:00')
    hour, minute = [int(part) for part in text.split(':')]
    return hour, minute


def _editor_clock(value):
    hour, minute = _clock_parts(value)
    period = 'AM' if hour < 12 else 'PM'
    hour12 = hour % 12 or 12
    return f'{hour12}:{minute:02d} {period}'


def _editor_window(slot):
    if not isinstance(slot, dict):
        return ''
    start = slot.get('start')
    end = slot.get('end')
    if not start or not end:
        return ''
    start_hour, start_minute = _clock_parts(start)
    end_hour, end_minute = _clock_parts(end)
    same_period = (start_hour < 12) == (end_hour < 12)
    if same_period and start_minute == 0 and end_minute == 0:
        period = 'AM' if start_hour < 12 else 'PM'
        return f'{start_hour % 12 or 12}–{end_hour % 12 or 12} {period}'
    return f'{_editor_clock(start)} – {_editor_clock(end)}'


def _slot_label(slot):
    return _editor_window(slot)


def _shop_date_label(value):
    text = str(value or '')[:10]
    if not _DATE_RE.match(text):
        return ''
    year, month, day = text.split('-')
    month_index = int(month) - 1
    if month_index < 0 or month_index > 11:
        return ''
    return f'{int(day)} {_MONTH_NAMES[month_index]} {year}'


def _vendor_closed_sets(vendor):
    closed_dates = vendor.closed_dates if isinstance(vendor.closed_dates, list) else []
    closed_days = vendor.closed_days if isinstance(vendor.closed_days, list) else []
    return (
        {str(day)[:10] for day in closed_dates},
        {str(day).lower() for day in closed_days},
    )


def _next_open_day(vendor, now=None):
    now = timezone.localtime(now or timezone.now())
    closed_dates, closed_days = _vendor_closed_sets(vendor)
    for offset in range(0, 21):
        day = now.date() + datetime.timedelta(days=offset)
        if day.isoformat() in closed_dates:
            continue
        weekday = day.strftime('%A').lower()
        if weekday in closed_days:
            continue
        if offset == 0 and now.time().replace(second=0, microsecond=0) >= vendor.close_time:
            continue
        return day
    return None


def _next_open_label(vendor, now=None):
    day = _next_open_day(vendor, now)
    if day is None:
        return ''
    weekday = day.strftime('%A').lower()
    return f'{_DAY_LABELS.get(weekday, weekday.title())}, {day.day} {_MONTH_NAMES[day.month - 1]}'


def _next_open_date(vendor, now=None):
    day = _next_open_day(vendor, now)
    if day is None:
        return ''
    return day.strftime('%d/%m')


def _vendor_is_open(vendor):
    now = timezone.localtime()
    today = now.date().isoformat()
    weekday = now.strftime('%A').lower()
    closed_dates, closed_days = _vendor_closed_sets(vendor)
    if today in closed_dates:
        return False, 'Closed today'
    if weekday in closed_days:
        return False, 'Closed today'
    current = now.time().replace(second=0, microsecond=0)
    if vendor.open_time <= current < vendor.close_time:
        return True, 'Open now'
    return False, 'Closed'


def _copy_timing(source, cleaned):
    source.quick_enabled = cleaned['quick_enabled']
    source.quick_min_minutes = cleaned['quick_min_minutes']
    source.quick_max_minutes = cleaned['quick_max_minutes']
    source.slots = cleaned['slots']
    source.open_time = datetime.time.fromisoformat(cleaned['open_time'])
    source.close_time = datetime.time.fromisoformat(cleaned['close_time'])
    source.closed_days = cleaned['closed_days']
    source.closed_dates = cleaned['closed_dates']


def _shop_image_url(vendor, request):
    if not vendor.shop_image:
        return ''
    return request.build_absolute_uri(vendor.shop_image.url)


def _store_card(vendor, request):
    is_open, status_label = _vendor_is_open(vendor)
    closed_today = status_label == 'Closed today'
    slots = vendor.slots if isinstance(vendor.slots, list) else []
    windows = [label for label in (_editor_window(slot) for slot in slots) if label]
    closed_days = vendor.closed_days if isinstance(vendor.closed_days, list) else []
    closed_dates = vendor.closed_dates if isinstance(vendor.closed_dates, list) else []
    closed_labels = [
        f'{_DAY_LABELS[day]} · Closed'
        for day in _WEEKDAYS
        if day in closed_days and day in _DAY_LABELS
    ]
    closed_labels.extend(
        f'{label} · Closed'
        for label in (_shop_date_label(day) for day in closed_dates)
        if label
    )
    hours_label = f'{_editor_clock(vendor.open_time)} – {_editor_clock(vendor.close_time)}'
    quick_label = f'{vendor.quick_min_minutes} – {vendor.quick_max_minutes} min'
    if vendor.quick_enabled:
        delivery_label = quick_label
    elif windows:
        delivery_label = ', '.join(windows)
    else:
        delivery_label = hours_label
    return {
        'id': vendor.id,
        'shop_name': vendor.shop_name,
        'owner_name': vendor.owner_name,
        'address': vendor.address,
        'location': vendor.location,
        'city': vendor.city,
        'state': vendor.state,
        'phone': vendor.phone,
        'alternate_phone': vendor.alternate_phone,
        'gstin': vendor.gstin,
        'license_number': vendor.license_number,
        'is_open': is_open,
        'closed_today': closed_today,
        'status_label': status_label,
        'next_open_label': '' if is_open else _next_open_label(vendor),
        'next_open_date': '' if is_open else _next_open_date(vendor),
        'hours_label': hours_label,
        'delivery_label': delivery_label,
        'quick_enabled': vendor.quick_enabled,
        'quick_label': quick_label,
        'windows': windows,
        'closed_days': [day for day in _WEEKDAYS if day in closed_days],
        'closed_dates': sorted(
            str(day)[:10] for day in closed_dates if _DATE_RE.match(str(day)[:10])
        ),
        'closed_labels': closed_labels,
        'has_slots': bool(windows),
        'quick_min_minutes': vendor.quick_min_minutes,
        'quick_max_minutes': vendor.quick_max_minutes,
        'shop_image': _shop_image_url(vendor, request),
        'delivery_pincodes': _pincode_list(vendor.delivery_pincodes),
    }


def _delivery_timing_payload(obj):
    slots = obj.slots if isinstance(obj.slots, list) else []
    closed_days = obj.closed_days if isinstance(obj.closed_days, list) else []
    closed_dates = obj.closed_dates if isinstance(obj.closed_dates, list) else []
    return {
        'quick_enabled': obj.quick_enabled,
        'quick_min_minutes': obj.quick_min_minutes,
        'quick_max_minutes': obj.quick_max_minutes,
        'slots': slots,
        'open_time': _stored_clock(obj.open_time, '09:00'),
        'close_time': _stored_clock(obj.close_time, '22:00'),
        'closed_days': [day for day in _WEEKDAYS if day in closed_days],
        'closed_dates': sorted(str(day)[:10] for day in closed_dates if _DATE_RE.match(str(day)[:10])),
    }


@api_view(['GET', 'PUT'])
@csrf_exempt
def delivery_timing(request):
    """Read or save the store delivery windows used by the catalog editor."""
    from backend.vendor_auth_views import _vendor_from_request

    vendor = _vendor_from_request(request)
    if vendor is not None:
        timing, _created = DeliveryTiming.objects.get_or_create(
            vendor=vendor,
            defaults={
                'quick_enabled': vendor.quick_enabled,
                'quick_min_minutes': vendor.quick_min_minutes,
                'quick_max_minutes': vendor.quick_max_minutes,
                'slots': vendor.slots if isinstance(vendor.slots, list) else [],
                'open_time': vendor.open_time,
                'close_time': vendor.close_time,
                'closed_days': vendor.closed_days if isinstance(vendor.closed_days, list) else [],
                'closed_dates': vendor.closed_dates if isinstance(vendor.closed_dates, list) else [],
            },
        )
        source = vendor
    else:
        timing, _created = DeliveryTiming.objects.get_or_create(pk=1)
        source = timing
    if request.method == 'GET':
        return Response(_delivery_timing_payload(source))

    data = request.data if hasattr(request, 'data') else json.loads(request.body)
    cleaned, error = _clean_delivery_timing(data)
    if error:
        return Response({'error': error}, status=400)

    _copy_timing(timing, cleaned)
    if vendor is not None:
        timing.vendor = vendor
    timing.save()
    if vendor is not None:
        _copy_timing(vendor, cleaned)
        vendor.save()
    return Response(_delivery_timing_payload(vendor or timing))


@api_view(['GET', 'PUT'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_order_rules(request):
    """Minimum order amount and the delivery charge below that amount."""
    vendor, error = _vendor_required(request)
    if error is not None:
        return error
    if request.method == 'GET':
        return Response(_order_rules_payload(vendor))
    minimum = _clean_money(request.data.get('min_order_amount'), 'minimum')
    charge = _clean_money(request.data.get('delivery_charge_under'), 'charge')
    if minimum is None:
        return Response({'error': 'Enter the minimum order amount.'}, status=400)
    if charge is None:
        return Response({'error': 'Enter the delivery charge.'}, status=400)
    vendor.min_order_amount = minimum
    vendor.delivery_charge_under = charge
    vendor.save(update_fields=['min_order_amount', 'delivery_charge_under', 'updated_at'])
    return Response(_order_rules_payload(vendor))


def _pincode_list(raw):
    if not isinstance(raw, list):
        return []
    codes = []
    for item in raw:
        code = str(item).strip()
        if len(code) == 6 and code.isdigit() and code not in codes:
            codes.append(code)
    return codes


def _clean_pincodes(raw):
    if not isinstance(raw, list):
        return None
    return _pincode_list(raw) if all(
        len(str(item).strip()) == 6 and str(item).strip().isdigit() for item in raw
    ) else None


@api_view(['GET', 'PUT'])
@authentication_classes([])
@permission_classes([AllowAny])
def vendor_delivery_pincodes(request):
    """Pincodes this shop delivers to."""
    vendor, error = _vendor_required(request)
    if error is not None:
        return error
    if request.method == 'GET':
        return Response({'delivery_pincodes': _pincode_list(vendor.delivery_pincodes)})
    codes = _clean_pincodes(request.data.get('delivery_pincodes'))
    if codes is None:
        return Response({'error': 'Enter 6-digit pincodes.'}, status=400)
    vendor.delivery_pincodes = codes
    vendor.save(update_fields=['delivery_pincodes', 'updated_at'])
    return Response({'delivery_pincodes': codes})


@api_view(['GET'])
@permission_classes([AllowAny])
def popular_cities(request):
    """Cities the admin marked for the app, with the vendors that serve each one."""
    from backend.models import PopularCity

    rows = PopularCity.objects.filter(is_active=True).prefetch_related('vendors')
    payload = []
    for city in rows:
        payload.append({
            'id': city.id,
            'city': city.city,
            'state': city.state,
            'pincode': city.pincode,
            'latitude': float(city.latitude or 0),
            'longitude': float(city.longitude or 0),
            'vendor_ids': [vendor.id for vendor in city.vendors.all() if vendor.is_active],
        })
    return Response(payload)


@api_view(['GET'])
@permission_classes([AllowAny])
def store_list(request):
    """Public shop cards for the customer app."""
    vendors = Vendor.objects.filter(is_active=True).order_by('shop_name')
    return Response([_store_card(vendor, request) for vendor in vendors])


def _shop_order_rules(vendor):
    if vendor is None:
        return Decimal(FREE_DELIVERY_THRESHOLD), Decimal(DELIVERY_CHARGE_AMOUNT)
    return vendor.min_order_amount, vendor.delivery_charge_under


def _vendor_by_id(raw):
    if raw in (None, ''):
        return None
    try:
        return Vendor.objects.filter(pk=int(raw), is_active=True).first()
    except (TypeError, ValueError):
        return None


def _delivery_charge_for(amount, vendor):
    minimum, charge = _shop_order_rules(vendor)
    total = Decimal(str(amount))
    minimum = Decimal(str(minimum))
    charge = Decimal(str(charge))
    applied = charge if total < minimum else Decimal('0')
    return applied, minimum, charge


def _order_rules_payload(vendor):
    minimum, charge = _shop_order_rules(vendor)
    return {
        'min_order_amount': float(minimum),
        'delivery_charge_under': float(charge),
        'free_delivery_threshold': float(minimum),
        'delivery_charge_amount': float(charge),
    }


def _clean_money(value, label):
    try:
        amount = Decimal(str(value if value not in (None, '') else '')).quantize(Decimal('0.01'))
    except Exception:
        return None
    if amount < 0:
        return None
    return amount


@api_view(['GET'])
@permission_classes([AllowAny])
def app_config(request):
    """Public app configuration for mobile clients."""
    vendor = _vendor_by_id(request.GET.get('vendor'))
    return Response(_order_rules_payload(vendor))




@api_view(['POST'])
def calculate_delivery_charge(request):
    """
    POST payload: { "total_amount": <number> }
    Response:
      {
        "total_amount": <number>,
        "delivery_charge": <0 or 30>,
        "final_amount": <number>,
        "free_delivery_threshold": 200,
        "delivery_charge_amount": 30,
        "amount_needed_for_free_delivery": <number>
      }
    """
    # Extract and validate total_amount
    try:
        total_amount = float(request.data.get('total_amount', 0))
    except (TypeError, ValueError):
        return Response(
            {"error": "Invalid or missing 'total_amount'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Define delivery rules (you can move these to settings or database)

    vendor = _vendor_by_id(request.data.get('vendor'))
    delivery_charge, minimum, charge = _delivery_charge_for(total_amount, vendor)
    final_amount = Decimal(str(total_amount)) + delivery_charge
    amount_needed = max(Decimal('0'), minimum - Decimal(str(total_amount)))

    return Response({
        "total_amount": total_amount,
        "delivery_charge": float(delivery_charge),
        "final_amount": float(final_amount),
        "free_delivery_threshold": float(minimum),
        "delivery_charge_amount": float(charge),
        "min_order_amount": float(minimum),
        "amount_needed_for_free_delivery": float(amount_needed),
        "is_free_delivery": delivery_charge == 0
    })


#todo#########informme API

@api_view(['POST', 'GET'])
@permission_classes([IsAuthenticatedUser])  # Changed from IsAuthenticated to IsAuthenticatedUser
def inform_me(request):
    """
    POST: frontend users express interest in a product/option.
    GET:  (admin only) list all InformMe requests.
    """
    # --- POST handler ---
    if request.method == 'POST':
        try:
            product_id = request.data.get('product')
            product_option_id = request.data.get('product_option')

            if not product_id and not product_option_id:
                return Response(
                    {"error": "Product ID or product option ID is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            product = None
            product_option = None

            if product_option_id:
                try:
                    product_option = ProductOption.objects.get(id=product_option_id)
                    product = product_option.product
                except ProductOption.DoesNotExist:
                    return Response(
                        {"error": "Product option not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )

            if product_id:
                try:
                    product = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    return Response(
                        {"error": "Product not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )

            if product_option and product and product_option.product_id != product.id:
                return Response(
                    {"error": "Product option does not belong to the specified product"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if user already has a request for this product/option
            existing_request = InformMe.objects.filter(
                user=request.user,
                product=product,
                product_option=product_option
            ).first()

            if existing_request:
                return Response(
                    {"message": "You are already subscribed to notifications for this item"},
                    status=status.HTTP_200_OK
                )

            if product_option:
                base_price = product_option.effective_price()
                offer_price = request.data.get('offer_price') or product_option.effective_offer_price()
            else:
                base_price = product.price
                offer_price = request.data.get('offer_price') or product.offer_price

            # Create InformMe record
            inform_me_request = InformMe.objects.create(
                user=request.user,
                product=product,
                product_option=product_option,
                price=base_price,
                offer_price=offer_price
            )

            # Serialize the response
            serialized_data = {
                'id': inform_me_request.id,
                'product': product.title,
                'product_option': product_option.option if product_option else None,
                'price': base_price,
                'offer_price': offer_price,
                'created_at': inform_me_request.created_at.isoformat(),
                'message': 'Successfully registered for stock notifications'
            }

            return Response(serialized_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error in inform_me POST: {str(e)}")
            return Response(
                {"error": "Internal server error", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # --- GET handler ---
    elif request.method == 'GET':
        # Only admin users may list all requests
        if not hasattr(request.user, 'is_staff') or not request.user.is_staff:
            return Response(
                {"detail": "You do not have permission to perform this action."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            inform_me_requests = InformMe.objects.select_related(
                'user', 'product', 'product_option'
            ).all().order_by('-created_at')

            # Serialize the data manually since you don't have the serializer imported
            serialized_requests = []
            for req in inform_me_requests:
                serialized_requests.append({
                    'id': req.id,
                    'user': req.user.fullname if hasattr(req.user, 'fullname') else req.user.email,
                    'product': req.product.title,
                    'product_option': req.product_option.option if req.product_option else None,
                    'price': req.price,
                    'offer_price': req.offer_price,
                    'created_at': req.created_at.isoformat()
                })

            return Response(serialized_requests, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in inform_me GET: {str(e)}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST', 'GET'])
@permission_classes([IsAuthenticatedUser])
def suggest_product(request):
    """
    POST: customer suggests a product missing from search/catalog.
    GET: admin-only list of all suggestions.
    """
    if request.method == 'POST':
        try:
            product_name = (request.data.get('product_name') or '').strip()
            search_query = (request.data.get('search_query') or '').strip()
            notes = (request.data.get('notes') or '').strip()

            if not product_name:
                return Response(
                    {'error': 'product_name is required'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if len(product_name) > 255:
                return Response(
                    {'error': 'product_name is too long'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            suggestion = ProductSuggestion.objects.create(
                user=request.user,
                product_name=product_name,
                search_query=search_query,
                notes=notes,
            )

            return Response(
                {
                    'id': suggestion.id,
                    'product_name': suggestion.product_name,
                    'search_query': suggestion.search_query,
                    'message': 'Thank you! We will look into your suggestion.',
                    'created_at': suggestion.created_at.isoformat(),
                },
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            logger.error(f'Error in suggest_product POST: {e}')
            return Response(
                {'error': 'Could not save suggestion', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    if not getattr(request.user, 'is_staff', False):
        return Response(
            {'detail': 'You do not have permission to perform this action.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    suggestions = ProductSuggestion.objects.select_related('user').order_by('-created_at')
    data = [
        {
            'id': item.id,
            'user': getattr(item.user, 'fullname', None) or item.user.email,
            'user_email': item.user.email,
            'product_name': item.product_name,
            'search_query': item.search_query,
            'notes': item.notes,
            'status': item.status,
            'created_at': item.created_at.isoformat(),
        }
        for item in suggestions
    ]
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticatedUser])
def check_inform_me(request):
    """
    Check if user already has an inform me request for a specific product/option

    Query parameters:
    - product_id: Required
    - product_option_id: Optional

    Returns:
    - {"exists": true/false, "request_id": "uuid" (if exists)}
    """
    try:
        product_id = request.GET.get('product_id')
        product_option_id = request.GET.get('product_option_id')

        if not product_id and not product_option_id:
            return Response(
                {"error": "product_id or product_option_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        product = None
        product_option = None

        if product_option_id:
            try:
                product_option = ProductOption.objects.get(id=product_option_id)
                product = product_option.product
            except ProductOption.DoesNotExist:
                return Response(
                    {"error": "Product option not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        if product_id:
            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                return Response(
                    {"error": "Product not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        if product_option and product and product_option.product_id != product.id:
            return Response(
                {"error": "Product option does not belong to the specified product"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if request already exists
        existing_request = InformMe.objects.filter(
            user=request.user,
            product=product,
            product_option=product_option
        ).first()

        if existing_request:
            return Response({
                "exists": True,
                "request_id": str(existing_request.id),
                "created_at": existing_request.created_at.isoformat(),
                "message": "Notification request already exists"
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                "exists": False,
                "message": "No existing notification request found"
            }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in check_inform_me: {str(e)}")
        return Response(
            {"error": "Internal server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def get_client_ip(request):
    """Get the client's IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def version_to_tuple(version_string):
    """Convert version string like '1.2.3' to tuple (1, 2, 3) for comparison"""
    try:
        return tuple(map(int, version_string.split('.')))
    except (ValueError, AttributeError):
        return (0, 0, 0)


@api_view(['POST'])
@permission_classes([AllowAny])
def check_app_version(request):
    """
    Check if app update is available based on admin panel configuration
    """
    try:
        # Validate request data
        data = request.data
        platform = data.get('platform')
        current_version = data.get('current_version')
        current_build = data.get('current_build')

        # Validate required fields
        if not platform or not current_version or not current_build:
            return Response({
                'error': 'Missing required fields',
                'required': ['platform', 'current_version', 'current_build']
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate platform
        if platform not in ['android', 'ios']:
            return Response({
                'error': 'Invalid platform',
                'valid_platforms': ['android', 'ios']
            }, status=status.HTTP_400_BAD_REQUEST)

        # Get latest active version for platform from admin panel
        try:
            latest_version_obj = AppVersion.objects.filter(
                platform=platform,
                is_active=True
            ).first()

            if not latest_version_obj:
                return Response({
                    'error': f'No active version configured for {platform}',
                    'message': 'Please configure version in admin panel'
                }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            return Response({
                'error': 'Database error',
                'message': 'Please try again later'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Compare versions
        current_version_tuple = version_to_tuple(current_version)
        latest_version_tuple = version_to_tuple(latest_version_obj.version_name)
        min_version_tuple = version_to_tuple(latest_version_obj.min_supported_version)

        # Check if update is available
        has_update = latest_version_tuple > current_version_tuple

        # Check if current version is below minimum supported (force update)
        is_below_minimum = current_version_tuple < min_version_tuple
        is_force_update = is_below_minimum or latest_version_obj.is_force_update

        # Prepare response data
        response_data = {
            'has_update': has_update,
            'is_force_update': is_force_update and has_update,
            'current_version': current_version,
            'latest_version': latest_version_obj.version_name,
            'latest_build': latest_version_obj.version_code,
            'min_supported_version': latest_version_obj.min_supported_version,
            'store_url': latest_version_obj.store_url,
            'release_notes': latest_version_obj.release_notes,
        }

        # Set appropriate message based on update type
        if has_update:
            if is_force_update:
                if is_below_minimum:
                    response_data['update_message'] = (
                            latest_version_obj.update_message or
                            f"Your app version is outdated. Please update to v{latest_version_obj.version_name} to continue using ClickWell."
                    )
                else:
                    response_data['update_message'] = (
                            latest_version_obj.update_message or
                            f"Critical update required! Please update to v{latest_version_obj.version_name} immediately."
                    )
            else:
                response_data['update_message'] = (
                        latest_version_obj.update_message or
                        f"A new version v{latest_version_obj.version_name} is available with exciting new features!"
                )
        else:
            response_data['update_message'] = "You have the latest version of ClickWell!"

        # Simple log for debugging (no database storage)
        logger.info(f"Version check - Platform: {platform}, Current: {current_version} (build {current_build}), "
                    f"Latest: {latest_version_obj.version_name} (build {latest_version_obj.version_code}), "
                    f"Has Update: {has_update}, Force: {is_force_update}")

        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Unexpected error in version check: {str(e)}")
        return Response({
            'error': 'Internal server error',
            'message': 'Please try again later'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Test endpoint to verify API is working
@api_view(['GET'])
@permission_classes([AllowAny])
def test_api(request):
    """
    Simple test endpoint to verify API connectivity
    """
    return Response({
        'message': 'ClickWell API is working!',
        'timestamp': datetime.timezone.now(),
        'version': '1.0.0'
    }, status=status.HTTP_200_OK)


# Get current app versions (for debugging)
@api_view(['GET'])
@permission_classes([AllowAny])
def get_app_versions(request):
    """
    Get all active app versions (for debugging)
    """
    try:
        versions = AppVersion.objects.filter(is_active=True)
        data = []

        for version in versions:
            data.append({
                'platform': version.platform,
                'version_name': version.version_name,
                'version_code': version.version_code,
                'min_supported_version': version.min_supported_version,
                'is_force_update': version.is_force_update,
                'store_url': version.store_url,
                'created_at': version.created_at
            })

        return Response({
            'active_versions': data,
            'count': len(data)
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _month_start(value):
    return value.replace(day=1)


def _next_month(value):
    if value.month == 12:
        return datetime.date(value.year + 1, 1, 1)
    return datetime.date(value.year, value.month + 1, 1)


def _rupees(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0


def _profit_total():
    """Money collected for the products, without the delivery charge."""
    return Sum(ExpressionWrapper(
        F('tx_price') - F('delivery_price'),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    ))


def _buyer_name(row):
    for key in ('order__user__fullname', 'order__user__name', 'order__delivery_contact_name'):
        value = str(row.get(key) or '').strip()
        if value:
            return value
    return 'Customer'


def _sales_day_label(value):
    return value.strftime('%-d %b')


def _product_status_totals(qs):
    rows = qs.values('status').annotate(quantity=Sum('quantity'))
    by_status = {row['status']: int(row['quantity'] or 0) for row in rows}
    return {
        'ordered': sum(by_status.values()),
        'delivered': by_status.get('DELIVERED', 0),
        'cancelled': by_status.get('CANCELLED', 0),
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def sales_summary(request):
    """Product units sold for a month, the week and day inside it, plus a daily chart and top 10."""
    today = timezone.localdate()
    month_raw = (request.GET.get('month') or '').strip()
    items = OrderedProduct.objects.annotate(
        sale_date=TruncDate('created_at', tzinfo=timezone.get_current_timezone()),
    )
    vendor = _signed_in_vendor(request)
    if vendor is not None:
        items = items.filter(product_option__product__vendor=vendor)
    sold = items.exclude(status='CANCELLED')
    if month_raw:
        try:
            year_text, month_text = month_raw.split('-', 1)
            start = datetime.date(int(year_text), int(month_text), 1)
        except (TypeError, ValueError):
            return Response({'error': 'month must be YYYY-MM.'}, status=400)
    else:
        latest = sold.order_by('-sale_date').values_list('sale_date', flat=True).first()
        start = _month_start(latest or today)
    if start > _month_start(today):
        return Response({'error': 'Choose the current month or an earlier month.'}, status=400)

    end = _next_month(start) - datetime.timedelta(days=1)
    daily_rows = (
        sold.filter(sale_date__gte=start, sale_date__lte=end)
        .values('sale_date')
        .annotate(quantity=Sum('quantity'), profit=_profit_total())
    )
    by_date = {row['sale_date']: int(row['quantity'] or 0) for row in daily_rows}
    profit_by_date = {row['sale_date']: _rupees(row['profit']) for row in daily_rows}
    date_raw = (request.GET.get('date') or '').strip()
    if date_raw:
        try:
            anchor = datetime.date.fromisoformat(date_raw)
        except ValueError:
            return Response({'error': 'date must be YYYY-MM-DD.'}, status=400)
        if not (start <= anchor <= end):
            return Response({'error': 'Choose a date in this month.'}, status=400)
    elif start <= today <= end:
        anchor = today
    else:
        sold_days = [day for day, quantity in by_date.items() if quantity]
        anchor = max(sold_days) if sold_days else end
    week_start = anchor - datetime.timedelta(days=anchor.weekday())
    week_end = week_start + datetime.timedelta(days=6)

    month_days = []
    cursor = start
    while cursor <= end:
        month_days.append({
            'date': cursor.isoformat(),
            'day': cursor.day,
            'quantity': by_date.get(cursor, 0),
            'profit': profit_by_date.get(cursor, 0),
        })
        cursor += datetime.timedelta(days=1)

    week_rows = (
        sold.filter(sale_date__gte=week_start, sale_date__lte=week_end)
        .values('sale_date')
        .annotate(quantity=Sum('quantity'), profit=_profit_total())
    )
    week_by_date = {row['sale_date']: int(row['quantity'] or 0) for row in week_rows}
    week_profit_by_date = {row['sale_date']: _rupees(row['profit']) for row in week_rows}
    week_days = []
    cursor = week_start
    while cursor <= week_end:
        week_days.append({
            'date': cursor.isoformat(),
            'label': cursor.strftime('%a'),
            'quantity': week_by_date.get(cursor, 0),
            'profit': week_profit_by_date.get(cursor, 0),
        })
        cursor += datetime.timedelta(days=1)

    day_rows = (
        sold.filter(sale_date=anchor)
        .values('product_option__product__title')
        .annotate(quantity=Sum('quantity'))
        .order_by('-quantity', 'product_option__product__title')
    )
    buyer_rows = (
        sold.filter(sale_date=anchor)
        .values(
            'product_option__product__title',
            'order__user__fullname',
            'order__user__name',
            'order__delivery_contact_name',
        )
        .annotate(quantity=Sum('quantity'))
        .order_by('-quantity')
    )
    buyers_by_title = {}
    for row in buyer_rows:
        title = row['product_option__product__title'] or 'Product'
        buyers_by_title.setdefault(title, []).append({
            'name': _buyer_name(row),
            'quantity': int(row['quantity'] or 0),
        })

    month_sales = sold.filter(sale_date__gte=start, sale_date__lte=end)
    top_rows = (
        month_sales.values('product_option__product__title')
        .annotate(quantity=Sum('quantity'))
        .order_by('-quantity', 'product_option__product__title')
    )
    unsold_titles = []
    if (request.GET.get('ranking') or '').strip() == '1':
        sold_product_ids = month_sales.values('product_option__product_id')
        unsold = Product.objects.exclude(id__in=sold_product_ids)
        if vendor is not None:
            unsold = unsold.filter(vendor=vendor)
        unsold_titles = list(unsold.order_by('title').values_list('title', flat=True))

    return Response({
        'month': start.strftime('%Y-%m'),
        'month_label': start.strftime('%B %Y'),
        'previous_month': (_month_start(start) - datetime.timedelta(days=1)).strftime('%Y-%m'),
        'next_month': None if _next_month(start) > today else _next_month(start).strftime('%Y-%m'),
        'day': {
            'date': anchor.isoformat(),
            'label': _sales_day_label(anchor),
            'quantity': by_date.get(anchor, 0),
            'profit': profit_by_date.get(anchor, 0),
            'products': [
                {
                    'title': row['product_option__product__title'] or 'Product',
                    'quantity': int(row['quantity'] or 0),
                    'customers': buyers_by_title.get(row['product_option__product__title'] or 'Product', []),
                }
                for row in day_rows
            ],
        },
        'week': {
            'start': week_start.isoformat(),
            'end': week_end.isoformat(),
            'label': f'{_sales_day_label(week_start)} – {_sales_day_label(week_end)}',
            'quantity': sum(item['quantity'] for item in week_days),
            'profit': round(sum(item['profit'] for item in week_days), 2),
            'days': week_days,
        },
        'month_total': {
            'quantity': sum(item['quantity'] for item in month_days),
            'profit': round(sum(item['profit'] for item in month_days), 2),
            'days': month_days,
        },
        'top_products': [
            {
                'title': row['product_option__product__title'] or 'Product',
                'quantity': int(row['quantity'] or 0),
            }
            for row in top_rows
        ],
        'unsold_products': [
            {'title': title or 'Product', 'quantity': 0}
            for title in unsold_titles
            if (title or '').strip()
        ],
        'status_totals': {
            'month': _product_status_totals(
                items.filter(sale_date__gte=start, sale_date__lte=end)
            ),
            'lifetime': _product_status_totals(items),
        },
    })


def _sales_customer_address(order):
    address = getattr(order, 'user_address', None)
    if address is None:
        return (getattr(order, 'address', '') or '').strip()
    chunks = []
    for value in (
        getattr(address, 'house', ''),
        getattr(address, 'address', ''),
        getattr(address, 'locality', ''),
        getattr(address, 'landmark', ''),
        getattr(address, 'city', ''),
        getattr(address, 'district', ''),
        getattr(address, 'state', ''),
        str(getattr(address, 'pincode', '') or ''),
    ):
        text = ' '.join(str(value or '').strip().split())
        if not text:
            continue
        lower = text.lower()
        if any(lower in existing.lower() for existing in chunks):
            continue
        chunks = [existing for existing in chunks if existing.lower() not in lower]
        chunks.append(text)
    if chunks:
        return ', '.join(chunks)
    return (getattr(order, 'address', '') or '').strip()


@api_view(['GET'])
@permission_classes([AllowAny])
def sales_status_items(request):
    """Product rows for a sales status card: ordered, delivered, or cancelled."""
    from backend.vendor_orders_views import _customer_name, _customer_phone

    status_key = (request.GET.get('status') or 'ordered').strip().lower()
    scope = (request.GET.get('scope') or 'month').strip().lower()
    month_raw = (request.GET.get('month') or '').strip()
    try:
        page = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    page_size = 40

    items = OrderedProduct.objects.select_related(
        'product_option',
        'product_option__product',
        'order',
        'order__user',
        'order__user_address',
        'handled_by',
    ).annotate(
        sale_date=TruncDate('created_at', tzinfo=timezone.get_current_timezone()),
    )
    vendor = _signed_in_vendor(request)
    if vendor is not None:
        items = items.filter(product_option__product__vendor=vendor)

    if status_key == 'delivered':
        items = items.filter(status='DELIVERED')
    elif status_key == 'cancelled':
        items = items.filter(status='CANCELLED')
    elif status_key != 'ordered':
        return Response({'error': 'status must be ordered, delivered, or cancelled.'}, status=400)

    today = timezone.localdate()
    month_value = ''
    if scope == 'lifetime':
        label = 'Lifetime'
    else:
        if month_raw:
            try:
                year_text, month_text = month_raw.split('-', 1)
                start = datetime.date(int(year_text), int(month_text), 1)
            except (TypeError, ValueError):
                return Response({'error': 'month must be YYYY-MM.'}, status=400)
        else:
            start = datetime.date(today.year, today.month, 1)
        end = _next_month(start) - datetime.timedelta(days=1)
        items = items.filter(sale_date__gte=start, sale_date__lte=end)
        label = start.strftime('%B %Y')
        month_value = start.strftime('%Y-%m')

    units = int(items.aggregate(total=Sum('quantity')).get('total') or 0)
    rows = items.order_by('-created_at')
    total = rows.count()
    start_index = (page - 1) * page_size
    page_rows = list(rows[start_index:start_index + page_size])
    results = []
    for item in page_rows:
        option = item.product_option
        product = option.product if option is not None else None
        order = item.order
        created = item.created_at
        handler_name = (item.handled_by_name or '').strip()
        handler_phone = ''
        partner = item.handled_by
        if partner is not None:
            if not handler_name:
                handler_name = (partner.name or partner.login_id or '').strip()
            handler_phone = (partner.phone or '').strip()
        handled_at = item.handled_at
        results.append({
            'id': str(item.id),
            'product': product.title if product is not None else 'Product',
            'option': option.option if option is not None else '',
            'quantity': int(item.quantity or 0),
            'status': item.status or '',
            'created_at': timezone.localtime(created).strftime('%d %b %Y') if created else '',
            'customer_name': _customer_name(order) if order is not None else 'Customer',
            'customer_phone': _customer_phone(order) if order is not None else '',
            'address': _sales_customer_address(order) if order is not None else '',
            'handled_by_name': handler_name,
            'handled_by_phone': handler_phone,
            'handled_at': timezone.localtime(handled_at).strftime('%d %b %Y, %I:%M %p') if handled_at else '',
        })
    return Response({
        'status': status_key,
        'scope': scope,
        'month': month_value,
        'label': label,
        'units': units,
        'count': total,
        'page': page,
        'page_size': page_size,
        'has_more': start_index + page_size < total,
        'results': results,
    })
