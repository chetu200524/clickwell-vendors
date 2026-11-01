from django.db import migrations, models
import django.db.models.deletion


def backfill_vendors(apps, schema_editor):
    Order = apps.get_model('backend', 'Order')
    OrderedProduct = apps.get_model('backend', 'OrderedProduct')
    DeliveryTiming = apps.get_model('backend', 'DeliveryTiming')
    Vendor = apps.get_model('backend', 'Vendor')

    for item in OrderedProduct.objects.select_related('product_option__product').iterator():
        product = getattr(item.product_option, 'product', None) if item.product_option_id else None
        vendor_id = getattr(product, 'vendor_id', None) if product is not None else None
        if vendor_id and item.vendor_id != vendor_id:
            item.vendor_id = vendor_id
            item.save(update_fields=['vendor_id'])

    for order in Order.objects.filter(vendor__isnull=True).iterator():
        item = (
            OrderedProduct.objects
            .filter(order_id=order.id)
            .exclude(vendor_id=None)
            .only('vendor_id')
            .first()
        )
        if item is None:
            item = (
                OrderedProduct.objects
                .filter(order_id=order.id)
                .select_related('product_option__product')
                .first()
            )
            product = getattr(item.product_option, 'product', None) if item is not None else None
            vendor_id = getattr(product, 'vendor_id', None) if product is not None else None
        else:
            vendor_id = item.vendor_id
        if vendor_id:
            order.vendor_id = vendor_id
            order.save(update_fields=['vendor_id'])

    for vendor in Vendor.objects.all():
        DeliveryTiming.objects.get_or_create(
            vendor_id=vendor.id,
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


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0035_orderedproduct_handled_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='vendor',
            field=models.ForeignKey(
                blank=True,
                help_text='Shop this order belongs to.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='orders',
                to='backend.vendor',
            ),
        ),
        migrations.AddField(
            model_name='orderedproduct',
            name='vendor',
            field=models.ForeignKey(
                blank=True,
                help_text='Shop this ordered product belongs to.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ordered_products',
                to='backend.vendor',
            ),
        ),
        migrations.AddField(
            model_name='deliverytiming',
            name='vendor',
            field=models.OneToOneField(
                blank=True,
                help_text='Shop these delivery windows belong to.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='delivery_timing_row',
                to='backend.vendor',
            ),
        ),
        migrations.RunPython(backfill_vendors, noop),
    ]
