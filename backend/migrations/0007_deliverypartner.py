from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0006_useraddress_order_address_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeliveryPartner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('login_id', models.CharField(help_text='ID used to sign in on the delivery app', max_length=50, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('password', models.CharField(max_length=5000)),
                ('is_active', models.BooleanField(default=True)),
                (
                    'is_logged_in',
                    models.BooleanField(
                        default=False,
                        help_text='True while signed in on a device. Cleared only via admin force logout.',
                    ),
                ),
                ('auth_token', models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ('logged_in_at', models.DateTimeField(blank=True, null=True)),
                ('device_info', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Delivery partner',
                'verbose_name_plural': 'Delivery partners',
                'ordering': ['login_id'],
            },
        ),
    ]
