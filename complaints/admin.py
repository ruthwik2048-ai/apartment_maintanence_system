from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserCreationForm

from .models import (
    Apartment,
    Category,
    Complaint,
    Feedback,
    MaintenancePayment,
    Notification,
    Unit,
    User,
    WorkLog,
)


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "phone", "role")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = AdminUserCreationForm
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Apartment profile", {"fields": ("phone", "role", "staff_position")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Apartment profile", {"fields": ("email", "phone", "role", "staff_position")}),
    )
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_active")


@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "total_blocks", "is_active")
    search_fields = ("name", "address", "city")
    list_filter = ("is_active", "city")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("unit_number", "apartment", "owner_name", "resident", "status")
    search_fields = ("unit_number", "owner_name", "apartment__name")
    list_filter = ("status", "apartment")


@admin.register(MaintenancePayment)
class MaintenancePaymentAdmin(admin.ModelAdmin):
    list_display = ("unit", "period", "amount", "status", "recorded_by", "paid_at")
    list_filter = ("period", "status", "unit__apartment")
    search_fields = ("unit__unit_number", "unit__owner_name", "recorded_by__username")
    readonly_fields = ("paid_at", "updated_at")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)
    list_filter = ("is_active",)


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "scope",
        "common_area_location",
        "resident",
        "category",
        "priority",
        "status",
        "is_emergency",
        "assigned_to",
    )
    search_fields = ("title", "description", "common_area_location", "resident__username")
    list_filter = ("scope", "is_emergency", "status", "priority", "category")
    readonly_fields = ("created_at", "updated_at", "assigned_at", "resolved_at")


@admin.register(WorkLog)
class WorkLogAdmin(admin.ModelAdmin):
    list_display = ("complaint", "performed_by", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("created_at",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("complaint", "resident", "rating", "created_at")
    list_filter = ("rating",)
    readonly_fields = ("created_at",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "complaint", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("title", "message", "recipient__username")
