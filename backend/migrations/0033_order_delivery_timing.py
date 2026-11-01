from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0032_useraddress_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='delivery_type',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_slot',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_eta',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
