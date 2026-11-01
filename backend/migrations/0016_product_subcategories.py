from django.db import migrations, models


def copy_single_subcategory(apps, schema_editor):
    Product = apps.get_model('backend', 'Product')
    for product in Product.objects.exclude(subcategory='').iterator():
        name = str(product.subcategory or '').strip()
        if not name:
            continue
        product.subcategories = [name]
        product.save(update_fields=['subcategories'])


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0015_product_barcode'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='subcategories',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Subcategory chips saved on this product. A product can have several.',
            ),
        ),
        migrations.AlterField(
            model_name='product',
            name='subcategory',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Comma-separated copy of the subcategory chips, kept for search.',
            ),
        ),
        migrations.RunPython(copy_single_subcategory, migrations.RunPython.noop),
    ]
