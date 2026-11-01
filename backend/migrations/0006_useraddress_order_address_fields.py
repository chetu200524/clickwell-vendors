import uuid

from django.db import migrations, models
import django.db.models.deletion


def migrate_user_addresses(apps, schema_editor):
    User = apps.get_model('backend', 'User')
    UserAddress = apps.get_model('backend', 'UserAddress')

    for user in User.objects.all():
        if not user.address and not user.pincode:
            continue
        UserAddress.objects.create(
            id=uuid.uuid4(),
            user=user,
            label='Home',
            name=user.name or user.fullname or 'Customer',
            address=user.address or '',
            pincode=user.pincode or 0,
            contact_no=user.contact_no or user.phone or '',
            district=user.district or '',
            state=user.state or '',
            is_default=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0005_alter_slide_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserAddress',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('label', models.CharField(default='Home', max_length=50)),
                ('name', models.CharField(max_length=100)),
                ('address', models.TextField(max_length=1000)),
                ('pincode', models.IntegerField()),
                ('contact_no', models.CharField(max_length=10)),
                ('district', models.CharField(blank=True, max_length=500)),
                ('state', models.CharField(blank=True, max_length=500)),
                ('latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='addresses_set', to='backend.user')),
            ],
            options={
                'ordering': ['-is_default', '-updated_at'],
            },
        ),
        migrations.AddField(
            model_name='order',
            name='order_for_someone_else',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='order',
            name='user_address',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='orders_set', to='backend.useraddress'),
        ),
        migrations.RunPython(migrate_user_addresses, migrations.RunPython.noop),
    ]
