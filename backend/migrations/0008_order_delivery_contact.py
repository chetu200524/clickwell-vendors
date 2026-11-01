from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0007_deliverypartner'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='delivery_contact_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_contact_phone',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
    ]
