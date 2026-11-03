from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from complaints.models import MaintenancePayment, Unit


class Command(BaseCommand):
    help = "Create this month's maintenance dues for every active apartment flat."

    def handle(self, *args, **options):
        today = timezone.localdate()
        if today.day < 2:
            self.stdout.write(f"No dues created before the 2nd. Today is {today:%B %d, %Y}.")
            return

        period = today.replace(day=1)
        active_units = Unit.objects.filter(apartment__is_active=True)
        payments = [
            MaintenancePayment(
                unit_id=unit_id,
                period=period,
                amount=Decimal("1500.00"),
                status=MaintenancePayment.Status.UNPAID,
            )
            for unit_id in active_units.values_list("pk", flat=True)
        ]

        try:
            with transaction.atomic():
                MaintenancePayment.objects.bulk_create(payments, ignore_conflicts=True)
        except IntegrityError as error:
            raise CommandError("Could not create monthly maintenance dues.") from error

        created_count = MaintenancePayment.objects.filter(
            unit__apartment__is_active=True,
            period=period,
        ).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Maintenance dues are ready for {period:%B %Y}: "
                f"{created_count} active flats tracked at ₹1,500 per flat."
            )
        )
