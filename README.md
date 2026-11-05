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
- President dashboard with complaint counts, monthly maintenance payment status by flat, and protected resident contact details
- President account management for resident and maintenance-staff profiles, activation, and password resets
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

For deployment, set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, and `DATABASE_URL` in the environment. Use a persistent production database: `db.sqlite3` is ignored by Git, and the default SQLite database is intended only for local development. Migrations create the database schema but do not copy local apartments, flats, or accounts to the deployed database.

### Repairing initial logins on Render

The local `db.sqlite3` is not deployed with the source code, so local apartments, flats, accounts, and passwords are not automatically copied to Render. On a new deployment, first connect the web service to its persistent database and deploy the latest code. If this is a fresh database, create an administrator with `python manage.py createsuperuser`, sign in at `/admin/`, and create the apartment named `Vijetha Nivas` at `Ramnagar`, `Karimanagar` and its flats with their owner names and flat numbers. The login repair command requires those apartment and flat records to already exist.

Before changing passwords, open the Render Shell for that same web service and run the command without `--apply`:

```sh
python manage.py repair_initial_logins
```

This dry run lists the owner name and flat number currently stored in the production database and makes no changes. Update incorrect owner names or flat numbers in `/admin/` first; this database data is the source for resident logins. Then run `python manage.py repair_initial_logins --apply`. The command asks for the president and staff passwords interactively, resets each linked resident account's password to its flat number, and creates any missing resident or staff accounts. The president is a separate administrator account (`ruthwik`), so the flat 107 resident can continue to sign in with owner name `Ruthwik` and password `107`. If that resident already uses `ruthwik` as their internal account username, the command changes that internal username to `resident-<flat-record-id>`; resident login remains the owner name and flat number. It preserves existing staff positions and refuses to change accounts with unexpected roles or inactive status. Run it only when you intend to reset these initial login credentials.

After it completes, residents sign in on the resident login page with the owner name recorded for their flat (case-insensitive) and the flat number as the password (case-sensitive). The president signs in through **Vijetha Community Access** with username `ruthwik` and the president password entered above. Staff use their assigned username and the staff password entered above. If the command reports that the apartment or flats are missing, create those records in `/admin/` first; do not run the repair command against an unintended database.

When adding or changing flat owners after initial setup, update the flat and owner records in the production database, review the dry-run listing, then run `python manage.py repair_initial_logins --apply` again from the Render Shell. Resident login matches only the current owner name on a flat (ignoring letter case and accidental leading/trailing spaces) and that flat's number as the password; old owner names stop matching after the record is changed. The command creates accounts for newly added flats and resets every linked resident password to its flat's number; it also resets the president and staff passwords to the values entered at the prompts. The configured staff usernames are `sandeep`, `ganesh`, `suresh`, `deeraj`, and `ramesh`.

## Tests

```powershell
python manage.py test
```
