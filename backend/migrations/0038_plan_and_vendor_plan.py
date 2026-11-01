from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('backend', 'Plan')
    defaults = [
        {
            'slug': 'basic',
            'name': 'Basic',
            'duration_days': 30,
            'price': Decimal('0.00'),
            'description': 'Basic shop access for 30 days.',
            'position': 1,
        },
        {
            'slug': 'standard',
            'name': 'Standard',
            'duration_days': 90,
            'price': Decimal('0.00'),
            'description': 'Standard shop access for 90 days.',
            'position': 2,
        },
        {
            'slug': 'premium',
            'name': 'Premium',
            'duration_days': 365,
            'price': Decimal('0.00'),
            'description': 'Premium shop access for 365 days.',
            'position': 3,
        },
    ]
    for row in defaults:
        Plan.objects.get_or_create(slug=row['slug'], defaults=row)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0037_vendor_session_expires_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='Plan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(help_text='Short key, such as basic, standard, or premium.', max_length=40, unique=True)),
                ('name', models.CharField(help_text='Name shown in admin, such as Basic.', max_length=80)),
                ('duration_days', models.PositiveIntegerField(default=30, help_text='How many days the vendor session lasts when this plan is assigned.')),
                ('price', models.DecimalField(decimal_places=2, default=Decimal('0'), help_text='Plan price shown in admin.', max_digits=10)),
                ('description', models.TextField(blank=True, default='')),
                ('is_active', models.BooleanField(default=True)),
                ('position', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Plan',
                'verbose_name_plural': 'Plans',
                'ordering': ['position', 'name'],
            },
        ),
        migrations.AddField(
            model_name='vendor',
            name='plan',
            field=models.ForeignKey(
                blank=True,
                help_text='Subscription plan for this shop.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='vendors',
                to='backend.plan',
            ),
        ),
        migrations.RunPython(seed_plans, noop),
    ]
