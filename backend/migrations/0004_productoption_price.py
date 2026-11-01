from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0003_migrate_shipped_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='productoption',
            name='price',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='productoption',
            name='offer_price',
            field=models.IntegerField(default=0),
        ),
    ]
