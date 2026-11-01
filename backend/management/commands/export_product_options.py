from django.core.management.base import BaseCommand
from openpyxl import Workbook
from backend.models import ProductOption


class Command(BaseCommand):
    help = "Export all product options to Excel"

    def handle(self, *args, **kwargs):
        wb = Workbook()
        ws = wb.active
        ws.title = "Product Options"

        # Excel headers
        ws.append([
            "Product ID",
            "Product Title",
            "Category",
            "Option ID",
            "Option Name",
            "Quantity",
            "Price",
            "Offer Price",
            "COD",
            "Created At"
        ])

        options = ProductOption.objects.select_related(
            "product", "product__category"
        )

        for opt in options:
            product = opt.product
            ws.append([
                str(product.id),
                product.title,
                product.category.name,
                str(opt.id),
                opt.option,
                opt.quantity,
                product.price,
                product.offer_price,
                product.cod,
                product.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ])

        file_name = "product_options_export.xlsx"
        wb.save(file_name)

        self.stdout.write(
            self.style.SUCCESS(f"✅ Excel file generated: {file_name}")
        )
