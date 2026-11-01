from django.core.management.base import BaseCommand
from django.db import connections, transaction
from backend.models import (
    Category, Product, ProductOption, ProductImage
)

class Command(BaseCommand):
    help = "Copy products from db-demo.sqlite3 to db.sqlite3"

    def handle(self, *args, **options):
        source_db = connections['source']

        self.stdout.write("🚀 Copying Categories...")
        for cat in Category.objects.using('source').all():
            Category.objects.get_or_create(
                id=cat.id,
                defaults={
                    'name': cat.name,
                    'position': cat.position,
                    'image': cat.image
                }
            )

        self.stdout.write("🚀 Copying Products...")
        for p in Product.objects.using('source').all():
            Product.objects.get_or_create(
                id=p.id,
                defaults={
                    'category_id': p.category_id,
                    'title': p.title,
                    'description': p.description,
                    'price': p.price,
                    'offer_price': p.offer_price,
                    'delivery_charge': p.delivery_charge,
                    'star_1': p.star_1,
                    'star_2': p.star_2,
                    'star_3': p.star_3,
                    'star_4': p.star_4,
                    'star_5': p.star_5,
                    'cod': p.cod,
                    'created_at': p.created_at,
                    'updated_at': p.updated_at,
                }
            )

        self.stdout.write("🚀 Copying Product Options...")
        for opt in ProductOption.objects.using('source').all():
            ProductOption.objects.get_or_create(
                id=opt.id,
                defaults={
                    'product_id': opt.product_id,
                    'option': opt.option,
                    'quantity': opt.quantity,
                }
            )

        self.stdout.write("🚀 Copying Product Images...")
        for img in ProductImage.objects.using('source').all():
            ProductImage.objects.get_or_create(
                id=img.id,
                defaults={
                    'product_option_id': img.product_option_id,
                    'image': img.image,
                    'position': img.position,
                }
            )

        self.stdout.write(self.style.SUCCESS("✅ Products copied successfully!"))
