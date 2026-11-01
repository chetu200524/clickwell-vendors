from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0023_vendor_storefront'),
    ]

    operations = [
        migrations.AlterField(
            model_name='category',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='categories/'),
        ),
    ]
