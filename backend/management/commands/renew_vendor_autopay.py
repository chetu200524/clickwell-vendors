from django.core.management.base import BaseCommand

from backend.models import Vendor
from backend.vendor_plan_autopay import sync_vendor_autopay


class Command(BaseCommand):
    help = 'Apply Razorpay monthly and yearly autopay charges to vendor subscriptions.'

    def handle(self, *args, **options):
        vendors = Vendor.objects.select_related('plan').exclude(razorpay_subscription_id='')
        renewed = 0
        for vendor in vendors:
            before = vendor.razorpay_paid_count
            sync_vendor_autopay(vendor)
            vendor.refresh_from_db()
            if vendor.razorpay_paid_count > before:
                renewed += 1
        self.stdout.write(f'Renewed {renewed} vendor subscription(s).')
