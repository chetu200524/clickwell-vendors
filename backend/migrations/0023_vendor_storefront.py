from django.db import migrations, models


def assign_storefront_to_first_vendor(apps, schema_editor):
    Vendor = apps.get_model('backend', 'Vendor')
    Slide = apps.get_model('backend', 'Slide')
    PageItem = apps.get_model('backend', 'PageItem')
    vendor = Vendor.objects.filter(is_active=True).order_by('id').first()
    if vendor is None:
        return
    Slide.objects.filter(vendor__isnull=True).update(vendor=vendor)
    PageItem.objects.filter(vendor__isnull=True).update(vendor=vendor)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0022_vendor_shop_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='slide',
            name='vendor',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name='slides',
                to='backend.vendor',
            ),
        ),
        migrations.AddField(
            model_name='pageitem',
            name='vendor',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name='page_items',
                to='backend.vendor',
            ),
        ),
        migrations.RunPython(assign_storefront_to_first_vendor, migrations.RunPython.noop),
    ]
