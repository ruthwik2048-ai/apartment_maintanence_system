from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AccountPasswordResetForm,
    AssignmentForm,
    CaseInsensitiveAuthenticationForm,
    ComplaintForm,
    CommunityAccountUpdateForm,
    FeedbackForm,
    MaintenanceStaffCreationForm,
    ResidentAccountCreationForm,
    WorkUpdateForm,
)
from .models import (
    MONTHLY_MAINTENANCE_FEE,
    Category,
    Complaint,
    Feedback,
    MaintenancePayment,
    Notification,
    Unit,
    WorkLog,
)

User = get_user_model()


def home(request):
    return render(request, "complaints/home.html")


def community_information(request):
    return render(request, "complaints/community_information.html")


def registration_closed(request):
    messages.info(
        request,
        "Public registration is disabled. Please contact the apartment administrator for an account.",
    )
    return redirect("login")


def community_access_login(request):
    if request.user.is_authenticated:
        if request.user.role == User.Role.ADMIN or request.user.is_superuser:
            return redirect("community_access")
        raise PermissionDenied("Only apartment administrators can sign in to this portal.")

    form = CaseInsensitiveAuthenticationForm(
        request,
        data=request.POST if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if user.role != User.Role.ADMIN and not user.is_superuser:
            form.add_error(None, "This account does not have administrator access.")
        else:
            login(request, user)
            return redirect("community_access")
    return render(
        request,
        "complaints/community_access_login.html",
        {"form": form},
    )


def staff_login(request):
    if request.user.is_authenticated:
        if request.user.role == User.Role.STAFF:
            return redirect(
                "maintenance_collection"
                if request.user.can_manage_maintenance_collection
                else "staff_portal"
            )
        raise PermissionDenied("Only maintenance staff can access staff sign-in.")

    form = CaseInsensitiveAuthenticationForm(
        request,
        data=request.POST if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        staff_member = form.get_user()
        if staff_member.role != User.Role.STAFF:
            form.add_error(None, "This account does not have maintenance staff access.")
        else:
            login(request, staff_member)
            return redirect(
                "maintenance_collection"
                if staff_member.can_manage_maintenance_collection
                else "staff_portal"
            )
    return render(request, "complaints/staff_login.html", {"form": form})


@login_required(login_url="staff_login")
def maintenance_collection(request):
    if not request.user.can_manage_maintenance_collection:
        raise PermissionDenied("Only watchmen can manage maintenance fee collection.")

    period = timezone.localdate().replace(day=1)
    units = list(
        Unit.objects.filter(apartment__is_active=True)
        .select_related("apartment")
        .order_by("apartment__name", "unit_number")
    )
    payments = {
        payment.unit_id: payment
        for payment in MaintenancePayment.objects.filter(
            unit__in=units,
            period=period,
        )
    }

    if request.method == "POST":
        try:
            unit_id = int(request.POST.get("unit_id", ""))
        except (TypeError, ValueError):
            messages.error(request, "Choose a valid flat.")
            return redirect("maintenance_collection")

        unit = get_object_or_404(
            Unit.objects.filter(apartment__is_active=True),
            pk=unit_id,
        )
        status = request.POST.get("status")
        if status not in MaintenancePayment.Status.values:
            messages.error(request, "Choose a valid payment status.")
            return redirect("maintenance_collection")

        paid_at = timezone.now() if status == MaintenancePayment.Status.PAID else None
        payment, created = MaintenancePayment.objects.get_or_create(
            unit=unit,
            period=period,
            defaults={
                "amount": MONTHLY_MAINTENANCE_FEE,
                "status": status,
                "recorded_by": request.user,
                "paid_at": paid_at,
            },
        )
        if not created:
            payment.status = status
            payment.recorded_by = request.user
            payment.paid_at = paid_at
            payment.save(update_fields=("status", "recorded_by", "paid_at", "updated_at"))
        messages.success(
            request,
            f"Flat {unit.unit_number} marked {payment.get_status_display().lower()} "
            f"for {period:%B %Y}.",
        )
        return redirect(f"{reverse('maintenance_collection')}#flat-{unit.pk}")

    today = timezone.localdate()
    rows = []
    overdue_count = 0
    for unit in units:
        payment = payments.get(unit.pk)
        is_paid = payment is not None and payment.status == MaintenancePayment.Status.PAID
        is_overdue = (
            payment is not None
            and payment.status == MaintenancePayment.Status.UNPAID
            and today > payment.period.replace(day=2)
        )
        if is_overdue:
            overdue_count += 1
        rows.append(
            {
                "unit": unit,
                "payment": payment,
                "is_paid": is_paid,
                "is_overdue": is_overdue,
            }
        )
    paid_count = sum(row["is_paid"] for row in rows)
    total_count = len(rows)
    return render(
        request,
        "complaints/maintenance_collection.html",
        {
            "rows": rows,
            "period": period,
            "period_label": period.strftime("%B %Y"),
            "paid_count": paid_count,
            "unpaid_count": total_count - paid_count,
            "total_count": total_count,
            "collection_percent": round(paid_count * 100 / total_count) if total_count else 0,
            "total_collected": MONTHLY_MAINTENANCE_FEE * paid_count,
            "total_due": MONTHLY_MAINTENANCE_FEE * (total_count - paid_count),
            "has_overdue": overdue_count > 0,
            "overdue_count": overdue_count,
        },
    )


@login_required(login_url="staff_login")
def staff_portal(request):
    if request.user.role != User.Role.STAFF:
        raise PermissionDenied("Only maintenance staff can access the staff work portal.")

    completed_statuses = (
        Complaint.Status.COMPLETED,
        Complaint.Status.SUCCESSFUL,
        Complaint.Status.RESOLVED,
        Complaint.Status.CLOSED,
    )
    completed_visibility_cutoff = timezone.now() - timedelta(hours=24)
    complaints = (
        Complaint.objects.filter(assigned_to=request.user)
        .exclude(
            status__in=completed_statuses,
            resolved_at__lte=completed_visibility_cutoff,
        )
        .select_related("unit__apartment", "category", "resident")
    )
    emergency_complaints = (
        Complaint.objects.filter(
            is_emergency=True,
            status__in=(
                Complaint.Status.RAISED,
                Complaint.Status.ASSIGNED,
                Complaint.Status.PENDING,
                Complaint.Status.IN_PROGRESS,
                Complaint.Status.REOPENED,
            ),
        )
        .select_related("unit__apartment", "category", "resident")
        .order_by("-created_at")
    )
    summary = complaints.aggregate(
        total=Count("pk"),
        pending=Count(
            "pk",
            filter=Q(
                status__in=(
                    Complaint.Status.ASSIGNED,
                    Complaint.Status.PENDING,
                    Complaint.Status.REOPENED,
                )
            ),
        ),
        in_progress=Count("pk", filter=Q(status=Complaint.Status.IN_PROGRESS)),
        completed=Count(
            "pk",
            filter=Q(
                status__in=(
                    Complaint.Status.COMPLETED,
                    Complaint.Status.SUCCESSFUL,
                    Complaint.Status.RESOLVED,
                    Complaint.Status.CLOSED,
                )
            ),
        ),
        successful=Count("pk", filter=Q(status=Complaint.Status.SUCCESSFUL)),
    )
    return render(
        request,
        "complaints/staff_portal.html",
        {
            "complaints": complaints.order_by("-created_at"),
            "emergency_complaints": emergency_complaints,
            "emergency_notifications": request.user.notifications.filter(
                title="Emergency resident report",
            )[:10],
            "summary": summary,
        },
    )


@login_required
def dashboard(request):
    resident_unit = None

    if request.user.role == User.Role.RESIDENT:
        resident_unit = (
            request.user.units
            .select_related("apartment")
            .order_by("id")
            .first()
        )
        resident_maintenance_period = timezone.localdate().replace(day=1)
        if resident_unit is not None:
            resident_maintenance_payment = MaintenancePayment.objects.filter(
                unit=resident_unit,
                period=resident_maintenance_period,
            ).first()
        resident_maintenance_status = (
            "Paid"
            if resident_maintenance_payment
            and resident_maintenance_payment.status == MaintenancePayment.Status.PAID
            else "Due"
        )

    complaints = Complaint.objects.select_related(
        "unit__apartment",
        "category",
        "resident",
        "assigned_to",
    )
    if request.user.role == User.Role.RESIDENT and not request.user.is_superuser:
        complaints = complaints.filter(resident=request.user)
    elif request.user.role == User.Role.STAFF:
        complaints = complaints.filter(assigned_to=request.user)

    summary = complaints.aggregate(
        total=Count("pk"),
        pending=Count(
            "pk",
            filter=Q(
                status__in=(
                    Complaint.Status.RAISED,
                    Complaint.Status.ASSIGNED,
                    Complaint.Status.PENDING,
                    Complaint.Status.REOPENED,
                )
            ),
        ),
        in_progress=Count("pk", filter=Q(status=Complaint.Status.IN_PROGRESS)),
        resolved=Count(
            "pk",
            filter=Q(
                status__in=(
                    Complaint.Status.COMPLETED,
                    Complaint.Status.SUCCESSFUL,
                    Complaint.Status.RESOLVED,
                    Complaint.Status.CLOSED,
                )
            ),
        ),
    )
    complaint_chart = []
    if request.user.role == User.Role.RESIDENT and not request.user.is_superuser:
        chart_categories = (
            ("Pending", summary["pending"], "#f59e0b"),
            ("In progress", summary["in_progress"], "#0ea5e9"),
            ("Resolved", summary["resolved"], "#10b981"),
        )
        circumference = 339.292
        offset = 0.0
        for label, count, color in chart_categories:
            percentage = count * 100 / summary["total"] if summary["total"] else 0
            length = circumference * percentage / 100
            complaint_chart.append(
                {
                    "label": label,
                    "count": count,
                    "percentage": round(percentage),
                    "length": length,
                    "offset": offset,
                    "color": color,
                }
            )
            offset += length

    if request.user.role == User.Role.RESIDENT and resident_unit is not None:
        maintenance_total = (
            resident_maintenance_payment.amount
            if resident_maintenance_payment
            else MONTHLY_MAINTENANCE_FEE
        )
        maintenance_received = (
            maintenance_total
            if resident_maintenance_status == "Paid"
            else Decimal("0.00")
        )
    else:
        maintenance_totals = MaintenancePayment.objects.filter(
            unit__apartment__is_active=True,
        ).aggregate(
            total=Sum("amount"),
            received=Sum(
                "amount",
                filter=Q(status=MaintenancePayment.Status.PAID),
            ),
        )
        maintenance_total = maintenance_totals["total"] or Decimal("0.00")
        maintenance_received = maintenance_totals["received"] or Decimal("0.00")
    maintenance_due = maintenance_total - maintenance_received
    maintenance_chart = []
    circumference = 339.292
    offset = 0.0
    for label, amount, color in (
        ("Received", maintenance_received, "#10b981"),
        ("Due", maintenance_due, "#f59e0b"),
    ):
        percentage = amount * 100 / maintenance_total if maintenance_total else 0
        length = circumference * float(percentage) / 100
        maintenance_chart.append(
            {
                "label": label,
                "amount": amount,
                "percentage": round(percentage),
                "length": length,
                "offset": offset,
                "color": color,
            }
        )
        offset += length

    average_rating = Feedback.objects.aggregate(average=Avg("rating"))["average"] or 0
    return render(
        request,
        "complaints/dashboard.html",
        {
            "complaints": complaints,
            "summary": summary,
            "complaint_chart": complaint_chart,
            "maintenance_chart": maintenance_chart,
            "maintenance_total": maintenance_total,
            "maintenance_received": maintenance_received,
            "maintenance_due": maintenance_due,
            "resident_maintenance_payment": resident_maintenance_payment,
            "resident_maintenance_period": resident_maintenance_period,
            "resident_maintenance_status": resident_maintenance_status,
            "average_rating": round(average_rating, 2),
            "notifications": request.user.notifications.filter(is_read=False)[:5],
            "resident_unit": resident_unit,
            "display_name": (
                resident_unit.owner_name
                if resident_unit and resident_unit.owner_name
                else request.user.get_full_name() or request.user.username
            ),
        },
    )


@login_required(login_url="community_access_login")
def community_access(request):
    if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Only apartment administrators can access this page.")

    complaints = Complaint.objects.select_related(
        "unit__apartment",
        "resident",
        "category",
        "assigned_to",
    )
    summary = complaints.aggregate(
        total=Count("pk"),
        pending=Count(
            "pk",
            filter=Q(
                status__in=(
                    Complaint.Status.RAISED,
                    Complaint.Status.ASSIGNED,
                    Complaint.Status.PENDING,
                    Complaint.Status.REOPENED,
                )
            ),
        ),
        in_progress=Count("pk", filter=Q(status=Complaint.Status.IN_PROGRESS)),
        resolved=Count(
            "pk",
            filter=Q(
                status__in=(
                    Complaint.Status.COMPLETED,
                    Complaint.Status.SUCCESSFUL,
                    Complaint.Status.RESOLVED,
                    Complaint.Status.CLOSED,
                )
            ),
        ),
    )
    staff_members = list(
        User.objects.filter(role=User.Role.STAFF, is_active=True).order_by(
            "first_name",
            "last_name",
            "username",
        )
    )
    current_period = timezone.localdate().replace(day=1)
    units = list(
        Unit.objects.filter(apartment__is_active=True)
        .select_related("apartment", "resident")
        .annotate(
            complaint_count=Count("complaints"),
            open_complaint_count=Count(
                "complaints",
                filter=Q(
                    complaints__status__in=(
                        Complaint.Status.RAISED,
                        Complaint.Status.ASSIGNED,
                        Complaint.Status.PENDING,
                        Complaint.Status.IN_PROGRESS,
                        Complaint.Status.REOPENED,
                    )
                ),
            ),
        )
        .order_by("apartment__name", "unit_number")
    )
    payments_by_unit = {
        payment.unit_id: payment
        for payment in MaintenancePayment.objects.filter(
            unit__in=units,
            period=current_period,
        )
    }
    maintenance_rows = []
    for unit in units:
        payment = payments_by_unit.get(unit.pk)
        is_paid = bool(payment and payment.status == MaintenancePayment.Status.PAID)
        maintenance_rows.append(
            {
                "unit": unit,
                "payment": payment,
                "is_paid": is_paid,
                "amount": payment.amount if payment else MONTHLY_MAINTENANCE_FEE,
            }
        )
    paid_rows = [row for row in maintenance_rows if row["is_paid"]]
    unpaid_rows = [row for row in maintenance_rows if not row["is_paid"]]
    return render(
        request,
        "complaints/community_access.html",
        {
            "complaints": complaints.order_by("-created_at"),
            "summary": summary,
            "staff_members": staff_members,
            "monthly_salary_total": sum(
                (staff_member.salary for staff_member in staff_members),
                Decimal("0.00"),
            ),
            "units": units,
            "current_period": current_period,
            "maintenance_rows": maintenance_rows,
            "maintenance_paid_count": len(paid_rows),
            "maintenance_due_count": len(unpaid_rows),
            "maintenance_received_total": sum(
                (row["amount"] for row in paid_rows),
                Decimal("0.00"),
            ),
            "maintenance_due_total": sum(
                (row["amount"] for row in unpaid_rows),
                Decimal("0.00"),
            ),
        },
    )


@login_required(login_url="community_access_login")
def community_accounts(request):
    if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Only apartment administrators can manage accounts.")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_resident":
            unit = get_object_or_404(
                Unit.objects.select_related("apartment"),
                pk=request.POST.get("unit_id"),
                apartment__is_active=True,
            )
            if unit.resident_id:
                messages.error(request, f"Flat {unit.unit_number} already has a resident account.")
                return redirect("community_accounts")
            form = ResidentAccountCreationForm(request.POST)
            if form.is_valid():
                username = f"resident-{unit.pk}"
                if User.objects.filter(username__iexact=username).exists():
                    messages.error(
                        request,
                        f"Cannot create the account for flat {unit.unit_number}: "
                        f"username {username!r} is already in use.",
                    )
                    return redirect("community_accounts")
                with transaction.atomic():
                    resident = User(
                        username=username,
                        first_name=form.cleaned_data["first_name"].strip(),
                        last_name=form.cleaned_data["last_name"].strip(),
                        email=form.cleaned_data["email"],
                        phone=form.cleaned_data["phone"].strip(),
                        role=User.Role.RESIDENT,
                    )
                    resident.set_password(unit.unit_number)
                    resident.save()
                    unit.resident = resident
                    unit.save(update_fields=("resident",))
                messages.success(
                    request,
                    f"Resident account for flat {unit.unit_number} created. "
                    "The initial password is the flat number.",
                )
            else:
                messages.error(
                    request,
                    "; ".join(
                        f"{field}: {error}"
                        for field, errors in form.errors.items()
                        for error in errors
                    ),
                )
            return redirect("community_accounts")

        if action in {"update_account", "reset_password", "toggle_active"}:
            account = get_object_or_404(
                User,
                pk=request.POST.get("user_id"),
                role__in=(User.Role.RESIDENT, User.Role.STAFF),
            )
            unit = (
                account.units.select_related("apartment")
                .filter(apartment__is_active=True)
                .order_by("unit_number")
                .first()
                if account.role == User.Role.RESIDENT
                else None
            )

            if action == "update_account":
                form = CommunityAccountUpdateForm(
                    request.POST,
                    user=account,
                    unit=unit,
                )
                if form.is_valid():
                    with transaction.atomic():
                        form.save()
                    messages.success(request, f"Account for {account} updated.")
                else:
                    messages.error(
                        request,
                        "; ".join(
                            f"{field}: {error}"
                            for field, errors in form.errors.items()
                            for error in errors
                        ),
                    )
            elif action == "reset_password":
                form = AccountPasswordResetForm(request.POST)
                if form.is_valid():
                    account.set_password(form.cleaned_data["password"])
                    account.save(update_fields=("password",))
                    messages.success(request, f"Password reset for {account}.")
                else:
                    messages.error(
                        request,
                        "; ".join(
                            f"{field}: {error}"
                            for field, errors in form.errors.items()
                            for error in errors
                        ),
                    )
            else:
                account.is_active = not account.is_active
                account.save(update_fields=("is_active",))
                state = "activated" if account.is_active else "deactivated"
                messages.success(request, f"Account for {account} {state}.")
            return redirect("community_accounts")

        messages.error(request, "Choose a valid account management action.")
        return redirect("community_accounts")

    units = list(
        Unit.objects.filter(apartment__is_active=True)
        .select_related("apartment", "resident")
        .order_by("apartment__name", "unit_number")
    )
    resident_accounts = []
    for unit in units:
        resident_accounts.append(
            {
                "unit": unit,
                "edit_form": (
                    CommunityAccountUpdateForm(user=unit.resident, unit=unit)
                    if unit.resident_id
                    else None
                ),
                "password_form": (
                    AccountPasswordResetForm() if unit.resident_id else None
                ),
                "create_form": (
                    ResidentAccountCreationForm() if not unit.resident_id else None
                ),
            }
        )
    staff_accounts = list(
        User.objects.filter(role=User.Role.STAFF).order_by(
            "first_name",
            "last_name",
            "username",
        )
    )
    for staff_member in staff_accounts:
        staff_member.edit_form = CommunityAccountUpdateForm(user=staff_member)
        staff_member.password_form = AccountPasswordResetForm()

    return render(
        request,
        "complaints/community_accounts.html",
        {
            "resident_accounts": resident_accounts,
            "staff_accounts": staff_accounts,
        },
    )


@login_required(login_url="community_access_login")
def community_staff(request):
    if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Only apartment administrators can manage maintenance staff.")

    form = MaintenanceStaffCreationForm(
        data=request.POST if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        staff_member = form.save(commit=False)
        staff_member.role = User.Role.STAFF
        staff_member.save()
        messages.success(
            request,
            f"Maintenance staff account for {staff_member.get_full_name() or staff_member.username} created.",
        )
        return redirect("community_staff")

    staff_members = list(
        User.objects.filter(
            role=User.Role.STAFF,
            is_active=True,
        ).order_by("first_name", "last_name", "username")
    )
    return render(
        request,
        "complaints/community_staff.html",
        {
            "form": form,
            "staff_members": staff_members,
        },
    )


@login_required(login_url="community_access_login")
def community_unit_detail(request, unit_id):
    if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Only apartment administrators can view flat complaints.")

    unit = get_object_or_404(
        Unit.objects.select_related("apartment", "resident"),
        pk=unit_id,
        apartment__is_active=True,
    )
    complaints = (
        Complaint.objects.filter(unit=unit)
        .select_related("resident", "category")
        .order_by("-created_at")
    )
    return render(
        request,
        "complaints/community_unit_detail.html",
        {
            "unit": unit,
            "complaints": complaints,
            "complaint_count": complaints.count(),
        },
    )


@login_required
def feedback_list(request):
    if request.user.role != User.Role.RESIDENT:
        raise PermissionDenied("Only residents can rate completed maintenance work.")
    complaints = (
        Complaint.objects.filter(
            resident=request.user,
            status__in=(
                Complaint.Status.COMPLETED,
                Complaint.Status.SUCCESSFUL,
                Complaint.Status.RESOLVED,
                Complaint.Status.CLOSED,
            ),
            feedback__isnull=True,
        )
        .select_related("unit__apartment", "category")
        .order_by("-resolved_at", "-created_at")
    )
    return render(
        request,
        "complaints/feedback_list.html",
        {"complaints": complaints},
    )


@login_required
def complaint_create(request):
    if request.user.role != User.Role.RESIDENT:
        raise PermissionDenied("Only residents can submit complaints.")
    return handle_complaint_submission(request, "complaints/complaint_form.html")


@login_required
def resident_help(request):
    if request.user.role != User.Role.RESIDENT:
        raise PermissionDenied("Only residents can use resident help.")
    return handle_complaint_submission(request, "complaints/resident_help.html")


@login_required
def resident_help_staff(request):
    if request.user.role != User.Role.RESIDENT:
        raise PermissionDenied("Only residents can view maintenance contacts.")

    is_emergency = request.GET.get("emergency") == "true"
    category_id = request.GET.get("category")
    category = None
    if category_id:
        try:
            category = Category.objects.get(pk=category_id, is_active=True)
        except (Category.DoesNotExist, ValueError):
            return JsonResponse({"error": "Select a valid issue category."}, status=400)

    staff_members = User.objects.filter(
        role=User.Role.STAFF,
        is_active=True,
    )
    if not is_emergency and category:
        category_name = category.name.casefold()
        if "electric" in category_name:
            staff_members = staff_members.filter(
                staff_position=User.StaffPosition.ELECTRICIAN,
            )
        elif any(term in category_name for term in ("plumb", "water", "drain")):
            staff_members = staff_members.filter(
                staff_position=User.StaffPosition.PLUMBER,
            )
        elif any(term in category_name for term in ("fire", "safety")):
            staff_members = staff_members.filter(
                staff_position=User.StaffPosition.FIRE_WORK,
            )

    return JsonResponse(
        {
            "emergency": is_emergency,
            "staff": [
                {
                    "name": staff.get_full_name() or staff.username,
                    "position": staff.get_staff_position_display()
                    or "Maintenance staff",
                    "phone": staff.phone,
                    "email": staff.email,
                }
                for staff in staff_members.order_by(
                    "first_name",
                    "last_name",
                    "username",
                )
            ],
        }
    )


def handle_complaint_submission(request, template_name):
    if request.method == "POST":
        form = ComplaintForm(request.POST, request.FILES)
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.resident = request.user
            complaint.created_by = request.user
            complaint.save()
            Notification.objects.create(
                recipient=request.user,
                title="Complaint Submitted",
                message=f"Your complaint '{complaint.title}' has been submitted.",
                complaint=complaint,
            )
            if complaint.is_emergency:
                staff_members = list(User.objects.filter(
                    role=User.Role.STAFF,
                    is_active=True,
                ))
                Notification.objects.bulk_create(
                    [
                        Notification(
                            recipient=staff_member,
                            title="Emergency resident report",
                            message=(
                                f"{complaint.resident.get_full_name() or complaint.resident.username} "
                                f"reported an emergency: {complaint.title}. "
                                f"Open complaint #{complaint.pk}."
                            ),
                            complaint=complaint,
                        )
                        for staff_member in staff_members
                    ]
                )
                messages.warning(
                    request,
                    (
                        "Emergency report submitted. Active maintenance staff have been notified."
                        if staff_members
                        else "Emergency report submitted, but there are no active maintenance staff accounts to notify."
                    ),
                )
            else:
                messages.success(request, "Your complaint has been submitted.")
            return redirect("complaint_detail", complaint_id=complaint.pk)
    else:
        form = ComplaintForm()
    return render(request, template_name, {"form": form})


@login_required
def complaint_detail(request, complaint_id):
    complaint = get_object_or_404(
        Complaint.objects.select_related(
            "unit__apartment",
            "category",
            "resident",
            "assigned_to",
        ).prefetch_related("work_logs__performed_by", "notifications"),
        pk=complaint_id,
    )
    ensure_can_view(request.user, complaint)
    if request.user.role == User.Role.STAFF and complaint.is_emergency:
        request.user.notifications.filter(
            complaint=complaint,
            title="Emergency resident report",
            is_read=False,
        ).update(is_read=True)
    can_manage = request.user.role == User.Role.ADMIN or request.user.is_superuser
    can_update = (
        request.user.role == User.Role.STAFF
        and (
            complaint.assigned_to_id == request.user.pk
            or (complaint.is_emergency and complaint.assigned_to_id is None)
        )
    )
    can_reopen = (
        request.user.role == User.Role.RESIDENT
        and complaint.resident_id == request.user.pk
        and complaint.status
        in (
            Complaint.Status.COMPLETED,
            Complaint.Status.SUCCESSFUL,
            Complaint.Status.RESOLVED,
            Complaint.Status.CLOSED,
        )
    )
    feedback_form = None
    if (
        request.user.role == User.Role.RESIDENT
        and complaint.resident_id == request.user.pk
        and complaint.status
        in (
            Complaint.Status.COMPLETED,
            Complaint.Status.SUCCESSFUL,
            Complaint.Status.RESOLVED,
            Complaint.Status.CLOSED,
        )
        and not hasattr(complaint, "feedback")
    ):
        feedback_form = FeedbackForm()
    return render(
        request,
        "complaints/complaint_detail.html",
        {
            "complaint": complaint,
            "can_manage": can_manage,
            "can_update": can_update,
            "can_reopen": can_reopen,
            "assignment_form": AssignmentForm(instance=complaint) if can_manage else None,
            "update_form": WorkUpdateForm(complaint=complaint) if can_update else None,
            "feedback_form": feedback_form,
        },
    )


@login_required
@require_POST
def assign_complaint(request, complaint_id):
    if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
        raise PermissionDenied("Only administrators can assign complaints.")
    complaint = get_object_or_404(Complaint, pk=complaint_id)
    previous_assignee = complaint.assigned_to
    form = AssignmentForm(request.POST, instance=complaint)
    if form.is_valid():
        complaint = form.save(commit=False)
        is_reassignment = (
            previous_assignee is not None
            and previous_assignee.pk != complaint.assigned_to_id
        )
        if previous_assignee is None:
            complaint.status = Complaint.Status.ASSIGNED
        complaint.assigned_at = timezone.now()
        complaint.save()
        Notification.objects.create(
            recipient=complaint.assigned_to,
            title="Complaint Reassigned" if is_reassignment else "New Complaint Assigned",
            message=(
                f"Complaint #{complaint.pk} has been reassigned to you."
                if is_reassignment
                else f"Complaint #{complaint.pk} has been assigned to you."
            ),
            complaint=complaint,
        )
        if is_reassignment:
            Notification.objects.create(
                recipient=previous_assignee,
                title="Complaint Reassigned",
                message=f"Complaint #{complaint.pk} has been reassigned to another staff member.",
                complaint=complaint,
            )
        Notification.objects.create(
            recipient=complaint.resident,
            title="Complaint Reassigned" if is_reassignment else "Complaint Assigned",
            message=(
                f"Your complaint #{complaint.pk} has been reassigned to "
                f"{complaint.assigned_to.get_full_name() or complaint.assigned_to.username}."
                if is_reassignment
                else f"Your complaint #{complaint.pk} has been assigned to maintenance staff."
            ),
            complaint=complaint,
        )
        messages.success(
            request,
            "Complaint reassigned to another staff member."
            if is_reassignment
            else "Complaint assigned to maintenance staff.",
        )
    else:
        messages.error(request, "Choose an active maintenance staff member.")
    return redirect("complaint_detail", complaint_id=complaint.pk)


@login_required
@require_POST
def update_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, pk=complaint_id)
    can_respond_to_emergency = (
        complaint.is_emergency
        and complaint.assigned_to_id is None
        and request.user.role == User.Role.STAFF
    )
    if request.user.role != User.Role.STAFF or (
        complaint.assigned_to_id != request.user.pk and not can_respond_to_emergency
    ):
        raise PermissionDenied("Only the assigned maintenance staff can update this complaint.")
    form = WorkUpdateForm(request.POST, request.FILES, complaint=complaint)
    if form.is_valid():
        work_log = form.save(commit=False)
        work_log.complaint = complaint
        work_log.performed_by = request.user
        complaint.status = work_log.status
        if can_respond_to_emergency:
            complaint.assigned_to = request.user
            complaint.assigned_at = timezone.now()
        if complaint.status in (
            Complaint.Status.COMPLETED,
            Complaint.Status.SUCCESSFUL,
            Complaint.Status.RESOLVED,
        ):
            complaint.resolved_at = timezone.now()
        complaint.save()
        work_log.save()
        Notification.objects.create(
            recipient=complaint.resident,
            title="Complaint Status Updated",
            message=f"Complaint #{complaint.pk}: {complaint.get_status_display()}",
            complaint=complaint,
        )
        messages.success(request, "Complaint status updated.")
    else:
        messages.error(request, "Select a valid next status and enter a work update.")
    return redirect("complaint_detail", complaint_id=complaint.pk)


@login_required
@require_POST
def reopen_complaint(request, complaint_id):
    complaint = get_object_or_404(Complaint, pk=complaint_id)
    if request.user.role != User.Role.RESIDENT or complaint.resident_id != request.user.pk:
        raise PermissionDenied("Only the resident who submitted this complaint can reopen it.")
    if complaint.status not in (
        Complaint.Status.COMPLETED,
        Complaint.Status.SUCCESSFUL,
        Complaint.Status.RESOLVED,
        Complaint.Status.CLOSED,
    ):
        messages.error(request, "Only a resolved or closed complaint can be reopened.")
        return redirect("complaint_detail", complaint_id=complaint.pk)
    complaint.status = Complaint.Status.REOPENED
    complaint.resolved_at = None
    complaint.save()
    WorkLog.objects.create(
        complaint=complaint,
        performed_by=request.user,
        comment="Complaint reopened by resident.",
        status=Complaint.Status.REOPENED,
    )
    if complaint.assigned_to:
        Notification.objects.create(
            recipient=complaint.assigned_to,
            title="Complaint Reopened",
            message=f"Complaint #{complaint.pk} has been reopened.",
            complaint=complaint,
        )
    messages.success(request, "Complaint reopened.")
    return redirect("complaint_detail", complaint_id=complaint.pk)


@login_required
@require_POST
def submit_feedback(request, complaint_id):
    complaint = get_object_or_404(Complaint, pk=complaint_id)
    if request.user.role != User.Role.RESIDENT or complaint.resident_id != request.user.pk:
        raise PermissionDenied("Only the complaint's resident can provide feedback.")
    if complaint.status not in (
        Complaint.Status.COMPLETED,
        Complaint.Status.SUCCESSFUL,
        Complaint.Status.RESOLVED,
        Complaint.Status.CLOSED,
    ):
        messages.error(request, "Feedback is available after resolution.")
        return redirect("complaint_detail", complaint_id=complaint.pk)
    if Feedback.objects.filter(complaint=complaint).exists():
        messages.error(request, "Feedback has already been submitted.")
        return redirect("complaint_detail", complaint_id=complaint.pk)
    form = FeedbackForm(request.POST)
    if form.is_valid():
        feedback = form.save(commit=False)
        feedback.complaint = complaint
        feedback.resident = request.user
        feedback.save()
        messages.success(request, "Thank you for your feedback.")
    else:
        messages.error(request, "Please submit a rating from 1 to 5.")
    return redirect("complaint_detail", complaint_id=complaint.pk)


def ensure_can_view(user, complaint):
    if user.is_superuser or user.role == User.Role.ADMIN:
        return
    if user.role == User.Role.RESIDENT and complaint.resident_id == user.pk:
        return
    if user.role == User.Role.STAFF and complaint.assigned_to_id == user.pk:
        return
    if user.role == User.Role.STAFF and complaint.is_emergency:
        return
    raise PermissionDenied("You do not have permission to view this complaint.")
