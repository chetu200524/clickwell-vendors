from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0028_pageitem_option_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='location',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Shop location, such as a market or landmark.',
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name='vendor',
            name='city',
            field=models.CharField(blank=True, default='', help_text='City name.', max_length=100),
        ),
        migrations.AddField(
            model_name='vendor',
            name='state',
            field=models.CharField(blank=True, default='', help_text='State name.', max_length=100),
        ),
    ]
