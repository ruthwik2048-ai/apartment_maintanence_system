from django.core.management.base import BaseCommand
from complaints.models import Apartment, Unit


class Command(BaseCommand):
    help = "Set up Vijetha Nivas apartment and 50 flats"

    def handle(self, *args, **kwargs):

        apartment = Apartment.objects.filter(
            is_active=True
        ).order_by("id").first()

        if not apartment:
            self.stdout.write(
                self.style.ERROR(
                    "No active apartment found. Create an apartment first."
                )
            )
            return

        apartment.name = "VIJETHA NIVAS"
        apartment.save()

        created_count = 0

        for floor in range(1, 6):
            for flat in range(1, 11):

                flat_number = f"{floor}{flat:02d}"

                unit, created = Unit.objects.get_or_create(
                    apartment=apartment,
                    unit_number=flat_number,
                    defaults={
                        "owner_name": "Not Assigned",
                        "status": Unit.Status.VACANT,
                    }
                )

                if created:
                    created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"VIJETHA NIVAS configured successfully. "
                f"{created_count} new flats created."
            )
        )
