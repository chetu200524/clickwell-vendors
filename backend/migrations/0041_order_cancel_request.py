from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0040_plan_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='cancel_request_status',
            field=models.CharField(blank=True, default='', help_text='pending, approved, or rejected return request.', max_length=20),
        ),
        migrations.AddField(
            model_name='order',
            name='cancel_requested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='cancel_reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='cancel_reviewed_by',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
