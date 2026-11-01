from django.db import migrations, models


def fill_duration_display(apps, schema_editor):
    Plan = apps.get_model('backend', 'Plan')
    for plan in Plan.objects.all():
        days = int(plan.duration_days or 0)
        if days > 0 and days % 365 == 0:
            plan.duration_value = days // 365
            plan.duration_unit = 'years'
        else:
            plan.duration_value = days or 30
            plan.duration_unit = 'days'
        plan.save(update_fields=['duration_value', 'duration_unit'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0038_plan_and_vendor_plan'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='duration_unit',
            field=models.CharField(
                choices=[('days', 'Days'), ('months', 'Months'), ('years', 'Years')],
                default='days',
                help_text='Choose Days, Months, or Years. 30 days or 1 month, 365 days or 1 year.',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='plan',
            name='duration_value',
            field=models.PositiveIntegerField(
                default=30,
                help_text='Number shown with the unit, such as 30 days, 1 month, or 1 year.',
            ),
        ),
        migrations.AlterField(
            model_name='plan',
            name='duration_days',
            field=models.PositiveIntegerField(
                default=30,
                help_text='Saved as days from the value and unit above.',
            ),
        ),
        migrations.RunPython(fill_duration_display, noop),
    ]
