from django.db import migrations, models
import django.db.models.deletion


def copy_existing_order(apps, schema_editor):
    PageItemOption = apps.get_model('backend', 'PageItemOption')
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'SELECT pageitem_id, productoption_id FROM backend_pageitem_product_options ORDER BY id'
        )
        rows = cursor.fetchall()
    next_position = {}
    links = []
    for page_item_id, option_id in rows:
        position = next_position.get(page_item_id, 0)
        next_position[page_item_id] = position + 1
        links.append(PageItemOption(
            page_item_id=page_item_id,
            product_option_id=option_id,
            position=position,
        ))
    PageItemOption.objects.bulk_create(links)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0027_pageitem_viewtypes'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageItemOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.IntegerField(default=0)),
                ('page_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='option_links', to='backend.pageitem')),
                ('product_option', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='page_item_links', to='backend.productoption')),
            ],
            options={
                'ordering': ['position', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='pageitemoption',
            constraint=models.UniqueConstraint(fields=('page_item', 'product_option'), name='unique_page_item_option'),
        ),
        migrations.RunPython(copy_existing_order, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='pageitem',
            name='product_options',
        ),
        migrations.AddField(
            model_name='pageitem',
            name='product_options',
            field=models.ManyToManyField(blank=True, through='backend.PageItemOption', to='backend.productoption'),
        ),
    ]
