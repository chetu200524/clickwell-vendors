# Migrate legacy SHIPPED rows to OUT_FOR_DELIVERY (quick-commerce flow has no shipped step).

from django.db import migrations


def forwards(apps, schema_editor):
    OrderedProduct = apps.get_model('backend', 'OrderedProduct')
    OrderedProduct.objects.filter(status='SHIPPED').update(status='OUT_FOR_DELIVERY')


def backwards(apps, schema_editor):
    OrderedProduct = apps.get_model('backend', 'OrderedProduct')
    # Best-effort rollback only for rows we would have changed.
    OrderedProduct.objects.filter(status='OUT_FOR_DELIVERY').update(status='SHIPPED')


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0002_slide_category'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
