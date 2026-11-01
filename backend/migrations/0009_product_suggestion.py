from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0008_order_delivery_contact'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductSuggestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_name', models.CharField(max_length=255)),
                ('search_query', models.CharField(blank=True, default='', max_length=255)),
                ('notes', models.TextField(blank=True, default='')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('reviewed', 'Reviewed'),
                        ('added', 'Added to catalog'),
                    ],
                    default='pending',
                    max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='product_suggestions',
                    to='backend.user',
                )),
            ],
            options={
                'verbose_name': 'Product Suggestion',
                'verbose_name_plural': 'Product Suggestions',
                'ordering': ['-created_at'],
            },
        ),
    ]
