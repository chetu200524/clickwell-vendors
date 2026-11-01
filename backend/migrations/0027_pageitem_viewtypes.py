from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0026_vendor_order_rules'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pageitem',
            name='viewtype',
            field=models.IntegerField(
                choices=[
                    (1, 'BANNER'),
                    (2, 'SWIPER'),
                    (3, 'GRID'),
                    (4, 'ROW'),
                    (5, 'OFFERS'),
                ],
            ),
        ),
    ]
