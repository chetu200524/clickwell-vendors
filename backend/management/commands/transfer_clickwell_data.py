from django.core.management.base import BaseCommand
from django.db import connections, transaction

from backend.models import (
    User,
    Order,
    OrderedProduct,
    ProductOption,
)


class Command(BaseCommand):
    help = "Transfer Users, Orders & OrderedProducts from db.sqlite3 to demo-db.sqlite3"

    def handle(self, *args, **kwargs):
        self.stdout.write("\n🚀 Starting Clickwell data transfer...\n")

        connection = connections['default']

        # 🔥 Disable SQLite FK checks
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA foreign_keys = OFF;")

        users_count = 0


        try:
            with transaction.atomic(using='default'):

                # =========================
                # USERS
                # =========================
                for user in User.objects.using('source').all():
                    User.objects.using('default').update_or_create(
                        id=user.id,
                        defaults={
                            'email': user.email,
                            'phone': user.phone,
                            'fullname': user.fullname,
                            'password': user.password,
                            'name': user.name,
                            'address': user.address,
                            'pincode': user.pincode,
                            'contact_no': user.contact_no,
                            'district': user.district,
                            'state': user.state,
                            'created_at': user.created_at,
                        }
                    )
                    users_count += 1

                self.stdout.write(f"✅ Users migrated: {users_count}")




        finally:
            # 🔥 Re-enable FK checks
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA foreign_keys = ON;")

        self.stdout.write(
            self.style.SUCCESS(
                "\n🎉 CLICKWELL DATA TRANSFER COMPLETED SUCCESSFULLY\n"
            )
        )
