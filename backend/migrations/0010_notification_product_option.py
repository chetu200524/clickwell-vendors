from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0009_product_suggestion'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='product_option',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='notifications',
                to='backend.productoption',
            ),
        ),
    ]
