from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0013_backfill_slide_categories'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='subcategory',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Saved with the product. Reuses an existing name when the spelling matches.',
                max_length=100,
            ),
        ),
    ]
