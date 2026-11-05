from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AssignmentForm, ComplaintForm, FeedbackForm, WorkUpdateForm
from .models import (
    Apartment,
    Category,
    Complaint,
    Feedback,
    MaintenancePayment,
    Notification,
    Unit,
    User,
)


class ComplaintWorkflowTests(TestCase):
    def setUp(self):
        self.resident = User.objects.create_user(
            username="resident",
            password="Test-password-123",
            email="resident@example.com",
            role=User.Role.RESIDENT,
        )
        self.other_resident = User.objects.create_user(
            username="other",
            password="Test-password-123",
            email="other@example.com",
            role=User.Role.RESIDENT,
        )
        self.staff = User.objects.create_user(
            username="staff",
            password="Test-password-123",
            email="staff@example.com",
            role=User.Role.STAFF,
        )
        self.admin = User.objects.create_user(
            username="admin",
            password="Test-password-123",
            email="admin@example.com",
            role=User.Role.ADMIN,
        )
        self.apartment = Apartment.objects.create(
            name="Green Apartments",
            address="10 Main Road",
            city="Pune",
        )
        self.unit = Unit.objects.create(
            apartment=self.apartment,
            unit_number="A-101",
            owner_name="Resident",
            resident=self.resident,
        )
        self.other_unit = Unit.objects.create(
            apartment=self.apartment,
            unit_number="A-102",
            owner_name="Other Resident",
            resident=self.other_resident,
        )
        self.category = Category.objects.create(name="Plumbing")

    def create_complaint(self, **kwargs):
        values = {
            "unit": self.unit,
            "resident": self.resident,
            "category": self.category,
            "title": "Leaking tap",
            "description": "The kitchen tap is leaking.",
            "created_by": self.resident,
        }
        values.update(kwargs)
        return Complaint.objects.create(**values)

    def test_complaint_form_offers_all_active_apartment_units(self):
        form = ComplaintForm()
        self.assertEqual(
            list(form.fields["unit"].queryset),
            [self.unit, self.other_unit],
        )
        self.assertFalse(form.fields["preferred_visit_time"].required)

    def test_resident_can_submit_complaint_and_get_notification(self):
        self.client.force_login(self.resident)
        response = self.client.post(
            reverse("complaint_create"),
            {
                "unit": self.unit.pk,
                "category": self.category.pk,
                "title": "Broken light",
                "description": "The hallway light is out.",
                "preferred_visit_time": "After 6 PM",
                "priority": Complaint.Priority.HIGH,
            },
        )
        complaint = Complaint.objects.get(title="Broken light")
        self.assertRedirects(
            response,
            reverse("complaint_detail", args=(complaint.pk,)),
        )
        self.assertEqual(complaint.resident, self.resident)
        self.assertEqual(complaint.preferred_visit_time, "After 6 PM")
        self.assertTrue(Notification.objects.filter(complaint=complaint).exists())
        self.assertContains(
            self.client.get(reverse("complaint_detail", args=(complaint.pk,))),
            "After 6 PM",
        )

    def test_assigned_staff_can_see_preferred_visit_time(self):
        complaint = self.create_complaint(
            preferred_visit_time="10 AM - 12 PM",
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("complaint_detail", args=(complaint.pk,)))

        self.assertContains(response, "10 AM - 12 PM")
        self.assertContains(response, "Preferred visit time")

    def test_resident_can_submit_complaint_for_another_unit(self):
        self.client.force_login(self.resident)
        response = self.client.post(
            reverse("complaint_create"),
            {
                "unit": self.other_unit.pk,
                "category": self.category.pk,
                "title": "Wrong unit",
                "description": "This unit belongs to another resident.",
                "priority": Complaint.Priority.MEDIUM,
            },
        )
        complaint = Complaint.objects.get(title="Wrong unit")
        self.assertRedirects(
            response,
            reverse("complaint_detail", args=(complaint.pk,)),
        )
        self.assertEqual(complaint.unit, self.other_unit)
        self.assertEqual(complaint.resident, self.resident)

    def test_resident_can_submit_common_area_issue_without_a_unit(self):
        self.client.force_login(self.resident)
        response = self.client.post(
            reverse("complaint_create"),
            {
                "scope": Complaint.Scope.COMMON,
                "common_area_location": "Lift lobby",
                "category": self.category.pk,
                "title": "Lift is not working",
                "description": "The lift is stuck on the ground floor.",
                "priority": Complaint.Priority.URGENT,
            },
        )

        complaint = Complaint.objects.get(title="Lift is not working")
        self.assertRedirects(
            response,
            reverse("complaint_detail", args=(complaint.pk,)),
        )
        self.assertEqual(complaint.scope, Complaint.Scope.COMMON)
        self.assertIsNone(complaint.unit)
        self.assertEqual(complaint.common_area_location, "Lift lobby")

    def test_matching_open_common_area_issue_cannot_be_submitted_twice(self):
        self.client.force_login(self.resident)
        issue_data = {
            "scope": Complaint.Scope.COMMON,
            "common_area_location": "Lift lobby",
            "category": self.category.pk,
            "title": "Lift is not working",
            "description": "The lift is stuck.",
            "priority": Complaint.Priority.HIGH,
        }
        self.client.post(reverse("complaint_create"), issue_data)
        self.client.force_login(self.other_resident)

        duplicate_data = {
            **issue_data,
            "common_area_location": "  LIFT LOBBY ",
            "title": "  lift is not working ",
        }
        response = self.client.post(reverse("complaint_create"), duplicate_data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A matching common area issue is already open.")
        self.assertEqual(
            Complaint.objects.filter(scope=Complaint.Scope.COMMON).count(),
            1,
        )

    def test_resident_help_sends_emergency_to_staff_and_staff_can_claim_it(self):
        self.client.force_login(self.resident)
        response = self.client.post(
            reverse("resident_help"),
            {
                "scope": Complaint.Scope.PRIVATE,
                "unit": self.unit.pk,
                "category": self.category.pk,
                "title": "Burst pipe",
                "description": "Water is flooding the kitchen.",
                "priority": Complaint.Priority.URGENT,
                "is_emergency": "on",
            },
        )
        complaint = Complaint.objects.get(title="Burst pipe")
        self.assertRedirects(
            response,
            reverse("complaint_detail", args=(complaint.pk,)),
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.staff,
                complaint=complaint,
                title="Emergency resident report",
            ).exists()
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("staff_portal"))
        self.assertContains(response, "Emergency reports")
        self.assertContains(response, "Burst pipe")
        response = self.client.get(reverse("complaint_detail", args=(complaint.pk,)))
        self.assertContains(response, "Update work status")

        response = self.client.post(
            reverse("update_complaint", args=(complaint.pk,)),
            {"status": Complaint.Status.IN_PROGRESS, "comment": "Responding now."},
        )
        complaint.refresh_from_db()
        self.assertRedirects(response, reverse("complaint_detail", args=(complaint.pk,)))
        self.assertEqual(complaint.assigned_to, self.staff)
        self.assertEqual(complaint.status, Complaint.Status.IN_PROGRESS)

    def test_resident_help_shows_relevant_employee_contacts_and_emergency_team(self):
        electrician = User.objects.create_user(
            username="electrician",
            password="Strong-electrician-pass-987",
            first_name="Eli",
            email="electrician@example.com",
            phone="555-1234",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.ELECTRICIAN,
        )
        self.client.force_login(self.resident)

        response = self.client.get(
            reverse("resident_help_staff"),
            {"category": Category.objects.create(name="Electrical issues").pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [employee["name"] for employee in response.json()["staff"]],
            ["Eli"],
        )
        self.assertEqual(response.json()["staff"][0]["phone"], "555-1234")

        response = self.client.get(
            reverse("resident_help_staff"),
            {"emergency": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {employee["name"] for employee in response.json()["staff"]},
            {self.staff.username, "Eli"},
        )

    def test_only_residents_can_view_chat_employee_contacts(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("resident_help_staff"), {"emergency": "true"})

        self.assertEqual(response.status_code, 403)

    def test_admin_can_assign_and_assigned_staff_can_resolve(self):
        complaint = self.create_complaint()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("assign_complaint", args=(complaint.pk,)),
            {"assigned_to": self.staff.pk},
        )
        self.assertRedirects(response, reverse("complaint_detail", args=(complaint.pk,)))
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.ASSIGNED)
        self.assertEqual(complaint.assigned_to, self.staff)

        self.client.force_login(self.staff)
        self.client.post(
            reverse("update_complaint", args=(complaint.pk,)),
            {"status": Complaint.Status.IN_PROGRESS, "comment": "Work started."},
        )
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.IN_PROGRESS)
        self.client.post(
            reverse("update_complaint", args=(complaint.pk,)),
            {"status": Complaint.Status.RESOLVED, "comment": "Tap repaired."},
        )
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.RESOLVED)
        self.assertEqual(complaint.work_logs.count(), 2)

    def test_admin_can_reassign_complaint_without_resetting_work_status(self):
        replacement_staff = User.objects.create_user(
            username="replacement",
            password="Strong-replacement-pass-987",
            first_name="Replacement",
            last_name="Worker",
            email="replacement@example.com",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.ELECTRICIAN,
        )
        complaint = self.create_complaint(
            assigned_to=self.staff,
            status=Complaint.Status.IN_PROGRESS,
        )
        self.client.force_login(self.admin)

        detail_response = self.client.get(
            reverse("complaint_detail", args=(complaint.pk,))
        )
        self.assertContains(detail_response, "Reassign maintenance staff")
        self.assertContains(detail_response, "Currently assigned to")
        self.assertContains(detail_response, "Replacement Worker — Electrician")

        response = self.client.post(
            reverse("assign_complaint", args=(complaint.pk,)),
            {"assigned_to": replacement_staff.pk},
        )

        self.assertRedirects(response, reverse("complaint_detail", args=(complaint.pk,)))
        complaint.refresh_from_db()
        self.assertEqual(complaint.assigned_to, replacement_staff)
        self.assertEqual(complaint.status, Complaint.Status.IN_PROGRESS)
        self.assertTrue(
            Notification.objects.filter(
                recipient=replacement_staff,
                complaint=complaint,
                title="Complaint Reassigned",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.staff,
                complaint=complaint,
                title="Complaint Reassigned",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.resident,
                complaint=complaint,
                message__contains="Replacement Worker",
            ).exists()
        )

    def test_staff_work_status_choices_include_pending_completed_and_successful(self):
        assigned = self.create_complaint(status=Complaint.Status.ASSIGNED)
        assigned_choices = dict(WorkUpdateForm(complaint=assigned).fields["status"].choices)
        self.assertIn(Complaint.Status.ASSIGNED, assigned_choices)
        self.assertIn(Complaint.Status.PENDING, assigned_choices)
        self.assertIn(Complaint.Status.IN_PROGRESS, assigned_choices)
        self.assertIn(Complaint.Status.COMPLETED, assigned_choices)
        self.assertIn(Complaint.Status.SUCCESSFUL, assigned_choices)

        in_progress = self.create_complaint(status=Complaint.Status.IN_PROGRESS)
        in_progress_choices = dict(
            WorkUpdateForm(complaint=in_progress).fields["status"].choices
        )
        self.assertIn(Complaint.Status.COMPLETED, in_progress_choices)
        self.assertIn(Complaint.Status.SUCCESSFUL, in_progress_choices)

    def test_staff_can_mark_complaints_completed_or_successful(self):
        self.client.force_login(self.staff)
        for status in (Complaint.Status.COMPLETED, Complaint.Status.SUCCESSFUL):
            with self.subTest(status=status):
                complaint = self.create_complaint(
                    status=Complaint.Status.IN_PROGRESS,
                    assigned_to=self.staff,
                )
                response = self.client.post(
                    reverse("update_complaint", args=(complaint.pk,)),
                    {"status": status, "comment": f"Work marked {status}."},
                )

                self.assertRedirects(
                    response,
                    reverse("complaint_detail", args=(complaint.pk,)),
                )
                complaint.refresh_from_db()
                self.assertEqual(complaint.status, status)
                self.assertIsNotNone(complaint.resolved_at)
                self.assertTrue(
                    Notification.objects.filter(
                        recipient=self.resident,
                        complaint=complaint,
                        message__contains=complaint.get_status_display(),
                    ).exists()
                )
                self.assertFalse(complaint.is_overdue)

    def test_successful_staff_complaint_counts_as_completed_feedback_item(self):
        complaint = self.create_complaint(status=Complaint.Status.SUCCESSFUL)
        self.client.force_login(self.resident)

        response = self.client.get(reverse("feedback_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["complaints"]), [complaint])

    def test_staff_portal_summarizes_pending_completed_and_successful_statuses(self):
        self.create_complaint(
            title="Pending task",
            status=Complaint.Status.PENDING,
            assigned_to=self.staff,
        )
        self.create_complaint(
            title="Completed task",
            status=Complaint.Status.COMPLETED,
            assigned_to=self.staff,
        )
        self.create_complaint(
            title="Successful task",
            status=Complaint.Status.SUCCESSFUL,
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("staff_portal"))

        self.assertEqual(response.context["summary"]["pending"], 1)
        self.assertEqual(response.context["summary"]["completed"], 2)
        self.assertEqual(response.context["summary"]["successful"], 1)
        self.assertContains(response, "Pending")
        self.assertContains(response, "Completed")
        self.assertContains(response, "Successful")

    def test_staff_portal_hides_completed_complaints_after_24_hours_and_preserves_history(self):
        recent_completed = self.create_complaint(
            title="Recently completed",
            status=Complaint.Status.COMPLETED,
            assigned_to=self.staff,
        )
        recent_completed.resolved_at = timezone.now() - timedelta(hours=23)
        recent_completed.save(update_fields=("resolved_at",))
        old_successful = self.create_complaint(
            title="Older successful work",
            status=Complaint.Status.SUCCESSFUL,
            assigned_to=self.staff,
        )
        old_successful.resolved_at = timezone.now() - timedelta(hours=24, seconds=1)
        old_successful.save(update_fields=("resolved_at",))
        active = self.create_complaint(
            title="New pending work",
            status=Complaint.Status.PENDING,
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("staff_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["complaints"]),
            [active, recent_completed],
        )
        self.assertContains(response, "Recently completed")
        self.assertContains(response, "New pending work")
        self.assertNotContains(response, "Older successful work")
        self.assertTrue(Complaint.objects.filter(pk=old_successful.pk).exists())
        self.assertEqual(old_successful.work_logs.count(), 0)
        self.assertTrue(
            Complaint.objects.filter(
                pk=old_successful.pk,
                status=Complaint.Status.SUCCESSFUL,
            ).exists()
        )
        history_response = self.client.get(
            reverse("complaint_detail", args=(old_successful.pk,))
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, "Older successful work")

    def test_staff_login_redirects_to_staff_work_portal(self):
        self.staff.set_password("StaffPass-12345")
        self.staff.save(update_fields=("password",))

        response = self.client.post(
            reverse("staff_login"),
            {"username": "STAFF", "password": "StaffPass-12345"},
        )

        self.assertRedirects(response, reverse("staff_portal"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            self.staff.pk,
        )

    def test_watchman_login_redirects_to_maintenance_collection(self):
        watchman = User.objects.create_user(
            username="watchman",
            password="WatchmanPass-12345",
            email="watchman@example.com",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.WATCHMAN,
        )

        response = self.client.post(
            reverse("staff_login"),
            {"username": watchman.username, "password": "WatchmanPass-12345"},
        )

        self.assertRedirects(response, reverse("maintenance_collection"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), watchman.pk)

    def test_watchman_collection_shows_all_flats_and_monthly_totals(self):
        watchman = User.objects.create_user(
            username="watchman",
            email="watchman@example.com",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.WATCHMAN,
        )
        self.client.force_login(watchman)

        response = self.client.get(reverse("maintenance_collection"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_count"], 2)
        self.assertEqual(response.context["paid_count"], 0)
        self.assertEqual(response.context["unpaid_count"], 2)
        self.assertEqual(response.context["total_collected"], 0)
        self.assertEqual(response.context["total_due"], 3000)
        self.assertContains(response, "₹1,500 per flat")
        self.assertContains(response, "101")
        self.assertContains(response, "102")
        self.assertContains(response, "Unpaid")
        self.assertContains(response, f'id="flat-{self.unit.pk}"')

    def test_monthly_maintenance_command_creates_active_flat_dues_idempotently(self):
        current_period = date(2026, 11, 1)
        already_paid = MaintenancePayment.objects.create(
            unit=self.unit,
            period=current_period,
            amount="1500.00",
            status=MaintenancePayment.Status.PAID,
        )
        previous_payment = MaintenancePayment.objects.create(
            unit=self.other_unit,
            period=date(2026, 10, 1),
            status=MaintenancePayment.Status.PAID,
        )
        inactive_apartment = Apartment.objects.create(
            name="Inactive Apartments",
            address="20 Main Road",
            city="Pune",
            is_active=False,
        )
        inactive_unit = Unit.objects.create(
            apartment=inactive_apartment,
            unit_number="B-101",
            owner_name="Inactive Unit",
        )

        with patch(
            "complaints.management.commands.generate_monthly_maintenance_dues.timezone.localdate",
            return_value=date(2026, 11, 1),
        ):
            output = StringIO()
            call_command("generate_monthly_maintenance_dues", stdout=output)
            self.assertIn("No dues created before the 2nd.", output.getvalue())
        self.assertEqual(MaintenancePayment.objects.filter(period=current_period).count(), 1)

        with patch(
            "complaints.management.commands.generate_monthly_maintenance_dues.timezone.localdate",
            return_value=date(2026, 11, 2),
        ):
            call_command("generate_monthly_maintenance_dues", stdout=StringIO())
            call_command("generate_monthly_maintenance_dues", stdout=StringIO())

        already_paid.refresh_from_db()
        previous_payment.refresh_from_db()
        created_due = MaintenancePayment.objects.get(
            unit=self.other_unit,
            period=current_period,
        )
        self.assertEqual(already_paid.status, MaintenancePayment.Status.PAID)
        self.assertEqual(previous_payment.status, MaintenancePayment.Status.PAID)
        self.assertEqual(created_due.status, MaintenancePayment.Status.UNPAID)
        self.assertEqual(created_due.amount, 1500)
        self.assertFalse(
            MaintenancePayment.objects.filter(
                unit=inactive_unit,
                period=current_period,
            ).exists()
        )
        self.assertEqual(
            MaintenancePayment.objects.filter(period=current_period).count(),
            2,
        )

    def test_watchman_collection_shows_overdue_alert_for_unpaid_flats(self):
        watchman = User.objects.create_user(
            username="watchman-overdue",
            email="watchman-overdue@example.com",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.WATCHMAN,
        )
        current_period = timezone.localdate().replace(day=1)
        MaintenancePayment.objects.create(
            unit=self.unit,
            period=current_period,
            amount="1500.00",
            status=MaintenancePayment.Status.UNPAID,
        )
        self.client.force_login(watchman)

        response = self.client.get(reverse("maintenance_collection"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_overdue"])
        self.assertEqual(response.context["overdue_count"], 1)
        self.assertContains(response, "Overdue maintenance fee")
        self.assertContains(response, "Overdue")

    def test_watchman_can_record_and_revise_monthly_flat_payment(self):
        watchman = User.objects.create_user(
            username="watchman",
            email="watchman@example.com",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.WATCHMAN,
        )
        self.client.force_login(watchman)
        collection_url = reverse("maintenance_collection")

        response = self.client.post(
            collection_url,
            {"unit_id": self.unit.pk, "status": MaintenancePayment.Status.PAID},
        )

        payment = MaintenancePayment.objects.get(unit=self.unit)
        self.assertRedirects(response, f"{collection_url}#flat-{self.unit.pk}")
        self.assertEqual(payment.amount, 1500)
        self.assertEqual(payment.status, MaintenancePayment.Status.PAID)
        self.assertEqual(payment.recorded_by, watchman)
        self.assertIsNotNone(payment.paid_at)

        response = self.client.post(
            collection_url,
            {"unit_id": self.unit.pk, "status": MaintenancePayment.Status.UNPAID},
        )
        self.assertRedirects(response, f"{collection_url}#flat-{self.unit.pk}")
        payment.refresh_from_db()
        self.assertEqual(payment.status, MaintenancePayment.Status.UNPAID)
        self.assertIsNone(payment.paid_at)

    def test_non_watchman_staff_cannot_access_maintenance_collection(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("maintenance_collection"))

        self.assertEqual(response.status_code, 403)

    def test_staff_login_rejects_non_staff_accounts(self):
        self.resident.set_password("ResidentPass-12345")
        self.resident.save(update_fields=("password",))
        response = self.client.post(
            reverse("staff_login"),
            {"username": self.resident.username, "password": "ResidentPass-12345"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not have maintenance staff access")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_portal_shows_only_assigned_complaints_and_work_status_counts(self):
        assigned = self.create_complaint(
            title="Assigned leak",
            status=Complaint.Status.ASSIGNED,
            assigned_to=self.staff,
        )
        in_progress = self.create_complaint(
            title="Work in progress",
            status=Complaint.Status.IN_PROGRESS,
            assigned_to=self.staff,
        )
        self.create_complaint(
            title="Another worker complaint",
            assigned_to=User.objects.create_user(
                username="another-staff",
                email="another-staff@example.com",
                role=User.Role.STAFF,
            ),
        )
        self.create_complaint(title="Unassigned complaint")
        self.client.force_login(self.staff)

        response = self.client.get(reverse("staff_portal"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["total"], 2)
        self.assertEqual(response.context["summary"]["pending"], 1)
        self.assertEqual(response.context["summary"]["in_progress"], 1)
        self.assertEqual(response.context["summary"]["completed"], 0)
        self.assertEqual(
            list(response.context["complaints"]),
            [in_progress, assigned],
        )
        self.assertContains(response, "Assigned to you")
        self.assertContains(response, "Work in progress")
        self.assertContains(
            response,
            f'href="{reverse("complaint_detail", args=(assigned.pk,))}"',
        )
        self.assertNotContains(response, "Another worker complaint")
        self.assertNotContains(response, "Unassigned complaint")

    def test_staff_portal_requires_staff_role(self):
        response = self.client.get(reverse("staff_portal"))
        self.assertRedirects(
            response,
            f"{reverse('staff_login')}?next={reverse('staff_portal')}",
        )

        self.client.force_login(self.resident)
        response = self.client.get(reverse("staff_portal"))
        self.assertEqual(response.status_code, 403)

    def test_resident_cannot_view_another_residents_complaint(self):
        complaint = self.create_complaint()
        self.client.force_login(self.other_resident)
        response = self.client.get(reverse("complaint_detail", args=(complaint.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_feedback_requires_rating_between_one_and_five(self):
        self.assertFalse(FeedbackForm(data={"rating": 0}).is_valid())
        self.assertFalse(FeedbackForm(data={"rating": 6}).is_valid())
        self.assertTrue(FeedbackForm(data={"rating": 5}).is_valid())

    def test_resident_can_submit_feedback_for_resolved_complaint(self):
        complaint = self.create_complaint(status=Complaint.Status.RESOLVED)
        self.client.force_login(self.resident)

        response = self.client.post(
            reverse("submit_feedback", args=(complaint.pk,)),
            {"rating": "5", "comments": "Excellent work."},
        )

        self.assertRedirects(
            response,
            reverse("complaint_detail", args=(complaint.pk,)),
        )
        feedback = Feedback.objects.get(complaint=complaint)
        self.assertEqual(feedback.resident, self.resident)
        self.assertEqual(feedback.rating, 5)
        self.assertEqual(feedback.comments, "Excellent work.")

    def test_resident_can_rate_completed_emergency_response(self):
        complaint = self.create_complaint(
            title="Emergency: burst pipe",
            status=Complaint.Status.COMPLETED,
            is_emergency=True,
            assigned_to=self.staff,
        )
        self.client.force_login(self.resident)

        detail_response = self.client.get(
            reverse("complaint_detail", args=(complaint.pk,))
        )
        self.assertContains(detail_response, "Rate the emergency response")

        response = self.client.post(
            reverse("submit_feedback", args=(complaint.pk,)),
            {"rating": "5", "comments": "Staff responded quickly."},
        )

        self.assertRedirects(
            response,
            reverse("complaint_detail", args=(complaint.pk,)),
        )
        feedback = Feedback.objects.get(complaint=complaint)
        self.assertEqual(feedback.resident, self.resident)
        self.assertEqual(feedback.rating, 5)
        self.assertEqual(feedback.comments, "Staff responded quickly.")

    def test_feedback_list_only_shows_resolved_unrated_resident_complaints(self):
        waiting = self.create_complaint(status=Complaint.Status.RESOLVED)
        already_rated = self.create_complaint(
            title="Rated complaint",
            status=Complaint.Status.RESOLVED,
        )
        Feedback.objects.create(
            complaint=already_rated,
            resident=self.resident,
            rating=4,
        )
        other_resident_complaint = self.create_complaint(
            title="Other resident complaint",
            resident=self.other_resident,
            status=Complaint.Status.RESOLVED,
        )
        self.client.force_login(self.resident)

        response = self.client.get(reverse("feedback_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["complaints"]),
            [waiting],
        )
        self.assertNotContains(response, other_resident_complaint.title)

    def test_feedback_list_is_for_residents_only(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("feedback_list"))
        self.assertEqual(response.status_code, 403)

    def test_overdue_uses_72_hour_threshold_and_resolved_complaints_are_not_overdue(self):
        complaint = self.create_complaint()
        complaint.created_at = timezone.now() - timedelta(hours=73)
        complaint.save(update_fields=("created_at",))
        self.assertTrue(complaint.is_overdue)
        complaint.status = Complaint.Status.RESOLVED
        self.assertFalse(complaint.is_overdue)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_resident_dashboard_shows_assigned_flat_owner_name_and_number(self):
        self.unit.owner_name = "RAVI"
        self.unit.unit_number = "101"
        self.unit.save(update_fields=("owner_name", "unit_number"))
        self.client.force_login(self.resident)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["display_name"], "RAVI")
        self.assertEqual(response.context["resident_unit"], self.unit)
        self.assertContains(response, "Welcome, RAVI")
        self.assertContains(response, "Flat 101")

    def test_resident_dashboard_shows_circular_chart_for_only_their_complaints(self):
        self.create_complaint(title="Waiting", status=Complaint.Status.PENDING)
        self.create_complaint(title="Being fixed", status=Complaint.Status.IN_PROGRESS)
        self.create_complaint(title="Finished", status=Complaint.Status.COMPLETED)
        self.create_complaint(
            title="Another resident's issue",
            resident=self.other_resident,
            unit=self.other_unit,
            status=Complaint.Status.REOPENED,
        )
        self.client.force_login(self.resident)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["total"], 3)
        self.assertEqual(
            [
                (segment["label"], segment["count"])
                for segment in response.context["complaint_chart"]
            ],
            [("Pending", 1), ("In progress", 1), ("Resolved", 1)],
        )
        self.assertContains(response, "Your complaint status")
        self.assertContains(response, "aria-label=\"Circular chart of your 3 complaints")
        self.assertNotContains(response, "Another resident&#x27;s issue")

    def test_resident_dashboard_chart_handles_no_complaints(self):
        self.client.force_login(self.resident)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["total"], 0)
        self.assertContains(response, "Report a complaint to see your progress here.")
        self.assertContains(response, "class=\"dashboard-donut-track\"")

    def test_resident_dashboard_shows_current_flat_maintenance_due_or_paid(self):
        period = timezone.localdate().replace(day=1)
        resident_payment = MaintenancePayment.objects.create(
            unit=self.unit,
            period=period,
            amount="1500.00",
            status=MaintenancePayment.Status.PAID,
        )
        MaintenancePayment.objects.create(
            unit=self.other_unit,
            period=period,
            amount="2500.00",
            status=MaintenancePayment.Status.UNPAID,
        )
        self.client.force_login(self.resident)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["resident_maintenance_payment"], resident_payment)
        self.assertEqual(response.context["resident_maintenance_status"], "Paid")
        self.assertEqual(response.context["maintenance_total"], Decimal("1500.00"))
        self.assertEqual(response.context["maintenance_received"], Decimal("1500.00"))
        self.assertEqual(response.context["maintenance_due"], Decimal("0.00"))
        self.assertContains(response, "Your maintenance")
        self.assertContains(response, "Paid")
        self.assertContains(response, f'href="{reverse("complaint_create")}"')
        self.assertNotContains(response, "2500.00")

        resident_payment.status = MaintenancePayment.Status.UNPAID
        resident_payment.save(update_fields=("status",))
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["resident_maintenance_status"], "Due")
        self.assertEqual(response.context["maintenance_received"], Decimal("0.00"))
        self.assertEqual(response.context["maintenance_due"], Decimal("1500.00"))
        self.assertContains(response, "payment is still outstanding")

    def test_resident_dashboard_shows_due_when_current_month_payment_is_not_recorded(self):
        self.client.force_login(self.resident)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["resident_maintenance_payment"])
        self.assertEqual(response.context["resident_maintenance_status"], "Due")
        self.assertEqual(response.context["maintenance_due"], Decimal("1500.00"))
        self.assertContains(response, "No payment has been recorded for this month yet.")

    def test_staff_dashboard_does_not_show_resident_complaint_chart(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Your complaint status")

    def test_dashboard_shows_all_time_maintenance_due_and_received_for_all_roles(self):
        MaintenancePayment.objects.create(
            unit=self.unit,
            period=date(2026, 1, 1),
            amount="1500.00",
            status=MaintenancePayment.Status.PAID,
        )
        MaintenancePayment.objects.create(
            unit=self.other_unit,
            period=date(2026, 2, 1),
            amount="2000.00",
            status=MaintenancePayment.Status.UNPAID,
        )

        for dashboard_user in (self.resident, self.staff, self.admin):
            with self.subTest(role=dashboard_user.role):
                self.client.force_login(dashboard_user)
                response = self.client.get(reverse("dashboard"))

                self.assertEqual(response.status_code, 200)
                if dashboard_user.role == User.Role.RESIDENT:
                    self.assertEqual(response.context["maintenance_total"], 1500)
                    self.assertEqual(response.context["maintenance_received"], 0)
                    self.assertEqual(response.context["maintenance_due"], 1500)
                    self.assertEqual(
                        [
                            (segment["label"], segment["amount"])
                            for segment in response.context["maintenance_chart"]
                        ],
                        [("Received", Decimal("0.00")), ("Due", Decimal("1500.00"))],
                    )
                    self.assertContains(response, "Your maintenance")
                    self.assertContains(response, "Due")
                    self.assertNotContains(response, "₹2000.00")
                else:
                    self.assertEqual(response.context["maintenance_total"], 3500)
                    self.assertEqual(response.context["maintenance_received"], 1500)
                    self.assertEqual(response.context["maintenance_due"], 2000)
                    self.assertEqual(
                        [
                            (segment["label"], segment["amount"])
                            for segment in response.context["maintenance_chart"]
                        ],
                        [("Received", 1500), ("Due", 2000)],
                    )
                    self.assertContains(response, "Maintenance dues and receipts")
                    self.assertContains(response, "₹1500.00")
                    self.assertContains(response, "₹2000.00")

    def test_president_login_accepts_username_with_different_capitalization(self):
        president = User.objects.create_user(
            username="RUTHWIK",
            email="president@example.com",
            role=User.Role.ADMIN,
            password="test-admin-pass-456",
        )

        response = self.client.post(
            reverse("community_access_login"),
            {"username": "ruthwik", "password": "test-admin-pass-456"},
        )

        self.assertRedirects(response, reverse("community_access"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            president.pk,
        )

    def test_president_login_still_requires_the_correct_password(self):
        User.objects.create_user(
            username="RUTHWIK",
            email="president@example.com",
            role=User.Role.ADMIN,
            password="test-admin-pass-456",
        )

        response = self.client.post(
            reverse("community_access_login"),
            {"username": "ruthwik", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_president_login_rejects_resident_accounts(self):
        User.objects.create_user(
            username="regular-resident",
            email="regular-resident@example.com",
            role=User.Role.RESIDENT,
            password="test-resident-pass-456",
        )
        response = self.client.post(
            reverse("community_access_login"),
            {
                "username": "regular-resident",
                "password": "test-resident-pass-456",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "does not have administrator access")

    def test_resident_login_rejects_an_unregistered_owner_name(self):
        User.objects.create_user(
            username="ResidentCase",
            email="case@example.com",
            role=User.Role.RESIDENT,
            password="test-resident-pass-456",
        )

        response = self.client.post(
            reverse("login"),
            {"username": "residentcase", "password": "test-resident-pass-456"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    @patch("complaints.management.commands.repair_initial_logins.getpass")
    def test_initial_login_repair_command_sets_accounts_without_storing_passwords(
        self,
        mock_getpass,
    ):
        apartment = Apartment.objects.create(
            name="Vijetha Nivas",
            address="Ramnagar",
            city="Karimanagar",
        )
        unit = Unit.objects.create(
            apartment=apartment,
            unit_number="101",
            owner_name="Resident",
            resident=self.resident,
        )
        unlinked_unit = Unit.objects.create(
            apartment=apartment,
            unit_number="102",
            owner_name="Unlinked Resident",
        )
        existing_admin_password = self.admin.password
        output = StringIO()

        call_command("repair_initial_logins", stdout=output)
        self.assertIn("No accounts changed", output.getvalue())
        self.assertFalse(mock_getpass.called)

        mock_getpass.side_effect = ("180605", "180605", "Vijetha", "Vijetha")
        call_command("repair_initial_logins", "--apply", stdout=StringIO())

        self.resident.refresh_from_db()
        self.assertTrue(self.resident.check_password(unit.unit_number))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.password, existing_admin_password)
        president = User.objects.get(username__iexact="ruthwik")
        self.assertEqual(president.role, User.Role.ADMIN)
        self.assertTrue(president.check_password("180605"))
        unlinked_unit.refresh_from_db()
        self.assertIsNotNone(unlinked_unit.resident_id)
        self.assertTrue(unlinked_unit.resident.check_password(unlinked_unit.unit_number))
        for name in ("sandeep", "ganesh", "suresh", "deeraj", "ramesh"):
            staff_member = User.objects.get(username=name)
            self.assertEqual(staff_member.role, User.Role.STAFF)
            self.assertTrue(staff_member.check_password("Vijetha"))

    def test_resident_can_log_in_with_owner_name_and_flat_number_password(self):
        self.unit.owner_name = "RAVI"
        self.unit.unit_number = "101"
        self.unit.save(update_fields=("owner_name", "unit_number"))
        self.resident.set_password("101")
        self.resident.save(update_fields=("password",))

        response = self.client.post(
            reverse("login"),
            {"username": "ravi", "password": "101"},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            self.resident.pk,
        )

    def test_duplicate_owner_names_are_resolved_by_flat_number_password(self):
        self.unit.owner_name = "RAVI"
        self.unit.unit_number = "101"
        self.unit.save(update_fields=("owner_name", "unit_number"))
        self.resident.set_password("101")
        self.resident.save(update_fields=("password",))
        self.other_unit.owner_name = "RAVI"
        self.other_unit.unit_number = "102"
        self.other_unit.save(update_fields=("owner_name", "unit_number"))
        self.other_resident.set_password("102")
        self.other_resident.save(update_fields=("password",))

        response = self.client.post(
            reverse("login"),
            {"username": "RAVI", "password": "102"},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            self.other_resident.pk,
        )

    def test_password_visibility_toggle_is_available_on_both_login_pages(self):
        for url_name in ("login", "community_access_login"):
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'type="password"')
                self.assertContains(response, 'className = "password-visibility-toggle"')
                self.assertContains(response, 'input.type = showPassword ? "text" : "password"')
                self.assertContains(response, 'aria-label", showPassword ? "Hide password" : "Show password"')

    def test_resident_login_does_not_highlight_a_specific_flat(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Flat 106 resident")
        self.assertNotContains(response, "resident-login-hint")
        self.assertContains(response, "Owner name")
        self.assertContains(response, "flat number as the password")
        self.assertContains(response, "Apartment president?")
        self.assertContains(
            response,
            f'href="{reverse("community_access_login")}"',
        )

    def test_community_access_requires_login(self):
        response = self.client.get(reverse("community_access"))
        self.assertRedirects(
            response,
            f"{reverse('community_access_login')}?next={reverse('community_access')}",
        )

    def test_community_access_is_available_to_admin_role_without_django_staff(self):
        complaint = self.create_complaint()
        self.create_complaint(
            title="Completed kitchen tap",
            status=Complaint.Status.COMPLETED,
        )
        self.assertFalse(self.admin.is_staff)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("community_access"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vijetha Community Access")
        self.assertContains(response, complaint.title)
        self.assertEqual(
            list(response.context["units"]),
            [self.unit, self.other_unit],
        )
        self.assertContains(response, f"Flat {self.unit.unit_number}")
        self.assertContains(response, self.unit.owner_name)
        first_unit = response.context["units"][0]
        self.assertEqual(first_unit.complaint_count, 2)
        self.assertEqual(first_unit.open_complaint_count, 1)
        self.assertContains(response, "1 open · 2 total complaints")
        self.assertContains(response, f'href="{reverse("community_staff")}"')
        self.assertContains(
            response,
            f'<a class="community-directory-item" href="'
            f'{reverse("community_unit_detail", args=(self.unit.pk,))}" '
            f'aria-label="Open complaints for flat {self.unit.unit_number}">',
        )
        self.assertContains(
            response,
            f'href="{reverse("complaint_detail", args=(complaint.pk,))}"',
        )

    def test_admin_can_view_a_flats_complaint_count_and_issues(self):
        first_complaint = self.create_complaint(
            title="Leaking tap",
            description="The kitchen tap is leaking.",
        )
        self.create_complaint(
            title="Hallway light",
            description="The hallway light is not working.",
        )
        self.create_complaint(
            unit=self.other_unit,
            resident=self.other_resident,
            title="Other flat issue",
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("community_unit_detail", args=(self.unit.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["complaint_count"], 2)
        self.assertEqual(
            list(response.context["complaints"].values_list("pk", flat=True)),
            list(
                Complaint.objects.filter(unit=self.unit)
                .order_by("-created_at")
                .values_list("pk", flat=True)
            ),
        )
        self.assertContains(response, "<strong>2</strong> complaints")
        self.assertContains(response, first_complaint.title)
        self.assertContains(response, first_complaint.category.name)
        self.assertContains(response, first_complaint.description)
        self.assertNotContains(response, "Other flat issue")

    def test_admin_flat_detail_shows_zero_when_no_complaints_exist(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("community_unit_detail", args=(self.unit.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["complaint_count"], 0)
        self.assertContains(response, "No complaints have been raised for this flat.")

    def test_flat_complaints_are_admin_only(self):
        response = self.client.get(
            reverse("community_unit_detail", args=(self.unit.pk,))
        )
        self.assertRedirects(
            response,
            f"{reverse('community_access_login')}?next="
            f"{reverse('community_unit_detail', args=(self.unit.pk,))}",
        )

        self.client.force_login(self.resident)
        response = self.client.get(
            reverse("community_unit_detail", args=(self.unit.pk,))
        )
        self.assertEqual(response.status_code, 403)

    def test_community_access_is_for_admins_only(self):
        self.client.force_login(self.resident)
        response = self.client.get(reverse("community_access"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_staff_account_for_complaint_assignments(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("community_staff"),
            {
                "username": "maintenance.worker",
                "first_name": "Maintenance",
                "last_name": "Worker",
                "email": "worker@example.com",
                "phone": "555-0101",
                "password1": "Strong-maintenance-pass-987",
                "password2": "Strong-maintenance-pass-987",
            },
        )

        staff_member = User.objects.get(username="maintenance.worker")
        self.assertRedirects(response, reverse("community_staff"))
        self.assertEqual(staff_member.role, User.Role.STAFF)
        self.assertFalse(staff_member.is_staff)
        self.assertTrue(staff_member.check_password("Strong-maintenance-pass-987"))
        self.assertIn(staff_member, AssignmentForm().fields["assigned_to"].queryset)
        self.assertContains(
            self.client.get(reverse("community_staff")),
            "maintenance.worker",
        )

    def test_staff_management_is_for_admins_only(self):
        response = self.client.get(reverse("community_staff"))
        self.assertRedirects(
            response,
            f"{reverse('community_access_login')}?next={reverse('community_staff')}",
        )

        self.client.force_login(self.resident)
        response = self.client.get(reverse("community_staff"))
        self.assertEqual(response.status_code, 403)

    def test_staff_creation_rejects_duplicate_email(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("community_staff"),
            {
                "username": "another.worker",
                "first_name": "Another",
                "last_name": "Worker",
                "email": self.staff.email.upper(),
                "phone": "",
                "password1": "Strong-maintenance-pass-987",
                "password2": "Strong-maintenance-pass-987",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="another.worker").exists())
        self.assertContains(response, "An account with this email already exists.")

    def test_admin_can_view_fixed_monthly_staff_salaries(self):
        watchman = User.objects.create_user(
            username="watchman1",
            password="Strong-watchman-pass-987",
            email="watchman1@example.com",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.WATCHMAN,
        )
        watchman_two = User.objects.create_user(
            username="watchman2",
            password="Strong-watchman-pass-987",
            email="watchman2@example.com",
            role=User.Role.STAFF,
            staff_position=User.StaffPosition.WATCHMAN,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("community_access"))
        self.assertContains(response, "Monthly staff salaries")
        self.assertContains(response, "watchman1")
        self.assertContains(response, "watchman2")
        self.assertContains(response, "₹7500.00")
        self.assertContains(response, "₹10000.00")
        self.assertContains(response, "₹27500.00")
        self.assertEqual(watchman.salary, Decimal("10000.00"))
        self.assertEqual(watchman_two.salary, Decimal("10000.00"))
        self.assertEqual(self.staff.salary, Decimal("7500.00"))

    def test_staff_salary_stays_fixed_when_salary_is_changed_directly(self):
        self.staff.salary = Decimal("18500.50")
        self.staff.save(update_fields=("salary",))
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.salary, Decimal("7500.00"))

    def test_home_page_is_available_when_authenticated(self):
        self.client.force_login(self.resident)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Go to dashboard")
        self.assertContains(response, "Report an issue")
        self.assertContains(response, f'href="{reverse("complaint_create")}"')
        self.assertContains(response, f'href="{reverse("dashboard")}"')
        self.assertContains(response, f'href="{reverse("feedback_list")}"')
        self.assertContains(response, "Explore the Vijetha Community")
        self.assertNotContains(response, "Track progress")
        self.assertContains(
            response,
            f'href="{reverse("community_information")}"',
        )

    def test_admin_navigation_uses_custom_community_access_page(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Vijetha Community Access")
        self.assertContains(response, f'href="{reverse("community_access")}"')
        self.assertContains(response, 'class="brand-apartment-logo"')
        self.assertContains(response, 'class="brand-name">Vijetha Nivas')
        self.assertContains(response, "GATED COMMUNITY")
        self.assertNotContains(response, f'href="{reverse("admin:index")}"')

    def test_resident_brand_link_opens_community_information(self):
        self.client.force_login(self.resident)
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{reverse("community_information")}"')
        self.assertContains(response, 'class="brand-apartment-logo"')
        self.assertContains(response, 'class="brand-name">Vijetha Nivas')
        self.assertContains(response, "GATED COMMUNITY")

    def test_anonymous_brand_link_opens_community_information(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, f'href="{reverse("community_information")}"')
        response = self.client.get(reverse("community_information"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apartment facilities")
        self.assertContains(response, "Watchman security")
        self.assertContains(response, "45 homes")

    def test_anonymous_home_workflow_links_prompt_login_with_destination(self):
        response = self.client.get(reverse("home"))
        self.assertContains(
            response,
            f'href="{reverse("login")}?next={reverse("complaint_create")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("community_access_login")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("community_information")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("login")}?next={reverse("feedback_list")}"',
        )
        self.assertNotContains(response, "Track progress")
        self.assertNotContains(response, "President access required")

    def test_community_information_is_public_and_hides_resident_login(self):
        response = self.client.get(reverse("community_information"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apartment facilities")
        self.assertContains(response, "Watchman security")
        self.assertContains(response, "Maintenance team")
        self.assertContains(response, "Vehicle parking")
        self.assertContains(response, "Lift")
        self.assertContains(response, "CCTV cameras")
        self.assertContains(response, "Water supply")
        self.assertContains(response, "Power backup")
        self.assertContains(response, "Garden")
        self.assertContains(response, "play area for children")
        self.assertContains(response, "Fire safety")
        self.assertContains(response, "45 homes")
        self.assertNotContains(response, f'href="{reverse("login")}"')
        self.assertContains(response, f'href="{reverse("staff_login")}"')
        self.assertContains(
            response,
            f'href="{reverse("community_access_login")}"',
        )

    def test_resolved_complaint_detail_shows_five_point_feedback_choices(self):
        complaint = self.create_complaint(status=Complaint.Status.RESOLVED)
        self.client.force_login(self.resident)
        response = self.client.get(
            reverse("complaint_detail", args=(complaint.pk,))
        )
        self.assertEqual(response.status_code, 200)
        for rating in ("1 - Poor", "2 - Fair", "3 - Good", "4 - Very good", "5 - Excellent"):
            self.assertContains(response, rating)

    def test_public_registration_is_disabled(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new-resident",
                "first_name": "New",
                "last_name": "Resident",
                "email": "new@example.com",
                "phone": "555-0100",
                "password1": "Strong-password-987",
                "password2": "Strong-password-987",
            },
        )
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(User.objects.filter(username="new-resident").exists())

    def test_register_option_is_not_visible(self):
        for path in (reverse("home"), reverse("login")):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, reverse("register"))
            self.assertNotContains(response, "Register as a resident")
