from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models.functions import Lower, Trim

from .models import Category, Complaint, Feedback, Unit, WorkLog

User = get_user_model()


class RegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class MaintenanceStaffCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "staff_position",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class CaseInsensitiveAuthenticationForm(AuthenticationForm):
    def clean_username(self):
        username = self.cleaned_data["username"]
        matching_usernames = list(
            User.objects.filter(username__iexact=username)
            .values_list("username", flat=True)[:2]
        )
        if len(matching_usernames) == 1:
            return matching_usernames[0]
        return username


class ResidentAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Owner name",
        help_text="Enter the owner name registered to your flat.",
    )

    def clean(self):
        owner_name = self.cleaned_data.get("username", "").strip()
        password = self.cleaned_data.get("password")
        if not owner_name or not password:
            return self.cleaned_data

        candidates = User.objects.filter(
            role=User.Role.RESIDENT,
            is_active=True,
            units__apartment__is_active=True,
            units__owner_name__iexact=owner_name,
        ).distinct().order_by("pk")
        for candidate in candidates:
            user = authenticate(
                self.request,
                username=candidate.get_username(),
                password=password,
            )
            if user is not None:
                self.confirm_login_allowed(user)
                self.user_cache = user
                return self.cleaned_data

        raise self.get_invalid_login_error()


class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = (
            "scope",
            "unit",
            "common_area_location",
            "category",
            "title",
            "description",
            "preferred_visit_time",
            "priority",
            "is_emergency",
            "image",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "scope": forms.Select(attrs={"data-complaint-scope": "true"}),
            "common_area_location": forms.TextInput(
                attrs={"placeholder": "e.g. Lift lobby, clubhouse, Block A hallway"}
            ),
            "preferred_visit_time": forms.TextInput(
                attrs={"placeholder": "e.g. 10 AM - 12 PM or After 6 PM"}
            ),
        }
        labels = {
            "scope": "Issue area",
            "common_area_location": "Common area location",
            "preferred_visit_time": "Preferred visit time",
            "is_emergency": "This is an emergency",
        }
        help_texts = {
            "scope": (
                "Private unit issues are associated with the selected flat and are the "
                "owner/tenant's responsibility. "
                "Common area issues are shared community problems."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.filter(
            apartment__is_active=True,
        ).select_related("apartment")
        self.fields["unit"].required = False
        self.fields["scope"].required = False
        self.fields["category"].queryset = Category.objects.filter(is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        scope = cleaned_data.get("scope") or Complaint.Scope.PRIVATE
        cleaned_data["scope"] = scope
        unit = cleaned_data.get("unit")
        location = cleaned_data.get("common_area_location", "").strip()

        if scope == Complaint.Scope.PRIVATE:
            if not unit:
                self.add_error("unit", "Select the flat where the issue occurred.")
            cleaned_data["common_area_location"] = ""
        elif scope == Complaint.Scope.COMMON:
            if not location:
                self.add_error(
                    "common_area_location",
                    "Enter where in the community the issue occurred.",
                )
            cleaned_data["unit"] = None

            category = cleaned_data.get("category")
            title = cleaned_data.get("title", "").strip()
            if category and title and location:
                active_statuses = (
                    Complaint.Status.RAISED,
                    Complaint.Status.ASSIGNED,
                    Complaint.Status.PENDING,
                    Complaint.Status.IN_PROGRESS,
                    Complaint.Status.REOPENED,
                )
                duplicate_exists = (
                    Complaint.objects.filter(
                        scope=Complaint.Scope.COMMON,
                        category=category,
                        status__in=active_statuses,
                    )
                    .annotate(
                        normalized_title=Lower(Trim("title")),
                        normalized_location=Lower(Trim("common_area_location")),
                    )
                    .filter(
                        normalized_title=title.lower(),
                        normalized_location=location.lower(),
                    )
                    .exists()
                )
                if duplicate_exists:
                    self.add_error(
                        None,
                        "A matching common area issue is already open. "
                        "Please check with the apartment team instead of reporting it again.",
                    )

        return cleaned_data


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ("assigned_to",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(
            role=User.Role.STAFF,
            is_active=True,
        )
        self.fields["assigned_to"].required = True
        self.fields["assigned_to"].label = "Assign to staff member"
        self.fields["assigned_to"].label_from_instance = self._format_staff_choice

    @staticmethod
    def _format_staff_choice(staff_member):
        name = staff_member.get_full_name() or staff_member.username
        position = staff_member.get_staff_position_display()
        return f"{name} — {position}" if position else name


class WorkUpdateForm(forms.ModelForm):
    class Meta:
        model = WorkLog
        fields = ("status", "comment", "image")
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, complaint, **kwargs):
        super().__init__(*args, **kwargs)
        if complaint.status in (
            Complaint.Status.ASSIGNED,
            Complaint.Status.PENDING,
            Complaint.Status.REOPENED,
            Complaint.Status.IN_PROGRESS,
        ) or (complaint.is_emergency and complaint.status == Complaint.Status.RAISED):
            allowed = (
                Complaint.Status.ASSIGNED,
                Complaint.Status.PENDING,
                Complaint.Status.IN_PROGRESS,
                Complaint.Status.COMPLETED,
                Complaint.Status.SUCCESSFUL,
                Complaint.Status.RESOLVED,
            )
        else:
            allowed = ()
        self.fields["status"].choices = [
            choice for choice in Complaint.Status.choices if choice[0] in allowed
        ]


class FeedbackForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=(
            (1, "1 - Poor"),
            (2, "2 - Fair"),
            (3, "3 - Good"),
            (4, "4 - Very good"),
            (5, "5 - Excellent"),
        ),
        coerce=int,
        widget=forms.RadioSelect,
        label="Rate the completed work (out of 5)",
    )

    class Meta:
        model = Feedback
        fields = ("rating", "comments")
        widgets = {
            "comments": forms.Textarea(attrs={"rows": 3}),
        }
