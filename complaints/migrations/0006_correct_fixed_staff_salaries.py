from decimal import Decimal

from django.db import migrations


def correct_fixed_staff_salaries(apps, schema_editor):
    User = apps.get_model("complaints", "User")
    User.objects.filter(
        role="staff",
        staff_position="watchman",
    ).update(salary=Decimal("10000.00"))
    User.objects.filter(role="staff").exclude(
        staff_position="watchman",
    ).update(salary=Decimal("7500.00"))


class Migration(migrations.Migration):

    dependencies = [
        ("complaints", "0005_set_fixed_staff_salaries"),
    ]

    operations = [
        migrations.RunPython(
            correct_fixed_staff_salaries,
            migrations.RunPython.noop,
        ),
    ]
