from django.db import migrations


RESIDENT_NAMES_BY_UNIT = {
    "101": "Arun",
    "102": "Aakash",
    "103": "Vinay",
    "104": "Vijay",
    "105": "Ajay",
    "106": "Gopi",
    "107": "Ruthwik",
    "108": "Karthik",
    "109": "Akshay",
    "201": "Saikumar",
    "202": "Shiva",
    "203": "Ravi",
    "204": "Raju",
    "205": "Vikranth",
    "206": "Dinesh",
    "207": "Somesh",
    "208": "Mahesh",
    "209": "Rajesh",
    "301": "Srinivas",
    "302": "Arun",
    "303": "Akarsh",
    "304": "Bindu",
    "305": "Mani",
    "306": "Abhinav",
    "307": "Vignesh",
    "308": "Snehith",
    "309": "Rohan",
    "401": "Vamshi",
    "402": "Gagan",
    "403": "Bharat",
    "404": "Preetham",
    "405": "Thanish",
    "406": "Nithin",
    "407": "Sharath",
    "408": "Nikhil",
    "409": "Saketh",
    "501": "Hanish",
    "502": "Shiva",
    "503": "Teja",
    "504": "Pruthvi Raj",
    "505": "Charan",
    "506": "Roja",
    "507": "Aruna",
    "508": "Sridhar",
    "509": "Varsha",
}


def set_resident_names(apps, schema_editor):
    Unit = apps.get_model("complaints", "Unit")
    for unit_number, owner_name in RESIDENT_NAMES_BY_UNIT.items():
        Unit.objects.filter(
            apartment__name="Vijetha Nivas",
            apartment__address="Ramnagar",
            apartment__city="Karimanagar",
            unit_number=unit_number,
        ).update(owner_name=owner_name)


class Migration(migrations.Migration):

    dependencies = [
        ("complaints", "0008_complaint_common_area_location_and_more"),
    ]

    operations = [
        migrations.RunPython(
            set_resident_names,
            migrations.RunPython.noop,
        ),
    ]
