from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Quick production health check: migrations, tables, delivery partners, categories.'

    def handle(self, *args, **options):
        from django.db.migrations.executor import MigrationExecutor
        from backend.models import Category, DeliveryPartner, Product

        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        pending = [f'{m.app_label}.{m.name}' for m, _ in plan]

        self.stdout.write('=== ClickWell deploy health ===')
        if pending:
            self.stdout.write(self.style.WARNING(f'Pending migrations: {", ".join(pending)}'))
            self.stdout.write('Run: python manage.py migrate --noinput')
        else:
            self.stdout.write(self.style.SUCCESS('Migrations: all applied'))

        try:
            self.stdout.write(f'Categories: {Category.objects.count()}')
            self.stdout.write(f'Products: {Product.objects.count()}')
            self.stdout.write(f'Delivery partners: {DeliveryPartner.objects.count()}')
            active = DeliveryPartner.objects.filter(is_active=True, is_logged_in=True).count()
            self.stdout.write(f'Delivery partners logged in: {active}')
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Database error: {exc}'))
            self.stdout.write('Likely cause: migrations not applied. Run migrate.')

        self.stdout.write('')
        self.stdout.write('If delivery app gets 403 (58 bytes) on /api/orderedProduct/:')
        self.stdout.write('  -> nginx is NOT forwarding auth headers to Django')
        self.stdout.write('  1. Add to nginx /api/ location:')
        self.stdout.write('       proxy_set_header Authorization $http_authorization;')
        self.stdout.write('       proxy_set_header X-Delivery-Token $http_x_delivery_token;')
        self.stdout.write('     See deploy/nginx-clickwelladmin.conf')
        self.stdout.write('  2. sudo nginx -t && sudo systemctl reload nginx')
        self.stdout.write('  3. Re-login in clickwell_delivery app')
        self.stdout.write('')
        self.stdout.write('If admin /product/add/ returns 500:')
        self.stdout.write('  -> run: python manage.py migrate --noinput (NEVER makemigrations)')
        self.stdout.write('  -> then restart gunicorn and check error log')
