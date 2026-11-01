from decimal import Decimal

from django.db import migrations


PLAN_PRICES = {
    'basic': Decimal('999.00'),
    'standard': Decimal('4599.00'),
    'premium': Decimal('9999.00'),
}


def set_plan_prices(apps, schema_editor):
    Plan = apps.get_model('backend', 'Plan')
    for slug, price in PLAN_PRICES.items():
        Plan.objects.filter(slug=slug).update(price=price)


def unset_plan_prices(apps, schema_editor):
    Plan = apps.get_model('backend', 'Plan')
    Plan.objects.filter(slug__in=PLAN_PRICES).update(price=Decimal('0.00'))


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0041_order_cancel_request'),
    ]

    operations = [
        migrations.RunPython(set_plan_prices, unset_plan_prices),
    ]
