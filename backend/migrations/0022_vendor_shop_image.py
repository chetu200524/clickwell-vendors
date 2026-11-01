from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0021_vendor_store_listing'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='shop_image',
            field=models.ImageField(blank=True, help_text='Photo of the shop shown on the store list.', upload_to='shops/'),
        ),
    ]
