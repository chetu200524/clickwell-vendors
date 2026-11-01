from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0016_product_subcategories'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeliveryTiming',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quick_enabled', models.BooleanField(default=False)),
                ('quick_min_minutes', models.PositiveIntegerField(default=10)),
                ('quick_max_minutes', models.PositiveIntegerField(default=30)),
                ('slots', models.JSONField(blank=True, default=list)),
            ],
            options={
                'verbose_name': 'Delivery timing',
                'verbose_name_plural': 'Delivery timing',
            },
        ),
    ]
