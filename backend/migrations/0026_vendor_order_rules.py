from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0025_vendor_home_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='min_order_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=100,
                help_text='Orders under this amount pay the delivery charge.',
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name='vendor',
            name='delivery_charge_under',
            field=models.DecimalField(
                decimal_places=2,
                default=15,
                help_text='Delivery charge when the order is under the minimum.',
                max_digits=10,
            ),
        ),
    ]
