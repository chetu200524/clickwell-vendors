# urls.py - Enhanced URL patterns with bulk update endpoints
from django.urls import path

from backend.views import (
    # ... existing imports ...
    request_otp, verify_otp, create_account, login, password_reset_email, password_reset_form,
    password_reset_confirm, userdata, resend_otp, categories, slides, pageitems, product_details,
    update_wishlist, update_cart, wishlist, cart, updateaddress, user_addresses, user_address_detail,
    set_default_address, notify_url, initiate_payment, orders, orderdetails,
    updaterating, search, updateinfo, update_phone_request_otp, change_password, logout, viewall, notifications,
    forgot_password, privacy_policy, PrivacyPolicyAPIView, forgotpassword, ContactUsAPIView, contact_us,
    verify_pass_otp, ChangePasswordView, newpassword, ordered_product_list, update_order_status,
    initiate_order, delete_account, fast2sms_verification, get_phone_number, all_products,
    create_product, update_product_option, upload_product_image, delete_product_image, delete_product, update_product,
    get_product_details, get_categories, category_products, create_product_enhanced, update_product_enhanced, bulk_update_stock,
    delete_product_image_enhanced, upload_product_image_enhanced, update_product_option_enhanced, create_product_option,
    update_all_order_products_status_enhanced, update_order_with_confirmation, calculate_delivery_charge, inform_me,
    check_inform_me, check_app_version, app_config, suggest_product, subcategory_suggestions,
    vendor_catalog_summary,
    delivery_timing, sales_summary, sales_status_items, store_list, popular_cities, vendor_categories, vendor_category_detail,
    vendor_category_order, vendor_order_rules, vendor_delivery_pincodes

)
from backend.delivery_auth_views import delivery_login, delivery_session
from backend.vendor_auth_views import vendor_login, vendor_logout, vendor_profile, vendor_plans
from backend.vendor_plan_payment_views import vendor_plan_autopay_webhook, vendor_plan_pay, vendor_plan_verify
from backend.vendor_delivery_boy_views import vendor_delivery_boys, vendor_delivery_boy_detail
from backend.vendor_orders_views import vendor_orders
from backend.cancel_request_views import request_order_cancel, review_order_cancel
from backend.vendor_storefront_views import (
    vendor_page_item_create,
    vendor_page_item_detail,
    vendor_slide_create,
    vendor_slide_detail,
    vendor_storefront,
)

urlpatterns = [
    # Authentication endpoints
    path('request_otp/', request_otp),
    path('resend_otp/', resend_otp),
    path('verify_otp/', verify_otp),
    path('create_account/', create_account),
    path('login/', login),
    path('logout/', logout),
    path('password_reset_email/', password_reset_email),
    path('password_reset_form/<email>/<token>/', password_reset_form, name="password_reset_form"),
    path('password_reset_confirm/', password_reset_confirm, name="password_reset_confirm"),
    path('userdata/', userdata),

    # Category and content endpoints
    path('categories/', categories),
    path('get_categories/', get_categories, name='get_categories'),
    path('vendor/categories/', vendor_categories, name='vendor_categories'),
    path('vendor/categories/order/', vendor_category_order, name='vendor_category_order'),
    path('vendor/categories/<int:category_id>/', vendor_category_detail, name='vendor_category_detail'),
    path('subcategories/', subcategory_suggestions, name='subcategory_suggestions'),
    path('vendor/login/', vendor_login, name='vendor_login'),
    path('vendor/profile/', vendor_profile, name='vendor_profile'),
    path('vendor/catalog_summary/', vendor_catalog_summary, name='vendor_catalog_summary'),
    path('vendor/plans/', vendor_plans, name='vendor_plans'),
    path('vendor/plans/pay/', vendor_plan_pay, name='vendor_plan_pay'),
    path('vendor/plans/verify/', vendor_plan_verify, name='vendor_plan_verify'),
    path('vendor/plans/autopay/webhook/', vendor_plan_autopay_webhook, name='vendor_plan_autopay_webhook'),
    path('vendor/logout/', vendor_logout, name='vendor_logout'),
    path('vendor/storefront/', vendor_storefront, name='vendor_storefront'),
    path('vendor/slides/', vendor_slide_create, name='vendor_slide_create'),
    path('vendor/slides/<int:slide_id>/', vendor_slide_detail, name='vendor_slide_detail'),
    path('vendor/pageitems/', vendor_page_item_create, name='vendor_page_item_create'),
    path('vendor/pageitems/<int:item_id>/', vendor_page_item_detail, name='vendor_page_item_detail'),
    path('stores/', store_list, name='store_list'),
    path('popular_cities/', popular_cities, name='popular_cities'),
    path('delivery_timing/', delivery_timing, name='delivery_timing'),
    path('vendor/order_rules/', vendor_order_rules, name='vendor_order_rules'),
    path('vendor/delivery_pincodes/', vendor_delivery_pincodes, name='vendor_delivery_pincodes'),
    path('vendor/delivery_boys/', vendor_delivery_boys, name='vendor_delivery_boys'),
    path('vendor/delivery_boys/<int:partner_id>/', vendor_delivery_boy_detail, name='vendor_delivery_boy_detail'),
    path('vendor/orders/', vendor_orders, name='vendor_orders'),
    path('sales/status-items/', sales_status_items, name='sales_status_items'),
    path('sales/', sales_summary, name='sales_summary'),
    path('slides/', slides),
    path('pageitems/', pageitems),
    path('category_products/', category_products, name='category_products'),
    path('productdetails/', product_details),
    path('viewall/', viewall),
    path('search/', search),

    # User management endpoints
    path('updatewishlist/', update_wishlist),
    path('updatecart/', update_cart),
    path('wishlist/', wishlist),
    path('cart/', cart),
    path('updateaddress/', updateaddress),
    path('addresses/', user_addresses, name='user_addresses'),
    path('addresses/<uuid:address_id>/', user_address_detail, name='user_address_detail'),
    path('addresses/<uuid:address_id>/set_default/', set_default_address, name='set_default_address'),
    path('updateinfo/', updateinfo),
    path('updatephone_otp/', update_phone_request_otp),
    path('changepassword/', change_password),
    path('deleteaccount/', delete_account, name='delete_account'),

    # Payment and order endpoints
    path('initiate_payment/', initiate_payment),
    path('notify_url/', notify_url),
    path('initiate_order/', initiate_order, name='initiate_order'),
    path('orders/', orders),
    path('orderdetails/', orderdetails),
    path('order/cancel_request/', request_order_cancel, name='order_cancel_request'),
    path('order/cancel_review/', review_order_cancel, name='order_cancel_review'),
    path('updaterating/', updaterating),

    # Delivery partner app authentication
    path('delivery/login/', delivery_login, name='delivery_login'),
    path('delivery/session/', delivery_session, name='delivery_session'),

    # ORDER MANAGEMENT ENDPOINTS - Enhanced (delivery app — requires Delivery token)
    path('orderedProduct/', ordered_product_list, name='ordered_product_list'),

    # Single order status update (both old and enhanced versions)
    path('update_order_status/', update_order_status, name='update_order_status'),

    # Notification endpoints
    path('notifications/', notifications),

    # Password reset endpoints
    path('forgot_password/', forgot_password),
    path('forgot-password/', forgotpassword, name='forgot-password'),
    path('verify_pass_otp/', verify_pass_otp, name='verify_pass_otp'),
    path('change_password_otp/', ChangePasswordView.as_view(), name='change_password_otp'),
    path('newpassword/', newpassword, name="newpassword"),

    # Static pages (HTML)
    path('privacy-policy/', privacy_policy, name='privacy_policy'),
    path('contact_us/', contact_us, name='contact_us'),

    # JSON content for mobile app (use /api/contact-us/ not /api/api/contact-us/)
    path('contact-us/', ContactUsAPIView.as_view(), name='contact_us_api'),
    path('privacy-policy-content/', PrivacyPolicyAPIView.as_view(), name='privacy_policy_api'),
    # Legacy nested paths (kept for older clients)
    path('api/privacy-policy/', PrivacyPolicyAPIView.as_view(), name='privacy_policy_api_legacy'),
    path('api/contact-us/', ContactUsAPIView.as_view(), name='contact_us_api_legacy'),

    # Utility endpoints
    path("fast2sms-verification/", fast2sms_verification, name="fast2sms_verification"),
    path('phone-number/', get_phone_number),

    # Product management endpoints
    path('all_products/', all_products, name='all_products'),
    path('products/<uuid:product_id>/', get_product_details, name='get_product_details'),
    path('products/<uuid:product_id>/update/', update_product, name='update_product'),
    path('products/<uuid:product_id>/delete/', delete_product, name='delete_product'),
    path('products/create/', create_product, name='create_product'),

    # Product option endpoints
    path('product-options/create/', create_product_option, name='create_product_option'),
    path('product-options/<uuid:option_id>/update/', update_product_option, name='update_product_option'),
    path('product-options/<uuid:option_id>/update/', update_product_option_enhanced,
         name='update_product_option_enhanced'),

    # Image management endpoints
    path('product-images/upload/', upload_product_image, name='upload_product_image'),
    path('product-images/<str:image_id>/delete/', delete_product_image, name='delete_product_image'),
    path('product-images/upload/', upload_product_image_enhanced, name='upload_product_image_enhanced'),
    path('product-images/<str:image_id>/delete/', delete_product_image_enhanced, name='delete_product_image_enhanced'),

    # Enhanced product endpoints
    path('products/create/', create_product_enhanced, name='create_product_enhanced'),
    path('products/<uuid:product_id>/update/', update_product_enhanced, name='update_product_enhanced'),

    # Bulk operations
    path('bulk-update-stock/', bulk_update_stock, name='bulk_update_stock'),

    path('update_all_order_status_enhanced/', update_all_order_products_status_enhanced,
         name='update_all_order_status_enhanced'),

    # Order status update with confirmation
    path('update_order_with_confirmation/', update_order_with_confirmation, name='update_order_with_confirmation'),

    path('calculate_delivery_charge/', calculate_delivery_charge, name='calculate_delivery_charge'),

    path('app_config/', app_config, name='app_config'),

    path('inform_me/', inform_me, name='inform_me'),

    path('check_inform_me/', check_inform_me, name='check_inform_me'),

    path('suggest_product/', suggest_product, name='suggest_product'),

    path('check-version/', check_app_version, name='check_app_version'),
]

