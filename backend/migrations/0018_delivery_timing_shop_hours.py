import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0017_delivery_timing'),
    ]

    operations = [
        migrations.AddField(
            model_name='deliverytiming',
            name='open_time',
            field=models.TimeField(default=datetime.time(9, 0)),
        ),
        migrations.AddField(
            model_name='deliverytiming',
            name='close_time',
            field=models.TimeField(default=datetime.time(22, 0)),
        ),
        migrations.AddField(
            model_name='deliverytiming',
            name='closed_days',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
