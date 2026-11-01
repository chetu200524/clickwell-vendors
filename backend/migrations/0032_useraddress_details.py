from django.db import migrations, models


def _split_legacy(apps, schema_editor):
    UserAddress = apps.get_model('backend', 'UserAddress')
    for row in UserAddress.objects.all():
        text = (row.address or '').strip()
        house, locality = '', ''
        if text:
            if ',' in text:
                house, locality = [part.strip() for part in text.split(',', 1)]
            else:
                house = text
        if not row.house:
            row.house = house[:200]
        if not row.locality:
            row.locality = locality[:300]
        if not row.city:
            row.city = (row.district or '')[:200]
        row.save(update_fields=['house', 'locality', 'city'])


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0031_popular_city'),
    ]

    operations = [
        migrations.AddField(
            model_name='useraddress',
            name='house',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='useraddress',
            name='locality',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='useraddress',
            name='landmark',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='useraddress',
            name='city',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.RunPython(_split_legacy, migrations.RunPython.noop),
    ]
