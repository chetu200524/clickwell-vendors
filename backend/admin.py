from django import forms
from django.contrib import admin
from django.contrib.admin import register
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, User as AUser
from django.db import models
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
import json

from django.utils.html import format_html, format_html_join, json_script

from backend.models import User, Otp, Token, PasswordResetToken, Category, Slide, Product, ProductOption, ProductImage, \
    PageItem, PageItemOption, Order, OrderedProduct, Notification, ContactInfo, InformMe, ProductSuggestion, AppVersion, UserAddress, \
    DeliveryPartner, DeliveryTiming, Vendor, Plan, PopularCity, known_subcategory_spellings, resolve_subcategory_names
from backend.utils import send_user_notification

from .models import User
from .decorators import password_protected_view

admin.site.unregister(Group)
admin.site.unregister(AUser)

admin.site.site_header = "ClickWell Quick Commerce"
admin.site.site_title = "ClickWell QC Admin"
admin.site.index_title = "Operations dashboard — catalog, orders & customers"


class DeliveryPartnerAdminForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label='Password',
        help_text='Required when creating a partner. Leave blank on edit to keep the current password.',
    )

    class Meta:
        model = DeliveryPartner
        fields = ['vendor', 'login_id', 'name', 'phone', 'is_active']

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get('new_password'):
            raise forms.ValidationError({'new_password': 'Password is required for a new delivery partner.'})
        return cleaned


@register(DeliveryPartner)
class DeliveryPartnerAdmin(admin.ModelAdmin):
    form = DeliveryPartnerAdminForm
    list_display = ['login_id', 'name', 'vendor', 'phone', 'is_active', 'is_logged_in', 'logged_in_at']
    list_filter = ['is_active', 'is_logged_in', 'vendor']
    search_fields = ['login_id', 'name', 'phone', 'vendor__shop_name']
    readonly_fields = [
        'auth_token', 'is_logged_in', 'logged_in_at', 'device_info',
        'session_actions', 'created_at', 'updated_at',
    ]
    actions = ['force_logout_partners']

    fieldsets = (
        ('Account', {
            'fields': ('vendor', 'login_id', 'name', 'phone', 'new_password', 'is_active'),
        }),
        ('Session (read-only)', {
            'fields': (
                'is_logged_in', 'auth_token', 'logged_in_at', 'device_info',
                'session_actions', 'created_at', 'updated_at',
            ),
            'description': (
                'Delivery partners cannot logout from the app. '
                'Use Force logout below (or the list-page Action) to end their session.'
            ),
        }),
    )

    def session_actions(self, obj):
        if not obj.pk:
            return 'Save the partner first.'
        if obj.is_logged_in or obj.auth_token:
            url = reverse('admin:backend_deliverypartner_force_logout', args=[obj.pk])
            return format_html(
                '<a class="button" style="background:#ba2121;color:#fff;padding:8px 14px;" '
                'href="{}">Force logout</a>',
                url,
            )
        return 'Not logged in — no active session.'

    session_actions.short_description = 'Force logout'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/force-logout/',
                self.admin_site.admin_view(self.force_logout_view),
                name='backend_deliverypartner_force_logout',
            ),
        ]
        return custom_urls + urls

    def force_logout_view(self, request, object_id):
        partner = get_object_or_404(DeliveryPartner, pk=object_id)
        if partner.is_logged_in or partner.auth_token:
            partner.force_logout()
            self.message_user(
                request,
                f'Force logged out {partner.login_id} ({partner.name}).',
            )
        else:
            self.message_user(request, f'{partner.login_id} has no active session.')
        return HttpResponseRedirect(
            reverse('admin:backend_deliverypartner_change', args=[object_id])
        )

    def save_model(self, request, obj, form, change):
        new_password = form.cleaned_data.get('new_password')
        if new_password:
            obj.password = make_password(new_password)
        super().save_model(request, obj, form, change)

    @admin.action(description='Force logout selected delivery partners')
    def force_logout_partners(self, request, queryset):
        count = 0
        for partner in queryset:
            if partner.is_logged_in or partner.auth_token:
                partner.force_logout()
                count += 1
        self.message_user(request, f'Force logged out {count} delivery partner(s).')


@register(UserAddress)
class UserAddressAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'label', 'name', 'city', 'pincode', 'is_default', 'updated_at']
    list_filter = ['is_default', 'label', 'state']
    search_fields = ['user__email', 'name', 'contact_no', 'address', 'house', 'locality', 'city']
    fields = [
        'user', 'label', 'name', 'contact_no', 'house', 'locality', 'landmark',
        'city', 'state', 'district', 'pincode', 'address', 'latitude', 'longitude', 'is_default',
    ]


@register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'email', 'phone', 'fullname', 'address', 'pincode', 'created_at']
    fieldsets = (
        ('User info', {
            'fields': ('email', 'phone', 'fullname', 'password',)
        }),
        ('Address info', {
            'fields': ('name', 'address', 'contact_no', 'pincode', 'district', 'state',)
        }),
    )
    readonly_fields = ['password', 'email','phone','fullname','name','address','pincode','district', 'state','contact_no']
    search_fields = ['id','email','phone','fullname','address','pincode']
    search_help_text =  "Search by id,email,phone,fullname,address,pincode"

    # @password_protected_view('userAdmin@1612') #password for userAdmin
    # def changelist_view(self, request, extra_context=None):
    #     return super().changelist_view(request, extra_context)
    #
    # @password_protected_view('userAdmin@1612') ##password for userAdmin
    # def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
    #     return super().changeform_view(request, object_id, form_url, extra_context)


@register(Otp)
class OtpAdmin(admin.ModelAdmin):
    list_display = ['phone', 'otp', 'validity', 'verified']

    def has_add_permission(self, request):
        return False

  #  @password_protected_view('otp_admin@1612') #password for OtpAdmin
   # def changelist_view(self, request, extra_context=None):
    #    return super().changelist_view(request, extra_context)

   # @password_protected_view('otp_admin@1612') #password for OtpAdmin
    #def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
     #   return super().changeform_view(request, object_id, form_url, extra_context)

@register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ['token', 'fcmtoken', 'user', 'created_at']

    def has_add_permission(self, request):
        return False


@register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ['token', 'user', 'validity']

    def has_add_permission(self, request):
        return False


@register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'position', 'image']

    # @password_protected_view('hesoyam@24') #password for CategoryAdmin
    # def changelist_view(self, request, extra_context=None):
    #     return super().changelist_view(request, extra_context)
    #
    # @password_protected_view('hesoyam@24') #password for CategoryAdmin
    # def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
    #     return super().changeform_view(request, object_id, form_url, extra_context)


@register(Slide)
class SlideAdmin(admin.ModelAdmin):
    list_display = ['position', 'vendor', 'category', 'image']
    list_filter = ['vendor', 'category']
    ordering = ['category', 'position']

    # @password_protected_view('promotion_admin@24') #password for SlideAdmin
    # def changelist_view(self, request, extra_context=None):
    #     return super().changelist_view(request, extra_context)
    #
    # @password_protected_view('promotion_admin@24') #password for SlideAdmin
    # def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
    #     return super().changeform_view(request, object_id, form_url, extra_context)




class ProductOptionInline(admin.TabularInline):
    model = ProductOption
    fields = ['option', 'quantity', 'price', 'offer_price']
    extra = 1
    show_change_link = True


class SubcategoryChipsWidget(forms.Widget):
    """Chip editor for several subcategory names on one product."""

    def __init__(self, suggestions, attrs=None):
        self.suggestions = list(suggestions)
        super().__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        names = value if isinstance(value, list) else []
        attrs = attrs or {}
        field_id = attrs.get('id') or f'id_{name}'
        options = format_html_join(
            '',
            '<option value="{}"></option>',
            ((suggestion,) for suggestion in self.suggestions),
        )
        return format_html(
            '<div data-subcat-editor data-field-id="{}">'
            '<div data-chips></div>'
            '<div style="display:flex;gap:8px;align-items:center;margin-top:8px;">'
            '<input type="text" list="product-subcategory-options" autocomplete="off" '
            'placeholder="Add a subcategory" style="flex:1;">'
            '<button type="button" data-add class="button">Add</button>'
            '</div>'
            '<input type="hidden" name="{}" value="{}">'
            '<datalist id="product-subcategory-options">{}</datalist>'
            '{}'
            '{}'
            '<script>'
            '(function(){{'
            'var root=document.querySelector(\'[data-subcat-editor][data-field-id="{id}"]\');'
            'if(!root||root.dataset.ready)return;'
            'root.dataset.ready="1";'
            'var hidden=root.querySelector(\'input[type=hidden]\');'
            'var text=root.querySelector(\'input[type=text]\');'
            'var chips=root.querySelector(\'[data-chips]\');'
            'var valueNode=document.getElementById("{id}-value");'
            'var names=[];'
            'try{{names=JSON.parse(valueNode.textContent);}}catch(e){{names=[];}}'
            'if(!Array.isArray(names))names=[];'
            'function sync(){{'
            'hidden.value=JSON.stringify(names);'
            'chips.innerHTML="";'
            'names.forEach(function(name,index){{'
            'var chip=document.createElement("span");'
            'chip.style.cssText="display:inline-flex;align-items:center;gap:6px;margin:0 8px 8px 0;padding:4px 10px;border-radius:999px;background:#e8eaf6;color:#283593;";'
            'chip.appendChild(document.createTextNode(name));'
            'var btn=document.createElement("button");'
            'btn.type="button";btn.textContent="×";'
            'btn.style.cssText="border:0;background:transparent;cursor:pointer;font-size:16px;color:#283593;";'
            'btn.addEventListener("click",function(){{names.splice(index,1);sync();}});'
            'chip.appendChild(btn);chips.appendChild(chip);'
            '}});'
            '}}'
            'function addCurrent(){{'
            'text.value.split(",").forEach(function(part){{'
            'var name=part.trim();'
            'if(!name)return;'
            'var exists=names.some(function(item){{return item.toLowerCase()===name.toLowerCase();}});'
            'if(!exists)names.push(name);'
            '}});'
            'text.value="";sync();'
            '}}'
            'root.querySelector("[data-add]").addEventListener("click",addCurrent);'
            'text.addEventListener("keydown",function(event){{'
            'if(event.key==="Enter"){{event.preventDefault();addCurrent();}}'
            '}});'
            'sync();'
            '}})();'
            '</script>'
            '</div>',
            field_id,
            name,
            json.dumps(names),
            options,
            json_script(names, f'{field_id}-value'),
            json_script(self.suggestions, f'{field_id}-suggestions'),
            id=field_id,
        )


class SubcategoryListField(forms.Field):
    def __init__(self, suggestions, **kwargs):
        self.suggestions = suggestions
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)
        self.widget = SubcategoryChipsWidget(suggestions)

    def to_python(self, value):
        if value in (None, ''):
            return []
        if isinstance(value, list):
            raw = value
        else:
            try:
                raw = json.loads(value)
            except (TypeError, ValueError):
                raw = [part.strip() for part in str(value).split(',') if part.strip()]
        return resolve_subcategory_names(raw)


class ProductAdminForm(forms.ModelForm):
    subcategory_names = SubcategoryListField(suggestions=[])

    class Meta:
        model = Product
        exclude = ['subcategory', 'subcategories']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        suggestions = sorted(known_subcategory_spellings().values(), key=str.casefold)
        self.fields['subcategory_names'] = SubcategoryListField(required=False, suggestions=suggestions)
        stored = self.instance.subcategories if isinstance(getattr(self.instance, 'subcategories', None), list) else []
        if not stored and getattr(self.instance, 'subcategory', ''):
            stored = [part.strip() for part in self.instance.subcategory.split(',') if part.strip()]
        self.fields['subcategory_names'].initial = stored
        self.fields['subcategory_names'].label = 'Subcategories'
        self.fields['subcategory_names'].help_text = (
            'Add several chips, such as Chips, Lays, and Potato chips. '
            'Type a saved name or a new one, then Add.'
        )

    def save(self, commit=True):
        product = super().save(commit=False)
        names = self.cleaned_data.get('subcategory_names') or []
        product.subcategories = names
        product.subcategory = ', '.join(names)
        if commit:
            product.save()
            self.save_m2m()
        return product


@register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    inlines = [ProductOptionInline]
    list_display = [
        'id', 'vendor', 'category', 'subcategory', 'barcode', 'title', 'price', 'offer_price',
        'delivery_charge', 'cod', 'created_at', 'updated_at',
    ]
    list_select_related = ['vendor', 'category']
    fields = [
        'vendor', 'category', 'subcategory_names', 'barcode', 'title', 'description', 'price', 'offer_price',
        'delivery_charge', 'cod', 'star_1', 'star_2', 'star_3', 'star_4', 'star_5',
    ]
    readonly_fields = ['star_1', 'star_2', 'star_3', 'star_4', 'star_5']
    list_filter = ['vendor', 'cod', 'category', 'subcategory']
    search_fields = ['id', 'title', 'subcategory', 'barcode', 'vendor__shop_name', 'vendor__login_id', 'vendor__owner_name']
    search_help_text = "Search by Id, title, subcategory, barcode, or vendor"


class ProductImageInline(admin.TabularInline):
    list = ['image', 'position']
    model = ProductImage
    extra = 0
    min_num = 1


@register(ProductOption)
class ProductOptionAdmin(admin.ModelAdmin):
    inlines = [ProductImageInline]
    list_display = ['id', 'product', 'option', 'quantity', 'price', 'offer_price']
    search_fields = ['product__title','option','quantity']
    search_help_text = 'Search by, Product, Option, Quantity'


class PageItemOptionInline(admin.TabularInline):
    model = PageItemOption
    extra = 0
    autocomplete_fields = ['product_option']


@register(PageItem)
class PageItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'vendor', 'title', 'position', 'image', 'category', 'viewtype']
    inlines = [PageItemOptionInline]
    list_filter = ['vendor', 'viewtype', 'category']
    search_fields = ['title', 'vendor__shop_name', 'vendor__login_id']
    search_help_text = "Search by title"

    # @password_protected_view('pageitem@24') #password for pageitem
    # def changelist_view(self, request, extra_context=None):
    #     return super().changelist_view(request, extra_context)
    #
    # @password_protected_view('pageitem@24') ##password for pageitem
    # def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
    #     return super().changeform_view(request, object_id, form_url, extra_context)
    #

@register(OrderedProduct)
class OrderedProductAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'vendor', 'order', 'product_option', 'product_price', 'tx_price',
        'delivery_price', 'quantity', 'status', 'handled_by_name', 'rating',
        'created_at', 'updated_at',
    ]
    readonly_fields = [
        'vendor', 'order', 'product_option', 'product_price', 'tx_price',
        'delivery_price', 'quantity', 'rating',
    ]
    search_fields = ['id', 'vendor__shop_name', 'vendor__login_id', 'order__id']
    search_help_text = "Search by Id, vendor, or order"
    list_filter = ['vendor', 'status']
    list_select_related = ['vendor', 'order', 'product_option']
    ordering = ['-created_at']

    def save_model(self, request, ordered_product, form, change):
        super(OrderedProductAdmin, self).save_model( request, ordered_product, form, change)
        user = ordered_product.order.user
        title = "ORDER "+ordered_product.status
        body = "Your "+ordered_product.product_option.__str__()+" has been "+ordered_product.status+"."
        image = ordered_product.product_option.images_set.first().image
        print("ORDER STATUS: "+title)
        send_user_notification(
            user, title, body, image,
            product_option=ordered_product.product_option,
        )

    def has_add_permission(self, request):
        return False



class OrderedProductInline(admin.TabularInline):
    model = OrderedProduct
    list = ['id', 'vendor', 'product_option', 'product_price', 'tx_price', 'delivery_price', 'quantity', 'status']
    readonly_fields = [
        'vendor', 'product_option', 'product_price', 'tx_price',
        'delivery_price', 'quantity', 'status', 'rating',
    ]
    fields = [
        'vendor', 'product_option', 'product_price', 'tx_price',
        'delivery_price', 'quantity', 'status', 'rating',
    ]

    show_change_link = True

    extra = 0

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = [OrderedProductInline]
    list_display = [
        'id', 'vendor', 'seen', 'user', 'tx_amount', 'payment_mode', 'address',
        'tx_id', 'tx_status', 'tx_time', 'tx_msg', 'from_cart', 'created_at', 'updated_at',
    ]
    list_filter = ['vendor', 'payment_mode', 'tx_status', 'from_cart']
    list_select_related = ['vendor', 'user']
    ordering = ['-created_at']
    readonly_fields = ['vendor', 'user', 'tx_amount', 'payment_mode', 'tx_id', 'tx_time', 'tx_msg', 'from_cart']
    search_fields = ['id', 'user__email', 'address', 'tx_id', 'vendor__shop_name', 'vendor__login_id']
    search_help_text = "Search by Id, vendor, user, address, tx_id"

    def has_add_permission(self, request):
        return False


@register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'body', 'image', 'seen', 'created_at']

    @password_protected_view('notificationadmin') #password for pageitem
    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, extra_context)

    @password_protected_view('notificationadmin') ##password for pageitem
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)

@admin.register(ContactInfo)
class ContactInfoAdmin(admin.ModelAdmin):
    list_display = ['id', 'phone_number']
    fields = ['phone_number']
    search_fields = ['phone_number']
    search_help_text = "Search by phone number"

    def has_add_permission(self, request):
        # Allow only one ContactInfo entry
        if ContactInfo.objects.exists():
            return False
        return super().has_add_permission(request)


@admin.register(InformMe)
class InformMeAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'product', 'product_option',
        'price', 'offer_price', 'created_at'
    )
    list_filter = ('created_at', 'product')
    search_fields = ('user__email', 'product__title')
    readonly_fields = ('price', 'offer_price', 'created_at')


@admin.register(ProductSuggestion)
class ProductSuggestionAdmin(admin.ModelAdmin):
    list_display = (
        'product_name', 'user', 'search_query', 'status', 'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = (
        'product_name', 'search_query', 'notes',
        'user__email', 'user__fullname', 'user__name',
    )
    search_help_text = 'Search by product name, search query, user email, or notes'
    readonly_fields = ('user', 'product_name', 'search_query', 'notes', 'created_at')
    ordering = ('-created_at',)
    list_editable = ('status',)

    def has_add_permission(self, request):
        return False


@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display = [
        'platform',
        'version_name',
        'version_code',
        'is_active',
        'is_force_update',
        'created_at'
    ]
    list_filter = ['platform', 'is_force_update', 'is_active', 'created_at']
    search_fields = ['version_name', 'update_message', 'release_notes']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Version Information', {
            'fields': ('platform', 'version_name', 'version_code', 'store_url'),
            'description': 'Basic version details and store URL'
        }),
        ('Update Policy', {
            'fields': ('min_supported_version', 'min_supported_code', 'is_force_update', 'is_active'),
            'description': 'Control update behavior and requirements'
        }),
        ('User Messages', {
            'fields': ('update_message', 'release_notes'),
            'description': 'Messages shown to users in the update dialog'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        # Deactivate other versions for the same platform when a new active version is saved
        if obj.is_active:
            AppVersion.objects.filter(
                platform=obj.platform,
                is_active=True
            ).exclude(pk=obj.pk).update(is_active=False)
        super().save_model(request, obj, form, change)

    # Add custom actions
    actions = ['make_active', 'make_inactive', 'make_force_update', 'remove_force_update']

    def make_active(self, request, queryset):
        for obj in queryset:
            # Deactivate other versions for the same platform
            AppVersion.objects.filter(platform=obj.platform, is_active=True).update(is_active=False)
            obj.is_active = True
            obj.save()
        self.message_user(request, f"{queryset.count()} version(s) activated.")

    make_active.short_description = "Activate selected versions"

    def make_inactive(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} version(s) deactivated.")

    make_inactive.short_description = "Deactivate selected versions"

    def make_force_update(self, request, queryset):
        queryset.update(is_force_update=True)
        self.message_user(request, f"{queryset.count()} version(s) set to force update.")

    make_force_update.short_description = "Set as force update"

    def remove_force_update(self, request, queryset):
        queryset.update(is_force_update=False)
        self.message_user(request, f"{queryset.count()} version(s) set to optional update.")

    remove_force_update.short_description = "Remove force update"


class VendorAdminForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label='Password',
        help_text='Required for a new vendor. Leave blank when editing to keep the current password.',
    )
    popular_city = forms.ModelChoiceField(
        queryset=PopularCity.objects.none(),
        required=True,
        label='City',
        empty_label='Select a city',
        help_text='Choose a popular city. Add cities under Popular cities.',
    )

    class Meta:
        model = Vendor
        fields = [
            'login_id',
            'shop_name',
            'owner_name',
            'phone',
            'alternate_phone',
            'address',
            'location',
            'gstin',
            'license_number',
            'shop_image',
            'is_active',
            'plan',
            'session_expires_at',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = None
        if getattr(self.instance, 'pk', None):
            current = self.instance.popular_cities.order_by('position', 'id').first()
            if current is None and (self.instance.city or '').strip():
                current = PopularCity.objects.filter(
                    city__iexact=self.instance.city.strip(),
                ).order_by('-is_active', 'position', 'id').first()
        queryset = PopularCity.objects.filter(is_active=True)
        if current is not None and not queryset.filter(pk=current.pk).exists():
            queryset = PopularCity.objects.filter(pk=current.pk) | queryset
        self.fields['popular_city'].queryset = queryset.order_by('position', 'city')
        if current is not None:
            self.initial['popular_city'] = current.pk
        if 'plan' in self.fields:
            self.fields['plan'].required = False
            self.fields['plan'].empty_label = 'None'
            self.fields['plan'].queryset = Plan.objects.order_by('position', 'name')
            self.fields['plan'].help_text = ''

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not (cleaned.get('new_password') or '').strip():
            raise forms.ValidationError({'new_password': 'Set a password for this vendor.'})
        gstin = (cleaned.get('gstin') or '').strip().upper()
        cleaned['gstin'] = gstin
        if gstin and len(gstin) != 15:
            raise forms.ValidationError({'gstin': 'GSTIN must be 15 characters.'})
        return cleaned

    def save(self, commit=True):
        vendor = super().save(commit=False)
        city = self.cleaned_data.get('popular_city')
        vendor.city = city.city if city is not None else ''
        vendor.state = city.state if city is not None else ''
        if commit:
            vendor.save()
            self.save_m2m()
        return vendor


class PlanVendorInline(admin.TabularInline):
    model = Vendor
    fk_name = 'plan'
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ['shop_name', 'login_id', 'owner_name', 'phone', 'is_active', 'session_expires_at']
    readonly_fields = ['shop_name', 'login_id', 'owner_name', 'phone', 'is_active', 'session_expires_at']
    verbose_name = 'Vendor'
    verbose_name_plural = 'Vendors on this plan'

    def has_add_permission(self, request, obj=None):
        return False


class PlanAdminForm(forms.ModelForm):
    class Meta:
        model = Plan
        exclude = ['duration_days']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'duration_value' in self.fields:
            self.fields['duration_value'].help_text = (
                'For Months, enter 1 to 12 only. Use Years for a longer plan.'
            )
        if 'duration_unit' in self.fields:
            self.fields['duration_unit'].help_text = (
                'The vendor app shows this same duration: days, months, or years.'
            )


@register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = [
        'logo', 'name', 'slug', 'short_description', 'duration_value', 'duration_unit',
        'duration_shown', 'price', 'is_active', 'position', 'vendor_count',
    ]
    form = PlanAdminForm
    list_filter = ['is_active', 'duration_unit']
    search_fields = ['name', 'slug', 'description']
    ordering = ['position', 'name']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['duration_value', 'duration_unit', 'price', 'is_active', 'position']
    readonly_fields = ['duration_days']
    inlines = [PlanVendorInline]
    fieldsets = (
        (None, {
            'fields': (
                'name',
                'slug',
                'image',
                'description',
                'duration_value',
                'duration_unit',
                'duration_days',
                'price',
                'is_active',
                'position',
            ),
        }),
    )
    formfield_overrides = {
        models.TextField: {
            'widget': forms.Textarea(attrs={'rows': 4, 'cols': 80}),
        },
    }

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'description' and field is not None:
            field.help_text = 'Shown on the vendor Plans screen. Add or edit the text here.'
        if db_field.name == 'image' and field is not None:
            field.help_text = 'Logo or image shown on the vendor plan card.'
        return field

    def logo(self, obj):
        if not obj.image:
            return '—'
        return format_html(
            '<img src="{}" alt="" style="height:36px;width:36px;object-fit:contain;border-radius:8px;background:#f4f6fb;" />',
            obj.image.url,
        )

    logo.short_description = 'Logo'

    def short_description(self, obj):
        text = (obj.description or '').strip()
        if not text:
            return '—'
        return text if len(text) <= 72 else f'{text[:69]}…'

    short_description.short_description = 'Description'

    def duration_shown(self, obj):
        return obj.duration_label()

    duration_shown.short_description = 'Shows as'

    def save_model(self, request, obj, form, change):
        obj.full_clean()
        super().save_model(request, obj, form, change)

    def vendor_count(self, obj):
        return obj.vendors.count()

    vendor_count.short_description = 'Vendors'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('vendors')


@register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    form = VendorAdminForm
    list_display = [
        'login_id', 'shop_name', 'owner_name', 'city', 'state', 'phone',
        'gstin', 'is_active', 'vendor_plan', 'session_expires_at', 'session_status',
    ]
    search_fields = [
        'login_id', 'shop_name', 'owner_name', 'phone', 'gstin',
        'license_number', 'location', 'city', 'state', 'plan__name', 'plan__slug',
    ]
    list_filter = ['is_active', 'plan', 'session_expires_at']
    list_select_related = ['plan']
    readonly_fields = [
        'plan_details', 'autopay_enabled', 'razorpay_subscription_id',
        'logged_in_at', 'created_at', 'updated_at',
    ]

    fieldsets = (
        ('Login', {
            'fields': ('login_id', 'new_password', 'is_active', 'session_expires_at'),
        }),
        ('Plan', {
            'fields': ('plan', 'plan_details', 'autopay_enabled', 'razorpay_subscription_id'),
        }),
        ('Shop', {
            'fields': (
                'shop_name',
                'owner_name',
                'phone',
                'alternate_phone',
                'address',
                'location',
                'popular_city',
                'gstin',
                'license_number',
                'shop_image',
            ),
        }),
        ('Record', {
            'fields': ('logged_in_at', 'created_at', 'updated_at'),
        }),
    )

    def vendor_plan(self, obj):
        if not obj.plan_id or obj.plan is None:
            return 'None'
        return obj.plan.name

    vendor_plan.short_description = 'Plan'
    vendor_plan.admin_order_field = 'plan__name'

    def plan_details(self, obj):
        plan = obj.plan
        if plan is None:
            return 'None — the vendor app shows all plans, not only a current plan.'
        description = (plan.description or '').strip() or 'No description yet. Add it under Plans.'
        return format_html(
            '<div><strong>{}</strong> — ₹{} / {}</div><div style="margin-top:6px;white-space:pre-wrap;">{}</div>',
            plan.name,
            plan.formatted_price(),
            plan.duration_label(),
            description,
        )

    plan_details.short_description = 'Plan details'

    def session_status(self, obj):
        if obj.session_expires_at is None:
            return 'No expiry'
        if obj.session_is_expired():
            return 'Expired'
        return f'Until {obj.session_expires_at:%d %b %Y}'

    session_status.short_description = 'Session'

    def save_model(self, request, obj, form, change):
        password = (form.cleaned_data.get('new_password') or '').strip()
        if password:
            obj.password = make_password(password)
        obj.gstin = (obj.gstin or '').strip().upper()
        obj.location = (obj.location or '').strip()
        super().save_model(request, obj, form, change)
        if obj.session_is_expired():
            obj.expire_session()
        city = form.cleaned_data.get('popular_city')
        obj.popular_cities.clear()
        if city is not None:
            city.vendors.add(obj)


class PopularCityAdminForm(forms.ModelForm):
    class Meta:
        model = PopularCity
        fields = '__all__'

    def clean_pincode(self):
        pincode = (self.cleaned_data.get('pincode') or '').strip()
        if len(pincode) != 6 or not pincode.isdigit():
            raise forms.ValidationError('Enter a 6-digit pincode.')
        return pincode

    def clean(self):
        cleaned = super().clean()
        cleaned['city'] = (cleaned.get('city') or '').strip()
        cleaned['state'] = (cleaned.get('state') or '').strip()
        if not cleaned['city']:
            raise forms.ValidationError({'city': 'Enter the city name.'})
        return cleaned


@admin.register(PopularCity)
class PopularCityAdmin(admin.ModelAdmin):
    form = PopularCityAdminForm
    list_display = ['city', 'state', 'pincode', 'position', 'is_active', 'vendor_count']
    list_filter = ['is_active', 'state']
    search_fields = ['city', 'state', 'pincode', 'vendors__shop_name']
    filter_horizontal = ['vendors']
    ordering = ['position', 'city']

    def vendor_count(self, obj):
        return obj.vendors.count()

    vendor_count.short_description = 'Vendors'


@admin.register(DeliveryTiming)
class DeliveryTimingAdmin(admin.ModelAdmin):
    list_display = [
        'vendor', 'open_time', 'close_time', 'quick_enabled',
        'quick_min_minutes', 'quick_max_minutes',
    ]
    list_filter = ['vendor', 'quick_enabled']
    search_fields = ['vendor__shop_name', 'vendor__login_id']
    list_select_related = ['vendor']
    autocomplete_fields = ['vendor']
    fields = [
        'vendor',
        'open_time',
        'close_time',
        'closed_days',
        'closed_dates',
        'quick_enabled',
        'quick_min_minutes',
        'quick_max_minutes',
        'slots',
    ]