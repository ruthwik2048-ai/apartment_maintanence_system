# Vijetha Nivas

This is a standalone Django implementation of the apartment complaint-management system in the sibling `webapp.py` file. It does not use or modify the separate SkillCareer Django project.

## Features

- Resident accounts and login
- Apartment, unit, resident, category, complaint, work-log, feedback, and notification records stored in SQLite
- Resident complaint submission limited to their assigned units
- Optional preferred visit times on issue reports, shown to assigned staff and administrators
- Private-unit vs. common-area issue reporting, with duplicate checks for matching open common-area reports
- Resident help chat with direct staff notifications for emergency reports
- Resident help chat displays relevant employees' roles and contact details, and shows all active staff for emergencies
- Admin assignment and reassignment of complaints to active maintenance staff, with notifications to the resident and affected staff
- President-managed maintenance staff accounts for complaint assignment
- President-visible monthly staff salaries (₹10,000 for watchmen and ₹7,500 for other maintenance staff)
- Dedicated maintenance staff sign-in and assigned-work dashboard
- Watchman-only monthly maintenance collection tracking for all flats (₹1,500 per flat)
- Staff work statuses for Pending, In Progress, Completed, and Successful
- Assigned staff status updates, work history, and resident notifications
- Resident reopening and feedback after resolution
- Role-aware dashboard and Django admin
- President-only flat detail pages with complaint counts and issue descriptions
- Public community information page with apartment facilities and resident login hidden on that page
- Optional complaint/work-log file attachments

## Run locally

From this directory in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Sign up for a resident account, then use `/admin/` to create apartments, units, categories, and staff accounts. Set an account's role to Maintenance Staff before assigning complaints to it. The president can manage staff accounts and monthly salaries from President Access. Mark watchman accounts with the Watchman staff position; after login they can track each active flat's monthly ₹1,500 maintenance fee at `/staff-access/maintenance-collection/`.

On Windows, double-click `run_apartment_maintenance.bat` to start the site in a terminal using the project's `.venv`. The default browser opens automatically when the site is ready. Keep the terminal open while using the site, then press Ctrl+C in that window to stop the server. If the site is already running, the launcher opens it in your browser without starting a second server.

### Automatic monthly maintenance dues

Run the maintenance dues command once a day from the 2nd of each month onward to create the current month's ₹1,500 unpaid maintenance entry for every flat in an active apartment. The operation is safe to repeat and will not overwrite a payment already recorded as paid. Keep the computer available and your Windows account signed in around the 2nd; Windows is configured to run a missed task when available.

The command can also be run manually from the 2nd of the month:

```powershell
.\.venv\Scripts\python.exe manage.py generate_monthly_maintenance_dues
```

For deployment, set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, and `DJANGO_ALLOWED_HOSTS` in the environment. The default SQLite database and secret are intended for local development.

### Repairing initial logins on Render

The local `db.sqlite3` is not deployed with the source code, so local accounts and passwords are not automatically copied to Render. After confirming the Render service is connected to the expected database and the latest code is deployed, open its Shell and run:

```sh
python manage.py repair_initial_logins --apply
```

The command asks for the president and staff passwords interactively, resets each linked resident account's password to its flat number, and creates any missing resident or staff accounts. It preserves existing staff positions and refuses to change accounts with unexpected roles or inactive status. Run it only when you intend to reset these initial login credentials.

## Tests

```powershell
python manage.py test
```
