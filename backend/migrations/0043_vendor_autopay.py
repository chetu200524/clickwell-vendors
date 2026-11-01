from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0042_plan_prices'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='razorpay_plan_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Razorpay plan id used for monthly autopay.',
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name='vendor',
            name='razorpay_subscription_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Razorpay subscription used for monthly autopay.',
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name='vendor',
            name='razorpay_paid_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Number of autopay charges already applied to this shop.',
            ),
        ),
        migrations.AddField(
            model_name='vendor',
            name='autopay_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Monthly plan is set to deduct automatically every month.',
            ),
        ),
    ]
