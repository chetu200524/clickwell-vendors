from django.db import migrations, models


def seed_vendor_cities(apps, schema_editor):
    Vendor = apps.get_model('backend', 'Vendor')
    PopularCity = apps.get_model('backend', 'PopularCity')
    grouped = {}
    for vendor in Vendor.objects.filter(is_active=True).order_by('id'):
        city = (vendor.city or '').strip()
        if not city:
            continue
        state = (vendor.state or '').strip()
        key = (city.lower(), state.lower())
        grouped.setdefault(key, {'city': city, 'state': state, 'vendors': [], 'pincode': ''})
        grouped[key]['vendors'].append(vendor)
        if not grouped[key]['pincode']:
            codes = vendor.delivery_pincodes if isinstance(vendor.delivery_pincodes, list) else []
            for code in codes:
                text = str(code).strip()
                if len(text) == 6 and text.isdigit():
                    grouped[key]['pincode'] = text
                    break
    for index, item in enumerate(grouped.values()):
        if not item['pincode']:
            continue
        row = PopularCity.objects.create(
            city=item['city'],
            state=item['state'],
            pincode=item['pincode'],
            position=index,
            is_active=True,
        )
        row.vendors.set(item['vendors'])


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0030_vendor_delivery_pincodes'),
    ]

    operations = [
        migrations.CreateModel(
            name='PopularCity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('city', models.CharField(max_length=100)),
                ('state', models.CharField(blank=True, default='', max_length=100)),
                ('pincode', models.CharField(help_text='6-digit pincode for this city.', max_length=6)),
                ('latitude', models.DecimalField(decimal_places=6, default=0, max_digits=9)),
                ('longitude', models.DecimalField(decimal_places=6, default=0, max_digits=9)),
                ('position', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('vendors', models.ManyToManyField(blank=True, related_name='popular_cities', to='backend.vendor')),
            ],
            options={
                'verbose_name': 'Popular city',
                'verbose_name_plural': 'Popular cities',
                'ordering': ['position', 'city'],
            },
        ),
        migrations.RunPython(seed_vendor_cities, migrations.RunPython.noop),
    ]
