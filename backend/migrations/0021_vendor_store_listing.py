from django.db import migrations, models
import django.db.models.deletion


def copy_timing_and_assign_products(apps, schema_editor):
    Vendor = apps.get_model('backend', 'Vendor')
    DeliveryTiming = apps.get_model('backend', 'DeliveryTiming')
    Product = apps.get_model('backend', 'Product')
    timing = DeliveryTiming.objects.filter(pk=1).first()
    if timing is not None:
        Vendor.objects.all().update(
            quick_enabled=timing.quick_enabled,
            quick_min_minutes=timing.quick_min_minutes,
            quick_max_minutes=timing.quick_max_minutes,
            slots=timing.slots,
            open_time=timing.open_time,
            close_time=timing.close_time,
            closed_days=timing.closed_days,
            closed_dates=timing.closed_dates,
        )
    vendor = Vendor.objects.filter(is_active=True).order_by('id').first()
    if vendor is not None:
        Product.objects.filter(vendor__isnull=True).update(vendor=vendor)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0020_vendor'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='quick_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='vendor',
            name='quick_min_minutes',
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.AddField(
            model_name='vendor',
            name='quick_max_minutes',
            field=models.PositiveIntegerField(default=30),
        ),
        migrations.AddField(
            model_name='vendor',
            name='slots',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='vendor',
            name='open_time',
            field=models.TimeField(default='09:00'),
        ),
        migrations.AddField(
            model_name='vendor',
            name='close_time',
            field=models.TimeField(default='22:00'),
        ),
        migrations.AddField(
            model_name='vendor',
            name='closed_days',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='vendor',
            name='closed_dates',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='product',
            name='vendor',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='products',
                to='backend.vendor',
            ),
        ),
        migrations.RunPython(copy_timing_and_assign_products, migrations.RunPython.noop),
    ]
