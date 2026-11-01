from rest_framework.fields import SerializerMethodField
from rest_framework.serializers import ModelSerializer
from rest_framework import serializers
from django.utils import timezone

from backend.models import User, Category, Slide, Product, ProductOption, ProductImage, PageItem, OrderedProduct, \
    Notification, ContactInfo, InformMe, AppVersion, UserAddress


def format_order_datetime(dt):
    """Format an aware datetime in the app's local timezone (Asia/Kolkata)."""
    if dt is None:
        return ''
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt).strftime('%d %B %Y, %I:%M %p')



class AddressSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['name', 'address', 'contact_no', 'pincode', 'state', 'district']


class UserAddressSerializer(ModelSerializer):
    class Meta:
        model = UserAddress
        fields = [
            'id', 'label', 'name', 'address', 'house', 'locality', 'landmark',
            'city', 'contact_no', 'pincode', 'state', 'district',
            'latitude', 'longitude', 'is_default',
        ]


class UserSerializer(ModelSerializer):
    notifications = SerializerMethodField()
    addresses = SerializerMethodField()

    class Meta:
        model = User
        fields = ['email', 'notifications', 'phone', 'fullname', 'wishlist', 'cart', 'name', 'address', 'contact_no',
                  'pincode', 'state', 'district', 'addresses']

    def get_notifications(self, obj):
        list = obj.notifications_set.filter(seen=False)
        return len(list)

    def get_addresses(self, obj):
        return UserAddressSerializer(obj.addresses_set.all(), many=True).data


class CategorySerializer(ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'position', 'image']

    def get_image(self, obj):
        request = self.context.get('request')
        if obj.image:
            image_url = obj.image.url
            return request.build_absolute_uri(image_url) if request else image_url
        return None


class SlideSerializer(ModelSerializer):
    image = SerializerMethodField()
    category = serializers.IntegerField(source='category_id', read_only=True)

    class Meta:
        model = Slide
        fields = ['position', 'image', 'category']

    def get_image(self, obj):
        request = self.context.get('request')
        if obj.image:
            image_url = obj.image.url
            return request.build_absolute_uri(image_url) if request else image_url
        return None


# Enhanced ProductSerializer with better image handling
class ProductSerializer(ModelSerializer):
    options = SerializerMethodField()
    category_name = SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'title', 'description', 'price', 'offer_price', 'delivery_charge', 'cod', 'star_5', 'star_4',
                  'star_3', 'star_2', 'star_1', 'options', 'category', 'category_name', 'subcategory',
                  'subcategories', 'barcode',
                  'created_at', 'updated_at']

    def get_options(self, obj):
        options = obj.options_set.all()
        data = ProductOptionSerializer(options, many=True, context=self.context).data
        return data

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None




class ProductOptionSerializer(ModelSerializer):
    images = SerializerMethodField()
    price = SerializerMethodField()
    offer_price = SerializerMethodField()
    raw_price = SerializerMethodField()
    raw_offer_price = SerializerMethodField()

    class Meta:
        model = ProductOption
        fields = [
            'id', 'option', 'quantity', 'images',
            'price', 'offer_price', 'raw_price', 'raw_offer_price',
        ]

    def get_price(self, obj):
        return float(obj.effective_price())

    def get_offer_price(self, obj):
        return float(obj.effective_offer_price())

    def get_raw_price(self, obj):
        return float(obj.price or 0)

    def get_raw_offer_price(self, obj):
        return float(obj.offer_price or 0)

    def get_images(self, obj):
        images = obj.images_set.all()
        data = ProductImageSerializer(images, many=True).data
        return data




class ProductImageSerializer(ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['position', 'image', 'product_option']


class WishlistSerializer(ModelSerializer):
    id = SerializerMethodField()
    product_id = SerializerMethodField()
    title = SerializerMethodField()
    price = SerializerMethodField()
    offer_price = SerializerMethodField()
    image = SerializerMethodField()
    quantity = SerializerMethodField()

    def get_id(self, obj):
        # Return ProductOption id for cart/wishlist operations.
        return obj.id

    def get_product_id(self, obj):
        # Keep product id for screens that need product-level context.
        return obj.product.id

    def get_quantity(self, obj):
        return obj.quantity

    def get_title(self, obj):
        return obj.__str__()

    def get_price(self, obj):
        return obj.effective_price()

    def get_offer_price(self, obj):
        return obj.effective_offer_price()

    def get_image(self, obj):
        return ProductImageSerializer(obj.images_set.order_by('position').first(), many=False).data.get(
            'image')

    class Meta:
        model = ProductOption
        fields = ['id', 'product_id', 'title', 'image', 'price', 'offer_price', 'quantity']


class CartSerializer(WishlistSerializer):
    cod = SerializerMethodField()
    delivery_charge = SerializerMethodField()
    id = SerializerMethodField()

    def get_cod(self, obj):
        return obj.product.cod

    def get_delivery_charge(self, obj):
        return obj.product.delivery_charge

    def get_id(self, obj):
        return obj.id

    class Meta:
        model = ProductOption
        fields = ['id', 'title', 'image', 'price', 'offer_price', 'quantity', 'cod', 'delivery_charge']


class PageItemSerializer(ModelSerializer):
    product_options = SerializerMethodField()

    class Meta:
        model = PageItem
        fields = ['id', 'position', 'image', 'category', 'title', 'viewtype', 'product_options']

    def get_product_options(self, obj):
        links = obj.option_links.select_related('product_option__product').order_by('position', 'id')
        request = self.context.get('request')
        vendor = request.GET.get('vendor') if request is not None else None
        if vendor:
            links = links.filter(product_option__product__vendor_id=vendor)
        options = [link.product_option for link in links[:8]]
        data = []
        for option in options:
            # Get the first image safely
            first_image = option.images_set.order_by('position').first()
            image_url = None
            if first_image and first_image.image:
                image_url = first_image.image.url if hasattr(first_image.image, 'url') else None

            data.append({
                'id': str(option.id),  # ✅ ProductOption ID (for cart operations)
                'product_id': str(option.product.id),  # ✅ NEW: Product ID (for product details)
                'image': image_url,
                'title': option.__str__(),
                'price': option.effective_price(),
                'offer_price': option.effective_offer_price(),
                'quantity': option.quantity,
            })

        return data
class OrderItemSerializer(ModelSerializer):
    title = SerializerMethodField()
    image = SerializerMethodField()
    created_at = SerializerMethodField()

    class Meta:
        model = OrderedProduct
        fields = ['id', 'title', 'image', 'created_at', 'quantity', 'status', 'rating']

    def get_title(self, obj):
        return obj.product_option.__str__()

    def get_image(self, obj):
        return ProductImageSerializer(obj.product_option.images_set.order_by('position').first(), many=False).data.get(
            'image')

    def get_created_at(self, obj):
        order_time = obj.order.created_at if obj.order_id else obj.created_at
        return format_order_datetime(order_time)


class OrderDetailLineItemSerializer(ModelSerializer):
    title = SerializerMethodField()
    image = SerializerMethodField()
    product_id = serializers.CharField(source='product_option.product.id', read_only=True)
    product_option_id = serializers.CharField(source='product_option.id', read_only=True)
    line_total = SerializerMethodField()

    class Meta:
        model = OrderedProduct
        fields = [
            'id', 'title', 'image', 'quantity', 'product_price', 'tx_price',
            'delivery_price', 'status', 'product_id', 'product_option_id', 'line_total',
        ]

    def get_title(self, obj):
        return obj.product_option.__str__()

    def get_image(self, obj):
        first_image = obj.product_option.images_set.order_by('position').first()
        if not first_image:
            return None
        return ProductImageSerializer(first_image, many=False).data.get('image')

    def get_line_total(self, obj):
        return (obj.product_price or 0) * (obj.quantity or 1)


class OrderDetailsSerializer(OrderItemSerializer):
    payment_mode = SerializerMethodField()
    address = SerializerMethodField()
    tx_id = SerializerMethodField()
    tx_status = SerializerMethodField()
    user_phone = SerializerMethodField()
    order_items = SerializerMethodField()
    order_total = SerializerMethodField()
    items_subtotal = SerializerMethodField()
    total_delivery = SerializerMethodField()
    from_cart = SerializerMethodField()
    order_id = SerializerMethodField()
    shop_name = SerializerMethodField()
    shop_image = SerializerMethodField()
    shop_phone = SerializerMethodField()
    address_label = SerializerMethodField()
    delivery_type = SerializerMethodField()
    delivery_date = SerializerMethodField()
    delivery_slot = SerializerMethodField()
    delivery_eta = SerializerMethodField()
    delivery_label = SerializerMethodField()
    cancel_request_status = SerializerMethodField()
    can_request_cancel = SerializerMethodField()
    cancel_request_pending = SerializerMethodField()

    #temp. code
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6,
        required=False, allow_null=True
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6,
        required=False, allow_null=True
    )

    class Meta:
        model = OrderedProduct
        fields = [
            'id', 'title', 'image', 'created_at', 'quantity', 'status', 'rating',
            'product_price', 'tx_price', 'delivery_price', 'payment_mode', 'address',
            'tx_id', 'tx_status', 'latitude', 'longitude', 'user_phone',
            'order_items', 'order_total', 'items_subtotal', 'total_delivery', 'from_cart',
            'order_id', 'shop_name', 'shop_image', 'shop_phone', 'address_label',
            'delivery_type', 'delivery_date', 'delivery_slot', 'delivery_eta',
            'delivery_label',
            'cancel_request_status', 'can_request_cancel', 'cancel_request_pending',
        ]

    def get_payment_mode(self, obj):
        return obj.order.payment_mode

    def get_address(self, obj):
        return obj.order.address

    def get_tx_id(self, obj):
        return obj.order.tx_id

    def get_tx_status(self, obj):
        return obj.order.tx_status

    def get_user_phone(self, obj):
        return obj.order.user.phone

    def get_order_items(self, obj):
        siblings = OrderedProduct.objects.filter(order=obj.order).select_related(
            'product_option', 'product_option__product',
        ).order_by('created_at')
        return OrderDetailLineItemSerializer(
            siblings, many=True, context=self.context,
        ).data

    def get_order_total(self, obj):
        return obj.order.tx_amount

    def get_items_subtotal(self, obj):
        items = obj.order.orders_set.all()
        return sum((item.product_price or 0) * (item.quantity or 1) for item in items)

    def get_total_delivery(self, obj):
        items = obj.order.orders_set.all()
        return sum(item.delivery_price or 0 for item in items)

    def get_from_cart(self, obj):
        return obj.order.from_cart

    def get_order_id(self, obj):
        return str(obj.order_id) if obj.order_id else ''

    def _vendor(self, obj):
        try:
            return obj.product_option.product.vendor
        except Exception:
            return None

    def get_shop_name(self, obj):
        vendor = self._vendor(obj)
        return getattr(vendor, 'shop_name', '') or ''

    def get_shop_image(self, obj):
        vendor = self._vendor(obj)
        if vendor is None or not vendor.shop_image:
            return ''
        try:
            return vendor.shop_image.url
        except Exception:
            return ''

    def get_shop_phone(self, obj):
        vendor = self._vendor(obj)
        if vendor is None:
            return ''
        return (getattr(vendor, 'phone', '') or '').strip() or (
            getattr(vendor, 'alternate_phone', '') or ''
        ).strip()

    def get_address_label(self, obj):
        address = getattr(obj.order, 'user_address', None)
        if address is None:
            return 'Home'
        return address.label or 'Home'

    def get_delivery_type(self, obj):
        return getattr(obj.order, 'delivery_type', '') or ''

    def get_delivery_date(self, obj):
        day = getattr(obj.order, 'delivery_date', None)
        return day.isoformat() if day else ''

    def get_delivery_slot(self, obj):
        return getattr(obj.order, 'delivery_slot', '') or ''

    def get_delivery_eta(self, obj):
        return getattr(obj.order, 'delivery_eta', '') or ''

    def _cancel_flags(self, obj):
        cached = getattr(obj, '_cancel_flags', None)
        if cached is None:
            cached = obj.order.cancel_request_payload()
            obj._cancel_flags = cached
        return cached

    def get_cancel_request_status(self, obj):
        return self._cancel_flags(obj).get('cancel_request_status', '')

    def get_can_request_cancel(self, obj):
        return self._cancel_flags(obj).get('can_request_cancel', False)

    def get_cancel_request_pending(self, obj):
        return self._cancel_flags(obj).get('cancel_request_pending', False)

    def get_delivery_label(self, obj):
        order = obj.order
        kind = getattr(order, 'delivery_type', '') or ''
        if kind in ('quick', 'express'):
            return getattr(order, 'delivery_eta', '') or ''
        parts = []
        day = getattr(order, 'delivery_date', None)
        if day is not None:
            parts.append(day.strftime('%d %B %Y'))
        slot = (getattr(order, 'delivery_slot', '') or '').strip()
        if slot:
            parts.append(slot)
        return '\n'.join(parts)


class NotificationSerializer(ModelSerializer):
    created_at = SerializerMethodField()
    product_option_id = SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'body', 'image', 'seen',
            'created_at', 'product_option_id',
        ]

    def get_created_at(self, obj):
        return format_order_datetime(obj.created_at)

    def get_product_option_id(self, obj):
        if obj.product_option_id:
            return str(obj.product_option_id)
        return None

class PrivacyPolicySerializer(serializers.Serializer):
    content = serializers.CharField(trim_whitespace=False)

class ContactUsSerializer(serializers.Serializer):
    content = serializers.CharField(trim_whitespace=False)


# class OrderDetailSerializer(serializers.ModelSerializer):
#     user = serializers.CharField(source='user.email', read_only=True)  # Fetch email from user

#     class Meta:
#         model = Order
#         fields = [
#             'id', 'user', 'tx_amount', 'payment_mode', 'address', 'tx_id',
#             'tx_status', 'tx_time', 'tx_msg', 'from_cart', 'created_at', 'updated_at'
#         ]





class ItemOrderSerializer(serializers.ModelSerializer):
    """
    Main serializer for ordered products with full details.
    Includes related products in the same order.
    """
    product_option = serializers.CharField(source='product_option.option')
    product_title = serializers.CharField(source='product_option.product.title')
    product_image = serializers.SerializerMethodField()
    product_mrp = serializers.SerializerMethodField()
    user_fullname = serializers.CharField(source='order.user.fullname', read_only=True)
    user_phone = serializers.CharField(source='order.user.phone', read_only=True)
    user_address_name = serializers.SerializerMethodField()
    user_address_contact = serializers.SerializerMethodField()
    payment_mode = serializers.CharField(source='order.payment_mode', read_only=True)
    tx_status = serializers.CharField(source='order.tx_status', read_only=True)
    tx_msg = serializers.CharField(source='order.tx_msg', read_only=True)
    address = serializers.CharField(source='order.address', read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    order_for_someone_else = serializers.BooleanField(
        source='order.order_for_someone_else',
        read_only=True,
    )
    order_placed_at = serializers.SerializerMethodField()
    related_products = serializers.SerializerMethodField()
    shop_name = serializers.SerializerMethodField()
    delivery_type = serializers.SerializerMethodField()
    delivery_date = serializers.SerializerMethodField()
    delivery_slot = serializers.SerializerMethodField()
    delivery_eta = serializers.SerializerMethodField()
    delivery_label = serializers.SerializerMethodField()
    cancel_request_status = serializers.SerializerMethodField()
    can_request_cancel = serializers.SerializerMethodField()
    cancel_request_pending = serializers.SerializerMethodField()

    class Meta:
        model = OrderedProduct
        fields = [
            'id',
            'quantity',
            'product_option',
            'product_title',
            'product_image',
            'user_fullname',
            'user_phone',
            'user_address_name',      # NEW
            'user_address_contact',   # NEW
            'payment_mode',
            'tx_status',
            'tx_msg',
            'address',
            'latitude',
            'longitude',
            'order_for_someone_else',
            'tx_price',
            'product_price',
            'product_mrp',
            'delivery_price',
            'status',
            'created_at',
            'updated_at',
            'order_placed_at',
            'related_products',
            'shop_name',
            'delivery_type',
            'delivery_date',
            'delivery_slot',
            'delivery_eta',
            'delivery_label',
            'cancel_request_status',
            'can_request_cancel',
            'cancel_request_pending',
        ]

    def _order_coordinates(self, obj):
        order = obj.order
        lat = order.latitude
        lng = order.longitude
        if lat is not None and lng is not None:
            return lat, lng
        user_address = getattr(order, 'user_address', None)
        if user_address and user_address.latitude is not None and user_address.longitude is not None:
            return user_address.latitude, user_address.longitude
        return None, None

    def get_latitude(self, obj):
        lat, _ = self._order_coordinates(obj)
        return float(lat) if lat is not None else None

    def get_longitude(self, obj):
        _, lng = self._order_coordinates(obj)
        return float(lng) if lng is not None else None

    def get_order_placed_at(self, obj):
        placed_at = obj.order.created_at if obj.order_id else obj.created_at
        return format_order_datetime(placed_at)

    def get_product_image(self, obj):
        """Get absolute URL for product image"""
        if obj.product_option.images_set.exists():
            request = self.context.get('request')
            image_url = obj.product_option.images_set.first().image.url
            return request.build_absolute_uri(image_url) if request else f"/{image_url.lstrip('/')}"
        return None

    def get_product_mrp(self, obj):
        """Catalog MRP (product/option price), distinct from selling product_price."""
        try:
            return float(obj.product_option.effective_price())
        except Exception:
            return float(obj.product_price or 0)

    def get_user_address_name(self, obj):
        order = obj.order
        if order.delivery_contact_name:
            return order.delivery_contact_name
        user_address = getattr(order, 'user_address', None)
        if user_address and (user_address.name or '').strip():
            return user_address.name.strip()
        return order.user.fullname or order.user.name

    def get_user_address_contact(self, obj):
        order = obj.order
        if order.delivery_contact_phone:
            return order.delivery_contact_phone
        user_address = getattr(order, 'user_address', None)
        if user_address and (user_address.contact_no or '').strip():
            return user_address.contact_no.strip()
        return order.user.phone or order.user.contact_no

    def get_related_products(self, obj):
        """
        Get all other products in the same order.
        Excludes the current product.
        """
        related_products = OrderedProduct.objects.filter(
            order=obj.order
        ).exclude(
            id=obj.id
        )

        return RelatedProductSerializer(
            related_products,
            many=True,
            context=self.context
        ).data

    def _order_vendor(self, obj):
        try:
            return obj.product_option.product.vendor
        except Exception:
            return None

    def get_shop_name(self, obj):
        vendor = self._order_vendor(obj)
        return getattr(vendor, 'shop_name', '') or ''

    def get_delivery_type(self, obj):
        return getattr(obj.order, 'delivery_type', '') or ''

    def get_delivery_date(self, obj):
        day = getattr(obj.order, 'delivery_date', None)
        return day.isoformat() if day else ''

    def get_delivery_slot(self, obj):
        return getattr(obj.order, 'delivery_slot', '') or ''

    def get_delivery_eta(self, obj):
        return getattr(obj.order, 'delivery_eta', '') or ''

    def get_delivery_label(self, obj):
        order = obj.order
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

    def _cancel_flags(self, obj):
        cached = getattr(obj, '_cancel_flags', None)
        if cached is None:
            cached = obj.order.cancel_request_payload()
            obj._cancel_flags = cached
        return cached

    def get_cancel_request_status(self, obj):
        return self._cancel_flags(obj).get('cancel_request_status', '')

    def get_can_request_cancel(self, obj):
        return self._cancel_flags(obj).get('can_request_cancel', False)

    def get_cancel_request_pending(self, obj):
        return self._cancel_flags(obj).get('cancel_request_pending', False)

class ContactInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactInfo
        fields = ['phone_number']


class RelatedProductSerializer(serializers.ModelSerializer):
    """
    Serializer for related products in an order.
    Used to show other products in the same order.
    """
    product_option = serializers.CharField(source='product_option.option')
    product_title = serializers.CharField(source='product_option.product.title')
    product_image = serializers.SerializerMethodField()
    product_mrp = serializers.SerializerMethodField()

    class Meta:
        model = OrderedProduct
        fields = [
            'id',
            'product_option',
            'product_title',
            'product_image',
            'quantity',
            'product_price',
            'product_mrp',
            'tx_price',
            'delivery_price',
            'status',

        ]

    def get_product_image(self, obj):
        """Get absolute URL for product image"""
        if obj.product_option.images_set.exists():
            request = self.context.get('request')
            image_url = obj.product_option.images_set.first().image.url
            return request.build_absolute_uri(image_url) if request else f"/{image_url.lstrip('/')}"
        return None

    def get_product_mrp(self, obj):
        """Catalog MRP (product/option price), distinct from selling product_price."""
        try:
            return float(obj.product_option.effective_price())
        except Exception:
            return float(obj.product_price or 0)


# Validation serializers for API requests
class ProductCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=500)
    description = serializers.CharField(max_length=100000, allow_blank=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    offer_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    delivery_charge = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, default=0)
    cod = serializers.BooleanField(default=False)
    category = serializers.CharField()

    def validate_category(self, value):
        try:
            category = Category.objects.get(id=value)
            return category
        except Category.DoesNotExist:
            raise serializers.ValidationError("Category not found")

    def validate(self, data):
        if data['offer_price'] > data['price']:
            raise serializers.ValidationError("Offer price cannot be greater than original price")
        return data


class ProductOptionCreateSerializer(serializers.Serializer):
    product = serializers.CharField()
    option = serializers.CharField(max_length=50)
    quantity = serializers.IntegerField(min_value=0, default=0)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False, default=0)
    offer_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False, default=0)

    def validate_product(self, value):
        try:
            product = Product.objects.get(id=value)
            return product
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found")


class ProductUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=500, required=False)
    description = serializers.CharField(max_length=100000, allow_blank=True, required=False)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    offer_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    delivery_charge = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    cod = serializers.BooleanField(required=False)

    def validate(self, data):
        # If both price and offer_price are provided, validate them
        if 'price' in data and 'offer_price' in data:
            if data['offer_price'] > data['price']:
                raise serializers.ValidationError("Offer price cannot be greater than original price")
        return data


class ProductOptionUpdateSerializer(serializers.Serializer):
    option = serializers.CharField(max_length=50, required=False)
    quantity = serializers.IntegerField(min_value=0, required=False)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    offer_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)


class BulkStockUpdateSerializer(serializers.Serializer):
    option_id = serializers.CharField()
    quantity = serializers.IntegerField(min_value=0)

    def validate_option_id(self, value):
        try:
            option = ProductOption.objects.get(id=value)
            return option
        except ProductOption.DoesNotExist:
            raise serializers.ValidationError("Product option not found")


class ImageUploadSerializer(serializers.Serializer):
    product_option = serializers.CharField()
    position = serializers.IntegerField(min_value=0, default=0)
    image = serializers.ImageField()

    def validate_product_option(self, value):
        try:
            option = ProductOption.objects.get(id=value)
            return option
        except ProductOption.DoesNotExist:
            raise serializers.ValidationError("Product option not found")

    def validate_image(self, value):
        # Validate file size (5MB max)
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Image file too large (max 5MB)")

class InformMeSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    product_option = serializers.PrimaryKeyRelatedField(
        queryset=ProductOption.objects.all(),
        allow_null=True,
        required=False
    )

    class Meta:
        model = InformMe
        fields = [
            'id', 'user', 'product', 'product_option',
            'price', 'offer_price', 'created_at'
        ]
        read_only_fields = ['id', 'user', 'price', 'created_at']

class VersionCheckRequestSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=['android', 'ios'])
    current_version = serializers.CharField(max_length=20)
    current_build = serializers.IntegerField()
    device_id = serializers.CharField(max_length=255, required=False, allow_blank=True)

class VersionCheckResponseSerializer(serializers.Serializer):
    has_update = serializers.BooleanField()
    is_force_update = serializers.BooleanField()
    current_version = serializers.CharField()
    latest_version = serializers.CharField()
    latest_build = serializers.IntegerField()
    update_message = serializers.CharField()
    release_notes = serializers.CharField()
    store_url = serializers.URLField()
    min_supported_version = serializers.CharField()

class AppVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = '__all__'


