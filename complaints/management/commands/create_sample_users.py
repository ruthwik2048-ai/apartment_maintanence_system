from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from complaints.models import Apartment, Category, Unit

User = get_user_model()


class Command(BaseCommand):
    help = "Create or update initial sample users and default data."

    def handle(self, *args, **options):
        # 1. President / Administrator User
        president, _ = User.objects.get_or_create(
            username="ruthwik",
            defaults={
                "email": "ruthwik@apartment.com",
                "first_name": "Ruthwik",
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        president.role = User.Role.ADMIN
        president.is_staff = True
        president.is_superuser = True
        president.set_password("180605")
        president.save()
        self.stdout.write(self.style.SUCCESS("President user 'ruthwik' ready."))

        # 2. Staff User (Shankar)
        staff, _ = User.objects.get_or_create(
            username="shankar",
            defaults={
                "email": "shankar@apartment.com",
                "first_name": "Shankar",
                "role": User.Role.STAFF,
                "staff_position": User.StaffPosition.WATCHMAN,
            },
        )
        staff.role = User.Role.STAFF
        staff.staff_position = User.StaffPosition.WATCHMAN
        staff.set_password("VIJETHA")
        staff.save()
        self.stdout.write(self.style.SUCCESS("Staff user 'shankar' ready."))

        # 3. Default Apartment
        apartment, _ = Apartment.objects.get_or_create(
            name="Vijetha Apartments",
            defaults={
                "address": "Main Road",
                "city": "Hyderabad",
                "total_blocks": 1,
                "is_active": True,
            },
        )
        if not apartment.is_active:
            apartment.is_active = True
            apartment.save()

        # 4. Resident User (Ravinder - Flat 103)
        resident, _ = User.objects.get_or_create(
            username="ravinder",
            defaults={
                "email": "ravinder@apartment.com",
                "first_name": "Ravinder",
                "role": User.Role.RESIDENT,
            },
        )
        resident.role = User.Role.RESIDENT
        resident.set_password("103")
        resident.save()

        unit, _ = Unit.objects.get_or_create(
            apartment=apartment,
            unit_number="103",
            defaults={
                "owner_name": "RAVINDER",
                "resident": resident,
                "status": Unit.Status.OCCUPIED,
            },
        )
        unit.owner_name = "RAVINDER"
        unit.resident = resident
        unit.status = Unit.Status.OCCUPIED
        unit.save()
        self.stdout.write(self.style.SUCCESS("Resident user 'ravinder' (Flat 103, Owner: RAVINDER) ready."))

        # 5. Default Categories
        default_categories = [
            ("Plumbing", "wrench", "Water leaks, pipe repairs, tap fixes"),
            ("Electrical", "zap", "Power outages, switch boards, light fixtures"),
            ("Carpentry", "tool", "Doors, windows, furniture repair"),
            ("Cleaning", "trash-2", "Waste disposal, corridor cleaning"),
            ("Lift & Elevator", "chevrons-up", "Elevator maintenance and issues"),
            ("Security", "shield", "CCTV, gate, and watchman assistance"),
            ("General Maintenance", "settings", "General building maintenance issues"),
        ]
        for name, icon, desc in default_categories:
            Category.objects.get_or_create(
                name=name,
                defaults={"icon": icon, "description": desc, "is_active": True},
            )
        self.stdout.write(self.style.SUCCESS("Default categories checked/created."))
