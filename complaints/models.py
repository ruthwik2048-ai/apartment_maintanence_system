from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        RESIDENT = "resident", "Resident"
        STAFF = "staff", "Maintenance Staff"
        ADMIN = "admin", "Administrator"

    class StaffPosition(models.TextChoices):
        ELECTRICIAN = "electrician", "Electrician"
        PLUMBER = "plumber", "Plumber"
        WATCHMAN = "watchman", "Watchman"
        FIRE_WORK = "fire_work", "Fire work"
        OTHER = "other", "Other maintenance staff"

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.RESIDENT)
    salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    staff_position = models.CharField(
        max_length=20,
        choices=StaffPosition.choices,
        blank=True,
    )

    def __str__(self):
        return self.get_full_name() or self.username

    def save(self, *args, **kwargs):
        if self.role == self.Role.STAFF:
            self.salary = (
                Decimal("10000.00")
                if self.staff_position == self.StaffPosition.WATCHMAN
                else Decimal("7500.00")
            )
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and {
                "role",
                "staff_position",
                "salary",
            }.intersection(update_fields):
                kwargs["update_fields"] = set(update_fields) | {"salary"}
        super().save(*args, **kwargs)

    @property
    def can_manage_maintenance_collection(self):
        return (
            self.role == self.Role.STAFF
            and self.staff_position == self.StaffPosition.WATCHMAN
        )


class Apartment(models.Model):
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    total_blocks = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Unit(models.Model):
    class Status(models.TextChoices):
        OCCUPIED = "occupied", "Occupied"
        VACANT = "vacant", "Vacant"

    apartment = models.ForeignKey(Apartment, on_delete=models.CASCADE, related_name="units")
    unit_number = models.CharField(max_length=30)
    owner_name = models.CharField(max_length=150)
    resident = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="units",
        limit_choices_to={"role": User.Role.RESIDENT},
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OCCUPIED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("apartment", "unit_number"),
                name="unique_unit_per_apartment",
            ),
        ]
        ordering = ("apartment__name", "unit_number")

    def __str__(self):
        return f"{self.apartment.name} - {self.unit_number}"


class MaintenancePayment(models.Model):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="maintenance_payments")
    period = models.DateField()
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1500.00"),
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNPAID,
    )
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_maintenance_payments",
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("unit", "period"),
                name="unique_maintenance_payment_per_unit_period",
            ),
        ]
        ordering = ("unit__apartment__name", "unit__unit_number")

    def __str__(self):
        return f"{self.unit} - {self.period:%B %Y}: {self.get_status_display()}"


class Category(models.Model):
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="unique_category_name_case_insensitive",
            ),
        ]
        ordering = ("name",)

    def __str__(self):
        return self.name


class Complaint(models.Model):
    class Scope(models.TextChoices):
        PRIVATE = "private", "Private unit"
        COMMON = "common", "Common area"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        RAISED = "raised", "Complaint Raised"
        ASSIGNED = "assigned", "Assigned to Staff"
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        SUCCESSFUL = "successful", "Successful"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        REOPENED = "reopened", "Reopened"

    scope = models.CharField(
        max_length=10,
        choices=Scope.choices,
        default=Scope.PRIVATE,
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="complaints",
        null=True,
        blank=True,
    )
    common_area_location = models.CharField(max_length=150, blank=True)
    resident = models.ForeignKey(User, on_delete=models.PROTECT, related_name="complaints")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="complaints")
    title = models.CharField(max_length=200)
    description = models.TextField()
    preferred_visit_time = models.CharField(
        max_length=100,
        blank=True,
        help_text='For example, "10 AM - 12 PM" or "After 6 PM".',
    )
    is_emergency = models.BooleanField(default=False)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RAISED)
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_complaints",
        limit_choices_to={"role": User.Role.STAFF},
    )
    image = models.FileField(upload_to="complaint_images/", blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_complaints",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"#{self.pk} {self.title}"

    @property
    def is_overdue(self):
        return (
            self.status
            not in (
                self.Status.COMPLETED,
                self.Status.SUCCESSFUL,
                self.Status.RESOLVED,
                self.Status.CLOSED,
            )
            and timezone.now() - self.created_at > timedelta(hours=72)
        )


class WorkLog(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="work_logs")
    performed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="work_logs")
    comment = models.TextField()
    status = models.CharField(max_length=12, choices=Complaint.Status.choices)
    image = models.FileField(upload_to="work_log_images/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.complaint}: {self.get_status_display()}"


class Feedback(models.Model):
    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, related_name="feedback")
    resident = models.ForeignKey(User, on_delete=models.PROTECT, related_name="feedback")
    rating = models.PositiveSmallIntegerField(
        validators=(MinValueValidator(1), MaxValueValidator(5)),
    )
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.complaint} feedback ({self.rating}/5)"


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=150)
    message = models.TextField()
    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.title} ({self.recipient})"
