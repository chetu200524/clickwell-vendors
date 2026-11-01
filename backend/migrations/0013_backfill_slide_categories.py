from django.core.files.base import ContentFile
from django.db import migrations


def backfill_slide_categories(apps, schema_editor):
    """Ensure legacy slides always have a category (safe to re-run)."""
    Slide = apps.get_model('backend', 'Slide')
    Category = apps.get_model('backend', 'Category')

    if not Slide.objects.filter(category__isnull=True).exists():
        return

    category = Category.objects.order_by('position', 'id').first()
    if category is None:
        category = Category(name='General', position=0)
        category.image.save(
            'default_slide_category.jpg',
            ContentFile(b'placeholder'),
            save=True,
        )

    Slide.objects.filter(category__isnull=True).update(category=category)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0012_order_decimal_amounts'),
    ]

    operations = [
        migrations.RunPython(backfill_slide_categories, migrations.RunPython.noop),
    ]
