from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0029_vendor_location'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='delivery_pincodes',
            field=models.JSONField(blank=True, default=list, help_text='Pincodes this shop delivers to.'),
        ),
    ]
