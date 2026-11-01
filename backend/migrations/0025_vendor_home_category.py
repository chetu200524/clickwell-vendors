from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0024_category_image_optional'),
    ]

    operations = [
        migrations.CreateModel(
            name='VendorHomeCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.IntegerField(default=0)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='home_placements', to='backend.category')),
                ('vendor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='home_categories', to='backend.vendor')),
            ],
            options={
                'ordering': ['position', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='vendorhomecategory',
            constraint=models.UniqueConstraint(fields=('vendor', 'category'), name='unique_vendor_home_category'),
        ),
    ]
