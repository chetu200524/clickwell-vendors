from django.core.files.base import ContentFile
from django.db import migrations, models
import django.db.models.deletion


def assign_slides_to_first_category(apps, schema_editor):
    Slide = apps.get_model('backend', 'Slide')
    Category = apps.get_model('backend', 'Category')

    if not Slide.objects.filter(category__isnull=True).exists():
        return

    default_category = Category.objects.order_by('position', 'id').first()
    if default_category is None:
        default_category = Category(name='General', position=0)
        default_category.image.save(
            'default_slide_category.jpg',
            ContentFile(b'placeholder'),
            save=True,
        )

    Slide.objects.filter(category__isnull=True).update(category=default_category)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='slide',
            name='category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='slides_set',
                to='backend.category',
            ),
        ),
        migrations.RunPython(
            assign_slides_to_first_category,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='slide',
            name='category',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='slides_set',
                to='backend.category',
            ),
        ),
    ]
