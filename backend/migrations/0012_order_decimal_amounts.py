from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0011_product_decimal_prices'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='tx_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
        migrations.AlterField(
            model_name='orderedproduct',
            name='product_price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
        migrations.AlterField(
            model_name='orderedproduct',
            name='tx_price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
        migrations.AlterField(
            model_name='orderedproduct',
            name='delivery_price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
    ]
