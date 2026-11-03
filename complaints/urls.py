from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("community-info/", views.community_information, name="community_information"),
    path("staff-access/login/", views.staff_login, name="staff_login"),
    path("staff-access/", views.staff_portal, name="staff_portal"),
    path("staff-access/maintenance-collection/", views.maintenance_collection, name="maintenance_collection"),
    path("community-access/login/", views.community_access_login, name="community_access_login"),
    path("community-access/", views.community_access, name="community_access"),
    path("community-access/staff/", views.community_staff, name="community_staff"),
    path("community-access/flats/<int:unit_id>/", views.community_unit_detail, name="community_unit_detail"),
    path("feedback/", views.feedback_list, name="feedback_list"),
    path("resident-help/", views.resident_help, name="resident_help"),
    path("resident-help/staff/", views.resident_help_staff, name="resident_help_staff"),
    path("complaints/new/", views.complaint_create, name="complaint_create"),
    path("complaints/<int:complaint_id>/", views.complaint_detail, name="complaint_detail"),
    path("complaints/<int:complaint_id>/assign/", views.assign_complaint, name="assign_complaint"),
    path("complaints/<int:complaint_id>/update/", views.update_complaint, name="update_complaint"),
    path("complaints/<int:complaint_id>/reopen/", views.reopen_complaint, name="reopen_complaint"),
    path("complaints/<int:complaint_id>/feedback/", views.submit_feedback, name="submit_feedback"),
]
