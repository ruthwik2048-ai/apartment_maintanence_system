from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from complaints.models import Apartment, Unit, User


STAFF_NAMES = ("Sandeep", "Ganesh", "Suresh", "Deeraj", "Ramesh")


class Command(BaseCommand):
    help = "Set up the initial Vijetha Nivas resident, staff, and president logins."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply login changes to the database.",
        )

    def handle(self, *args, **options):
        apartment = Apartment.objects.filter(
            name="Vijetha Nivas",
            address="Ramnagar",
            city="Karimanagar",
        ).first()
        if apartment is None:
            raise CommandError(
                "Vijetha Nivas was not found in this database. Confirm Render is "
                "connected to the expected database before changing accounts."
            )

        units = list(Unit.objects.filter(apartment=apartment).order_by("unit_number"))
        if not units:
            raise CommandError(
                "No flats were found for Vijetha Nivas; no accounts were changed."
            )

        president_unit = next(
            (
                unit
                for unit in units
                if unit.unit_number == "107"
                and unit.owner_name.casefold() == "ruthwik"
            ),
            None,
        )
        if president_unit is None:
            raise CommandError(
                "Flat 107 for Ruthwik was not found in this database. Confirm the "
                "production flat and owner records before changing accounts."
            )

        if not options["apply"]:
            self.stdout.write(
                f"Found {len(units)} flats. No accounts changed. "
                "Pass --apply to repair the logins."
            )
            return

        president_password = self._read_confirmed_password("President")
        staff_password = self._read_confirmed_password("Staff")

        with transaction.atomic():
            self._make_president_username_available(president_unit)
            president = self._get_or_create_user(
                username="ruthwik",
                role=User.Role.ADMIN,
                first_name=president_unit.owner_name,
                email="president@vijethanivas.invalid",
            )
            self._validate_active_role(president, User.Role.ADMIN, "President")
            president.set_password(president_password)
            president.save(update_fields=("password",))

            resident_ids = set()
            created_residents = 0
            for unit in units:
                resident = unit.resident
                if resident is not None:
                    resident = User.objects.get(pk=resident.pk)
                    self._validate_active_role(
                        resident,
                        User.Role.RESIDENT,
                        f"Resident linked to flat {unit.unit_number}",
                    )
                    if resident.pk in resident_ids:
                        raise CommandError(
                            f"Multiple flats share the same resident account "
                            f"({resident.username}); no accounts were changed."
                        )
                else:
                    resident = User(
                        username=f"resident-{unit.pk}",
                        first_name=unit.owner_name,
                        email=f"resident-{unit.pk}@vijethanivas.invalid",
                        role=User.Role.RESIDENT,
                    )
                    resident.set_password(unit.unit_number)
                    resident.save()
                    unit.resident = resident
                    unit.save(update_fields=("resident",))
                    created_residents += 1

                resident_ids.add(resident.pk)
                resident.set_password(unit.unit_number)
                resident.save(update_fields=("password",))

            for name in STAFF_NAMES:
                staff_member = self._get_or_create_user(
                    username=name.lower(),
                    role=User.Role.STAFF,
                    first_name=name,
                    email=f"{name.lower()}@vijethanivas.invalid",
                )
                self._validate_active_role(
                    staff_member,
                    User.Role.STAFF,
                    f"Staff member {name}",
                )
                staff_member.set_password(staff_password)
                staff_member.save(update_fields=("password",))

        self.stdout.write(
            self.style.SUCCESS(
                f"Login repair complete: {len(units)} residents "
                f"({created_residents} created), {len(STAFF_NAMES)} staff, "
                "and the separate president account are ready."
            )
        )

    @staticmethod
    def _make_president_username_available(president_unit):
        matching_users = list(User.objects.filter(username__iexact="ruthwik")[:2])
        if len(matching_users) > 1:
            raise CommandError(
                "Multiple accounts match the president username 'ruthwik'; "
                "no accounts were changed."
            )
        if not matching_users or matching_users[0].role != User.Role.RESIDENT:
            return

        resident = matching_users[0]
        if president_unit.resident_id != resident.pk:
            raise CommandError(
                "The username 'ruthwik' belongs to a resident account that is "
                "not linked to Ruthwik in flat 107; no accounts were changed."
            )

        resident_username = f"resident-{president_unit.pk}"
        if (
            User.objects.filter(username__iexact=resident_username)
            .exclude(pk=resident.pk)
            .exists()
        ):
            raise CommandError(
                f"Cannot reserve the president username 'ruthwik': "
                f"replacement resident username {resident_username!r} is "
                "already in use; no accounts were changed."
            )

        resident.username = resident_username
        resident.save(update_fields=("username",))

    @staticmethod
    def _read_confirmed_password(label):
        password = getpass(f"Enter the password to set for {label}: ")
        confirmation = getpass(f"Confirm the {label} password: ")
        if not password or password != confirmation:
            raise CommandError(f"The {label} passwords did not match.")
        return password

    @staticmethod
    def _validate_active_role(user, expected_role, description):
        if user.role != expected_role:
            raise CommandError(
                f"{description} account {user.username!r} has a different role; "
                "no accounts were changed."
            )
        if not user.is_active:
            raise CommandError(
                f"{description} account {user.username!r} is inactive; "
                "no accounts were changed."
            )

    @staticmethod
    def _get_or_create_user(*, username, role, first_name, email):
        matching_users = list(User.objects.filter(username__iexact=username)[:2])
        if len(matching_users) > 1:
            raise CommandError(
                f"Multiple accounts match username {username!r}; "
                "no accounts were changed."
            )
        if matching_users:
            return matching_users[0]

        user = User(
            username=username,
            first_name=first_name,
            email=email,
            role=role,
        )
        user.set_unusable_password()
        user.save()
        return user
