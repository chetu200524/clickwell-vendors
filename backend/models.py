import uuid
from datetime import time, timedelta
from decimal import Decimal

import os
from django.core.exceptions import ValidationError
from django.db import models


class Otp(models.Model):
    phone = models.CharField(max_length=10)
    otp = models.IntegerField()
    validity = models.DateTimeField()
    verified = models.BooleanField(default=False)

    def __str__(self):
        return self.phone


class Category(models.Model):
    name = models.CharField(max_length=50)
    position = models.IntegerField(default=0)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)

    def __str__(self):
        return self.name


class Slide(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='slides_set',
    )
    vendor = models.ForeignKey(
        'Vendor',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='slides',
    )
    position = models.IntegerField(default=0)
    image = models.ImageField(upload_to='categories/')

    class Meta:
        ordering = ['position']

    def __str__(self):
        return f'{self.category.name} — slide {self.position}'


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products_set')
    vendor = models.ForeignKey(
        'Vendor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )
    title = models.CharField(max_length=500)
    description = models.TextField(max_length=100000)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    offer_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    star_5 = models.IntegerField(default=0)
    star_4 = models.IntegerField(default=0)
    star_3 = models.IntegerField(default=0)
    star_2 = models.IntegerField(default=0)
    star_1 = models.IntegerField(default=0)
    cod = models.BooleanField(default=True)
    subcategory = models.TextField(
        blank=True,
        default='',
        help_text='Comma-separated copy of the subcategory chips, kept for search.',
    )
    subcategories = models.JSONField(
        blank=True,
        default=list,
        help_text='Subcategory chips saved on this product. A product can have several.',
    )
    barcode = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text='Optional product barcode captured when the product is added.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


def known_subcategory_spellings(vendor_id=None):
    """Map of lowercase name to the spelling already stored on a product."""
    spellings = {}
    products = Product.objects.all()
    if vendor_id is not None:
        products = products.filter(vendor_id=vendor_id)
    for names, legacy in products.values_list('subcategories', 'subcategory'):
        items = names if isinstance(names, list) and names else []
        if not items and legacy:
            items = [part.strip() for part in str(legacy).split(',')]
        for name in items:
            cleaned = str(name or '').strip()
            if cleaned:
                spellings.setdefault(cleaned.casefold(), cleaned)
    return spellings


def resolve_subcategory_names(raw):
    """Turn one name or a list into unique chips, reusing a saved spelling."""
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith('['):
            try:
                import json
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = [part.strip() for part in text.split(',') if part.strip()]
            raw_items = parsed if isinstance(parsed, list) else [parsed]
        else:
            raw_items = [part.strip() for part in text.split(',') if part.strip()]
    elif isinstance(raw, (list, tuple)):
        raw_items = list(raw)
    else:
        raw_items = [raw]

    spellings = known_subcategory_spellings()
    resolved = []
    seen = set()
    for item in raw_items:
        name = str(item or '').strip()[:100]
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        canonical = spellings.get(key, name)
        spellings[key] = canonical
        resolved.append(canonical)
        if len(resolved) >= 30:
            break
    return resolved


def resolve_subcategory_name(raw):
    """Trim one subcategory and reuse the stored spelling when one already exists."""
    names = resolve_subcategory_names(raw)
    return names[0] if names else ''


def normalize_barcode(raw):
    """Trim a scanned barcode and keep it within the stored length."""
    return str(raw or '').strip()[:128]


class ProductOption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='options_set')
    option = models.CharField(max_length=50, blank=True)
    quantity = models.IntegerField(default=0)
    # 0 means inherit from parent product
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    offer_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def effective_price(self):
        if self.price and self.price > 0:
            return self.price
        return self.product.price

    def effective_offer_price(self):
        if self.offer_price and self.offer_price > 0:
            return self.offer_price
        return self.product.offer_price

    def __str__(self):
        return f"({self.option}) {self.product.title}"


class User(models.Model):
    email = models.EmailField()
    phone = models.CharField(max_length=10)
    fullname = models.CharField(max_length=100)
    password = models.CharField(max_length=5000)
    wishlist = models.ManyToManyField(ProductOption, blank=True, related_name="wishlist")
    cart = models.ManyToManyField(ProductOption, blank=True, related_name="cart")
    created_at = models.DateTimeField(auto_now_add=True)
    # address fields
    name = models.CharField(max_length=100, blank=True)
    address = models.TextField(max_length=1000, blank=True)
    pincode = models.IntegerField(blank=True, null=True)
    contact_no = models.CharField(max_length=10, blank=True)
    district = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=500, blank=True)

    @property
    def is_authenticated(self):
        return True

    def __str__(self):
        return self.email


class UserAddress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses_set')
    label = models.CharField(max_length=50, default='Home')
    name = models.CharField(max_length=100)
    address = models.TextField(max_length=1000)
    house = models.CharField(max_length=200, blank=True, default='')
    locality = models.CharField(max_length=300, blank=True, default='')
    landmark = models.CharField(max_length=200, blank=True, default='')
    city = models.CharField(max_length=200, blank=True, default='')
    pincode = models.IntegerField()
    contact_no = models.CharField(max_length=10)
    district = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=500, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-updated_at']

    def __str__(self):
        return f'{self.label} — {self.name} ({self.user.email})'


class Token(models.Model):
    token = models.CharField(max_length=5000)
    fcmtoken = models.CharField(max_length=5000)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tokens_set")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.email


class PasswordResetToken(models.Model):
    token = models.CharField(max_length=5000)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens_set")
    validity = models.DateTimeField()

    def __str__(self):
        return self.user.email


class ProductImage(models.Model):
    position = models.IntegerField(default=0)
    image = models.ImageField(upload_to='product/')
    product_option = models.ForeignKey(ProductOption, on_delete=models.CASCADE, related_name='images_set')


class PageItem(models.Model):
    vendor = models.ForeignKey(
        'Vendor',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='page_items',
    )
    position = models.IntegerField(default=0)
    image = models.ImageField(upload_to='product/', blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='pageitems_set')
    choices = [
        (1, 'BANNER'),
        (2, 'SWIPER'),
        (3, 'GRID'),
        (4, 'ROW'),
        (5, 'OFFERS'),
    ]
    viewtype = models.IntegerField(choices=choices)
    title = models.CharField(max_length=50, blank=True)
    product_options = models.ManyToManyField(ProductOption, blank=True, through='PageItemOption')

    def __str__(self):
        return self.category.name


class PageItemOption(models.Model):
    page_item = models.ForeignKey(PageItem, on_delete=models.CASCADE, related_name='option_links')
    product_option = models.ForeignKey(ProductOption, on_delete=models.CASCADE, related_name='page_item_links')
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['page_item', 'product_option'], name='unique_page_item_option'),
        ]


class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(
        'Vendor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        help_text='Shop this order belongs to.',
    )
    seen = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="orders_set")
    tx_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    payment_mode = models.CharField(max_length=100, null=True)
    address = models.TextField(max_length=5000)
    tx_id = models.CharField(max_length=1000, null=True)
    tx_choices = [
        ('INITIATED', 'INITIATED'),
        ('PENDING', 'PENDING'),
        ('INCOMPLETE', 'INCOMPLETE'),
        ('FAILED', 'FAILED'),
        ('FLAGGED', 'FLAGGED'),
        ('USER_DROPPED', 'USER_DROPPED'),
        ('SUCCESS', 'SUCCESS'),
        ('CANCELLED', 'CANCELLED'),
        ('VOID', 'VOID'),
    ]
    tx_status = models.CharField(choices=tx_choices, max_length=100, null=True)
    tx_time = models.CharField(max_length=500, null=True)
    tx_msg = models.CharField(max_length=500, null=True)

    from_cart = models.BooleanField(default=True)
    order_for_someone_else = models.BooleanField(default=False)
    delivery_contact_name = models.CharField(max_length=100, blank=True, default='')
    delivery_contact_phone = models.CharField(max_length=10, blank=True, default='')
    user_address = models.ForeignKey(
        'UserAddress',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders_set',
    )
    delivery_type = models.CharField(max_length=20, blank=True, default='')
    delivery_date = models.DateField(null=True, blank=True)
    delivery_slot = models.CharField(max_length=120, blank=True, default='')
    delivery_eta = models.CharField(max_length=120, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancel_request_status = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text='pending, approved, or rejected return request.',
    )
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    cancel_reviewed_at = models.DateTimeField(null=True, blank=True)
    cancel_reviewed_by = models.CharField(max_length=20, blank=True, default='')

    #todo temp.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6,
        null=True, blank=True,
        help_text="Customer location latitude"
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6,
        null=True, blank=True,
        help_text="Customer location longitude"
    )

    def __str__(self):
        shop = self.vendor.shop_name if self.vendor_id and self.vendor else ''
        if shop:
            return f'{shop} · {self.id}'
        return str(self.id)

    def assign_vendor_from_items(self):
        if self.vendor_id:
            return
        item = self.orders_set.select_related('product_option__product__vendor').first()
        if item is None:
            return
        vendor = getattr(getattr(item.product_option, 'product', None), 'vendor', None)
        if vendor is not None:
            self.vendor = vendor
            self.save(update_fields=['vendor'])

    def line_statuses(self, items=None):
        if items is None:
            return {(status or '').upper() for status in self.orders_set.values_list('status', flat=True)}
        return {(item.status or '').upper() for item in items}

    def cancel_request_payload(self, items=None):
        statuses = self.line_statuses(items)
        request_status = (self.cancel_request_status or '').strip().lower()
        in_transit = bool(statuses & {'OUT_FOR_DELIVERY', 'SHIPPED'})
        can_return = bool(statuses) and (
            statuses <= {'ORDERED'} or statuses <= {'DELIVERED'}
        )
        return {
            'cancel_request_status': request_status,
            'can_request_cancel': can_return and request_status != 'pending',
            'cancel_request_pending': request_status == 'pending' and not in_transit,
        }


class OrderedProduct(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(
        'Vendor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ordered_products',
        help_text='Shop this ordered product belongs to.',
    )
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="orders_set")
    product_option = models.ForeignKey(ProductOption, on_delete=models.CASCADE, related_name="order_options_set")
    product_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    tx_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    delivery_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    quantity = models.IntegerField(default=1)
    choices = [
        ('ORDERED', 'ORDERED'),
        ('OUT_FOR_DELIVERY', 'OUT_FOR_DELIVERY'),
        ('DELIVERED', 'DELIVERED'),
        ('CANCELLED', 'CANCELLED'),
    ]
    rating = models.IntegerField(default=0)
    status = models.CharField(choices=choices, default='ORDERED', max_length=100)
    handled_by = models.ForeignKey(
        'DeliveryPartner',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='handled_items',
        help_text='Delivery boy who last changed this order status.',
    )
    handled_by_name = models.CharField(max_length=100, blank=True, default='')
    handled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.vendor_id is None:
            product = getattr(self.product_option, 'product', None)
            vendor = getattr(product, 'vendor', None)
            if vendor is not None:
                self.vendor = vendor
        super().save(*args, **kwargs)
        order = self.order
        if order is not None and order.vendor_id is None and self.vendor_id:
            order.vendor_id = self.vendor_id
            order.save(update_fields=['vendor'])


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications_set")
    title = models.CharField(max_length=225)
    body = models.TextField(max_length=1000)
    seen = models.BooleanField(default=False)
    image = models.ImageField(upload_to="notifications/", blank=True)
    product_option = models.ForeignKey(
        ProductOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class ContactInfo(models.Model):
    phone_number = models.CharField(max_length=15)

    def __str__(self):
        return self.phone_number



class InformMe(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='inform_me_requests'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='inform_me_requests'
    )
    product_option = models.ForeignKey(
        ProductOption,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='inform_me_requests'
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    offer_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Inform Me Request"
        verbose_name_plural = "Inform Me Requests"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} → {self.product.title}"


class ProductSuggestion(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewed', 'Reviewed'),
        ('added', 'Added to catalog'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='product_suggestions',
    )
    product_name = models.CharField(max_length=255)
    search_query = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Product Suggestion'
        verbose_name_plural = 'Product Suggestions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.email} → {self.product_name}'


class AppVersion(models.Model):
    PLATFORM_CHOICES = [
        ('android', 'Android'),
        ('ios', 'iOS'),
    ]

    platform = models.CharField(
        max_length=10,
        choices=PLATFORM_CHOICES,
        help_text="Select platform (Android or iOS)"
    )
    version_name = models.CharField(
        max_length=20,
        help_text="Version number (e.g., 2.0.0, 3.1.5)"
    )
    version_code = models.IntegerField(
        help_text="Build number (e.g., 1, 2, 3...)"
    )
    min_supported_version = models.CharField(
        max_length=20,
        help_text="Minimum version required (users below this will be forced to update)"
    )
    min_supported_code = models.IntegerField(
        help_text="Minimum build number required"
    )
    is_force_update = models.BooleanField(
        default=False,
        help_text="Force all users to update (regardless of minimum version)"
    )
    update_message = models.TextField(
        blank=True,
        help_text="Custom message shown to users",
        default="A new version is available with exciting new features!"
    )
    release_notes = models.TextField(
        blank=True,
        help_text="What's new in this version (shown in update dialog)"
    )
    store_url = models.URLField(
        help_text="App store download URL"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Only active versions will be used for update checks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['platform', 'version_name']
        ordering = ['-created_at']
        verbose_name = "App Version"
        verbose_name_plural = "App Versions"

    def __str__(self):
        return f"{self.get_platform_display()} v{self.version_name} ({'Active' if self.is_active else 'Inactive'})"

    def save(self, *args, **kwargs):
        # Set default store URLs if not provided
        if not self.store_url:
            if self.platform == 'android':
                self.store_url = 'https://play.google.com/store/apps/details?id=com.chaitanya.clickwell'
            elif self.platform == 'ios':
                self.store_url = 'https://apps.apple.com/in/app/clickwell-grocery-delivery/id6741314210'

        # Set default release notes if not provided
        if not self.release_notes:
            self.release_notes = f"🎉 What's New in ClickWell v{self.version_name}:\n\n• Bug fixes and improvements\n• Enhanced performance\n• Better user experience"

        super().save(*args, **kwargs)


class DeliveryPartner(models.Model):
    """Delivery personnel account — created by a shop or Django admin."""

    vendor = models.ForeignKey(
        'Vendor',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='delivery_partners',
        help_text='Shop that created this delivery boy account.',
    )
    login_id = models.CharField(max_length=50, unique=True, help_text='ID used to sign in on the delivery app')
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, blank=True, default='')
    password = models.CharField(max_length=5000)
    is_active = models.BooleanField(default=True)
    is_logged_in = models.BooleanField(
        default=False,
        help_text='True while signed in on a device. Cleared only via admin force logout.',
    )
    auth_token = models.CharField(max_length=128, blank=True, null=True, unique=True)
    logged_in_at = models.DateTimeField(null=True, blank=True)
    device_info = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Delivery partner'
        verbose_name_plural = 'Delivery partners'
        ordering = ['login_id']

    def __str__(self):
        return f'{self.login_id} — {self.name}'

    def force_logout(self):
        self.is_logged_in = False
        self.auth_token = None
        self.save(update_fields=['is_logged_in', 'auth_token', 'updated_at'])


class Plan(models.Model):
    """Vendor subscription plan, such as Basic, Standard, or Premium."""

    DURATION_DAYS = 'days'
    DURATION_MONTHS = 'months'
    DURATION_YEARS = 'years'
    DURATION_UNIT_CHOICES = [
        (DURATION_DAYS, 'Days'),
        (DURATION_MONTHS, 'Months'),
        (DURATION_YEARS, 'Years'),
    ]
    DURATION_UNIT_DAYS = {
        DURATION_DAYS: 1,
        DURATION_MONTHS: 30,
        DURATION_YEARS: 365,
    }

    slug = models.SlugField(
        max_length=40,
        unique=True,
        help_text='Short key, such as basic, standard, or premium.',
    )
    name = models.CharField(max_length=80, help_text='Name shown in admin, such as Basic.')
    duration_value = models.PositiveIntegerField(
        default=30,
        help_text='Number shown with the unit, such as 30 days, 1 month, or 1 year.',
    )
    duration_unit = models.CharField(
        max_length=10,
        choices=DURATION_UNIT_CHOICES,
        default=DURATION_DAYS,
        help_text='Choose Days, Months, or Years. 30 days or 1 month, 365 days or 1 year.',
    )
    duration_days = models.PositiveIntegerField(
        default=30,
        help_text='Saved as days from the value and unit above.',
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Plan price shown in admin.',
    )
    description = models.TextField(blank=True, default='')
    image = models.ImageField(
        upload_to='plans/',
        blank=True,
        help_text='Logo or image shown on the vendor plan card.',
    )
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    razorpay_plan_id = models.CharField(
        max_length=40,
        blank=True,
        default='',
        help_text='Razorpay plan id used for monthly or yearly autopay.',
    )

    class Meta:
        ordering = ['position', 'name']
        verbose_name = 'Plan'
        verbose_name_plural = 'Plans'

    def __str__(self):
        return self.name

    def duration_in_days(self):
        multiplier = self.DURATION_UNIT_DAYS.get(self.duration_unit, 1)
        return max(1, int(self.duration_value or 0) * multiplier)

    def duration_label(self):
        value = int(self.duration_value or 0)
        if self.duration_unit == self.DURATION_MONTHS:
            return '1 month' if value == 1 else f'{value} months'
        if self.duration_unit == self.DURATION_YEARS:
            return '1 year' if value == 1 else f'{value} years'
        return '1 day' if value == 1 else f'{value} days'

    def autopay_period(self):
        value = int(self.duration_value or 0)
        unit = self.duration_unit
        if unit == self.DURATION_MONTHS and value == 1:
            return 'monthly'
        if unit == self.DURATION_DAYS and value == 30:
            return 'monthly'
        if unit == self.DURATION_YEARS and value == 1:
            return 'yearly'
        if unit == self.DURATION_MONTHS and value == 12:
            return 'yearly'
        if unit == self.DURATION_DAYS and value == 365:
            return 'yearly'
        return ''

    def is_autopay(self):
        return bool(self.autopay_period())

    def formatted_price(self):
        value = self.price or Decimal('0')
        quantized = value.quantize(Decimal('0.01'))
        if quantized == quantized.to_integral_value():
            return f'{int(quantized):,}'
        return f'{quantized:,.2f}'

    def image_url(self, request=None):
        if not self.image:
            return ''
        url = self.image.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url

    def clean(self):
        value = int(self.duration_value or 0)
        if value < 1:
            raise ValidationError({'duration_value': 'Enter at least 1.'})
        if self.duration_unit == self.DURATION_MONTHS and value > 12:
            raise ValidationError({
                'duration_value': 'Months cannot be more than 12. Use 1 year or more instead.',
            })

    def save(self, *args, **kwargs):
        self.duration_days = self.duration_in_days()
        super().save(*args, **kwargs)


class Vendor(models.Model):
    """Shop account for the catalog editor. Credentials are set in Django admin."""

    login_id = models.CharField(max_length=50, unique=True, help_text='ID the vendor types to open the dashboard.')
    password = models.CharField(max_length=5000)
    shop_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=15, help_text='Main phone number.')
    alternate_phone = models.CharField(max_length=15, blank=True, default='')
    address = models.TextField(blank=True, default='', help_text='Shop address.')
    location = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Shop location, such as a market or landmark.',
    )
    city = models.CharField(max_length=100, blank=True, default='', help_text='City name.')
    state = models.CharField(max_length=100, blank=True, default='', help_text='State name.')
    gstin = models.CharField(max_length=15, blank=True, default='', help_text='GSTIN, 15 characters.')
    license_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text='Shop or trade license number.',
    )
    shop_image = models.ImageField(
        upload_to='shops/',
        blank=True,
        help_text='Photo of the shop shown on the store list.',
    )
    is_active = models.BooleanField(default=True)
    plan = models.ForeignKey(
        'Plan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendors',
        help_text='Subscription plan for this shop.',
    )
    quick_enabled = models.BooleanField(default=False)
    quick_min_minutes = models.PositiveIntegerField(default=10)
    quick_max_minutes = models.PositiveIntegerField(default=30)
    slots = models.JSONField(blank=True, default=list)
    open_time = models.TimeField(default=time(9, 0))
    close_time = models.TimeField(default=time(22, 0))
    closed_days = models.JSONField(blank=True, default=list)
    closed_dates = models.JSONField(blank=True, default=list)
    min_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=100,
        help_text='Orders under this amount pay the delivery charge.',
    )
    delivery_charge_under = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=15,
        help_text='Delivery charge when the order is under the minimum.',
    )
    delivery_pincodes = models.JSONField(
        blank=True,
        default=list,
        help_text='Pincodes this shop delivers to.',
    )
    auth_token = models.CharField(max_length=128, blank=True, null=True, unique=True)
    logged_in_at = models.DateTimeField(null=True, blank=True)
    session_expires_at = models.DateField(
        null=True,
        blank=True,
        help_text='Vendor app session stays valid through this date. Leave blank for no expiry. You can change this anytime.',
    )
    razorpay_subscription_id = models.CharField(
        max_length=40,
        blank=True,
        default='',
        help_text='Razorpay subscription used for monthly or yearly autopay.',
    )
    razorpay_paid_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of autopay charges already applied to this shop.',
    )
    autopay_enabled = models.BooleanField(
        default=False,
        help_text='Money is deducted automatically for a monthly or yearly plan.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['shop_name', 'login_id']

    def __str__(self):
        return f'{self.shop_name} ({self.login_id})'

    def session_is_expired(self):
        if self.session_expires_at is None:
            return False
        from django.utils import timezone
        return timezone.localdate() > self.session_expires_at

    def expire_session(self):
        if not self.auth_token:
            return
        self.auth_token = None
        self.save(update_fields=['auth_token', 'updated_at'])

    def apply_plan(self, plan):
        from django.utils import timezone
        self.plan = plan
        today = timezone.localdate()
        start = today
        if self.session_expires_at and self.session_expires_at > today:
            start = self.session_expires_at
        self.session_expires_at = start + timedelta(days=plan.duration_in_days())
        self.save(update_fields=['plan', 'session_expires_at', 'updated_at'])

    def profile(self, request=None):
        image = ''
        if self.shop_image:
            image = self.shop_image.url
            if request is not None:
                image = request.build_absolute_uri(image)
        return {
            'login_id': self.login_id,
            'shop_name': self.shop_name,
            'owner_name': self.owner_name,
            'phone': self.phone,
            'alternate_phone': self.alternate_phone,
            'address': self.address,
            'location': self.location,
            'city': self.city,
            'state': self.state,
            'gstin': self.gstin,
            'license_number': self.license_number,
            'shop_image': image,
            'session_expires_at': self.session_expires_at.isoformat() if self.session_expires_at else '',
            'plan': self.plan.name if self.plan_id and self.plan else '',
            'plan_slug': self.plan.slug if self.plan_id and self.plan else '',
            'autopay_enabled': bool(self.autopay_enabled),
            'autopay_period': self.plan.autopay_period() if self.plan_id and self.plan else '',
        }


class PopularCity(models.Model):
    """City shown on the app location screen, with the vendors that serve it."""

    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True, default='')
    pincode = models.CharField(max_length=6, help_text='6-digit pincode for this city.')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, default=0)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, default=0)
    position = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    vendors = models.ManyToManyField(Vendor, blank=True, related_name='popular_cities')

    class Meta:
        ordering = ['position', 'city']
        verbose_name = 'Popular city'
        verbose_name_plural = 'Popular cities'

    def __str__(self):
        label = f'{self.city}, {self.state}'.strip().rstrip(',')
        return label or self.city


class DeliveryTiming(models.Model):
    """Delivery windows for a shop, edited from the catalog dashboard or admin."""

    vendor = models.OneToOneField(
        'Vendor',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='delivery_timing_row',
        help_text='Shop these delivery windows belong to.',
    )
    quick_enabled = models.BooleanField(default=False)
    quick_min_minutes = models.PositiveIntegerField(default=10)
    quick_max_minutes = models.PositiveIntegerField(default=30)
    slots = models.JSONField(blank=True, default=list)
    open_time = models.TimeField(default=time(9, 0))
    close_time = models.TimeField(default=time(22, 0))
    closed_days = models.JSONField(blank=True, default=list)
    closed_dates = models.JSONField(blank=True, default=list)

    class Meta:
        verbose_name = 'Delivery timing'
        verbose_name_plural = 'Delivery timing'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        vendor = self.vendor
        if vendor is not None:
            vendor.quick_enabled = self.quick_enabled
            vendor.quick_min_minutes = self.quick_min_minutes
            vendor.quick_max_minutes = self.quick_max_minutes
            vendor.slots = self.slots
            vendor.open_time = self.open_time
            vendor.close_time = self.close_time
            vendor.closed_days = self.closed_days
            vendor.closed_dates = self.closed_dates
            vendor.save(update_fields=[
                'quick_enabled', 'quick_min_minutes', 'quick_max_minutes',
                'slots', 'open_time', 'close_time', 'closed_days', 'closed_dates',
                'updated_at',
            ])

    def __str__(self):
        if self.vendor_id and self.vendor:
            return f'Delivery timing — {self.vendor.shop_name}'
        return 'Delivery timing (shared)'