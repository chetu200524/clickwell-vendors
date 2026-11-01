from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0036_order_orderedproduct_deliverytiming_vendor'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='session_expires_at',
            field=models.DateField(
                blank=True,
                help_text='Vendor app session stays valid through this date. Leave blank for no expiry. You can change this anytime.',
                null=True,
            ),
        ),
    ]
