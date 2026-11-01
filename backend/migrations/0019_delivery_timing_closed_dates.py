from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0018_delivery_timing_shop_hours'),
    ]

    operations = [
        migrations.AddField(
            model_name='deliverytiming',
            name='closed_dates',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
