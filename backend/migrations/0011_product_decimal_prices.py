from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0010_notification_product_option'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
        migrations.AlterField(
            model_name='product',
            name='offer_price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
        migrations.AlterField(
            model_name='product',
            name='delivery_charge',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
        migrations.AlterField(
            model_name='productoption',
            name='price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
        migrations.AlterField(
            model_name='productoption',
            name='offer_price',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=10),
        ),
    ]
