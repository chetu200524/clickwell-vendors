from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0033_order_delivery_timing'),
    ]

    operations = [
        migrations.AddField(
            model_name='deliverypartner',
            name='vendor',
            field=models.ForeignKey(
                blank=True,
                help_text='Shop that created this delivery boy account.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='delivery_partners',
                to='backend.vendor',
            ),
        ),
        migrations.AddField(
            model_name='deliverypartner',
            name='phone',
            field=models.CharField(blank=True, default='', max_length=15),
        ),
    ]
