from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0034_deliverypartner_vendor'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderedproduct',
            name='handled_by',
            field=models.ForeignKey(
                blank=True,
                help_text='Delivery boy who last changed this order status.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='handled_items',
                to='backend.deliverypartner',
            ),
        ),
        migrations.AddField(
            model_name='orderedproduct',
            name='handled_by_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='orderedproduct',
            name='handled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
