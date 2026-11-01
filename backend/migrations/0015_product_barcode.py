from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0014_product_subcategory'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='barcode',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Optional product barcode captured when the product is added.',
                max_length=128,
            ),
        ),
    ]
