from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0039_plan_duration_unit'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='image',
            field=models.ImageField(
                blank=True,
                help_text='Logo or image shown on the vendor plan card.',
                upload_to='plans/',
            ),
        ),
    ]
