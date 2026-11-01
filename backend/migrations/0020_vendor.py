from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0019_delivery_timing_closed_dates'),
    ]

    operations = [
        migrations.CreateModel(
            name='Vendor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('login_id', models.CharField(help_text='ID the vendor types to open the dashboard.', max_length=50, unique=True)),
                ('password', models.CharField(max_length=5000)),
                ('shop_name', models.CharField(max_length=200)),
                ('owner_name', models.CharField(max_length=200)),
                ('phone', models.CharField(help_text='Main phone number.', max_length=15)),
                ('alternate_phone', models.CharField(blank=True, default='', max_length=15)),
                ('address', models.TextField(blank=True, default='', help_text='Shop address.')),
                ('gstin', models.CharField(blank=True, default='', help_text='GSTIN, 15 characters.', max_length=15)),
                ('license_number', models.CharField(blank=True, default='', help_text='Shop or trade license number.', max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('auth_token', models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ('logged_in_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['shop_name', 'login_id'],
            },
        ),
    ]
