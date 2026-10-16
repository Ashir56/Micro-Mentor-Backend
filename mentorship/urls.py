from django.urls import path

from . import views
from . import admin_views

urlpatterns = [
    # Auth
    path("auth/register/", views.register, name="register"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/token/refresh/", views.token_refresh, name="token-refresh"),

    # Discovery (public)
    path("home/", views.home, name="home"),
    path("mentors/", views.mentor_list, name="mentor-list"),
    path("mentors/<int:mentor_id>/", views.mentor_detail, name="mentor-detail"),
    path("mentors/<int:mentor_id>/availability/", views.mentor_availability, name="mentor-availability"),

    # Reference data (public read)
    path("categories/", views.category_list, name="category-list"),
    path("categories/<int:category_id>/", views.category_detail, name="category-detail"),
    path("expertise/", views.expertise_list, name="expertise-list"),
    path("expertise/<int:expertise_id>/", views.expertise_detail, name="expertise-detail"),

    # Mentor profiles (production records — admin/internal use)
    path("mentor-profiles/", views.mentor_profile_list, name="mentor-profile-list"),
    path("mentor-profiles/<int:mentor_id>/", views.mentor_profile_detail, name="mentor-profile-detail"),

    # Session packages and availability (production records)
    path("packages/", views.package_list, name="package-list"),
    path("packages/<int:package_id>/", views.package_detail, name="package-detail"),
    path("availability-windows/", views.availability_window_list, name="availability-window-list"),
    path("availability-windows/<int:window_id>/", views.availability_window_detail, name="availability-window-detail"),

    # Bookings and sessions
    path("bookings/", views.bookings, name="bookings"),
    path("sessions/", views.session_list, name="session-list"),
    path("sessions/<int:session_id>/", views.session_detail, name="session-detail"),
    path("sessions/<int:session_id>/cancel/", views.cancel_session, name="session-cancel"),
    path("sessions/<int:session_id>/payment/confirm/", views.confirm_payment, name="confirm-payment"),
    path("sessions/<int:session_id>/complete/", views.complete_session, name="complete-session"),
    path("sessions/<int:session_id>/review/", views.create_review, name="create-review"),

    # Reviews and payments
    path("reviews/", views.review_list, name="review-list"),
    path("reviews/<int:review_id>/", views.review_detail, name="review-detail"),
    path("payments/<int:session_id>/", views.payment_detail, name="payment-detail"),

    # Conversations and messages
    path("conversations/", views.conversations, name="conversation-list"),
    path("conversations/<int:conversation_id>/", views.conversation_detail, name="conversation-detail"),
    path("conversations/<int:conversation_id>/messages/", views.send_message, name="send-message"),

    # User profile and dashboard
    path("profile/", views.profile, name="profile"),
    path("mentor-dashboard/", views.mentor_dashboard, name="mentor-dashboard"),

    # Health (unauthenticated liveness probe)
    path("health/", views.health_check, name="api-health"),

    # -----------------------------------------------------------------------
    # Mentor onboarding (mentor-owner only)
    # -----------------------------------------------------------------------
    path("mentor-onboarding/", views.mentor_onboarding_draft_view, name="mentor-onboarding-draft"),
    path("mentor-onboarding/update/", views.mentor_onboarding_draft_view, name="mentor-onboarding-draft-update"),
    path("mentor-onboarding/submit/", views.mentor_onboarding_submit, name="mentor-onboarding-submit"),
    path("mentor-onboarding/status/", views.mentor_onboarding_status, name="mentor-onboarding-status"),
    path(
        "mentor-onboarding/documents/upload-request/",
        views.document_upload_request,
        name="mentor-onboarding-document-upload-request",
    ),
    path(
        "mentor-onboarding/documents/<int:document_id>/confirm/",
        views.document_confirm,
        name="mentor-onboarding-document-confirm",
    ),
    path(
        "mentor-onboarding/documents/<int:document_id>/",
        views.document_delete,
        name="mentor-onboarding-document-delete",
    ),

    # -----------------------------------------------------------------------
    # Admin — Mentor Applications (existing, staff-only)
    # -----------------------------------------------------------------------
    path("admin/mentor-applications/", views.admin_application_list, name="admin-application-list"),
    path("admin/mentor-applications/<int:application_id>/", views.admin_application_detail, name="admin-application-detail"),
    path("admin/mentor-applications/<int:application_id>/approve/", views.admin_application_approve, name="admin-application-approve"),
    path(
        "admin/mentor-applications/<int:application_id>/request-changes/",
        views.admin_application_request_changes,
        name="admin-application-request-changes",
    ),
    path("admin/mentor-applications/<int:application_id>/reject/", views.admin_application_reject, name="admin-application-reject"),
    path("admin/mentor-applications/<int:application_id>/reopen/", views.admin_application_reopen, name="admin-application-reopen"),
    path(
        "admin/mentor-applications/<int:application_id>/documents/<int:document_id>/download/",
        views.admin_document_download,
        name="admin-document-download",
    ),

    # -----------------------------------------------------------------------
    # Admin — Dashboard
    # -----------------------------------------------------------------------
    path("admin/dashboard/", admin_views.admin_dashboard, name="admin-dashboard"),

    # -----------------------------------------------------------------------
    # Admin — User Management
    # -----------------------------------------------------------------------
    path("admin/users/", admin_views.admin_user_list, name="admin-user-list"),
    path("admin/users/<int:user_id>/", admin_views.admin_user_detail, name="admin-user-detail"),
    path("admin/users/<int:user_id>/status/", admin_views.admin_user_status, name="admin-user-status"),
    path("admin/users/<int:user_id>/revoke-sessions/", admin_views.admin_user_revoke_sessions, name="admin-user-revoke-sessions"),
    path("admin/users/<int:user_id>/sessions/", admin_views.admin_user_sessions, name="admin-user-sessions"),
    path("admin/users/<int:user_id>/reviews/", admin_views.admin_user_reviews, name="admin-user-reviews"),

    # -----------------------------------------------------------------------
    # Admin — Live Mentor Profiles
    # -----------------------------------------------------------------------
    path("admin/mentor-profiles/", admin_views.admin_mentor_profile_list, name="admin-mentor-profile-list"),
    path("admin/mentor-profiles/<int:mentor_id>/", admin_views.admin_mentor_profile_detail, name="admin-mentor-profile-detail"),
    path("admin/mentor-profiles/<int:mentor_id>/visibility/", admin_views.admin_mentor_profile_visibility, name="admin-mentor-profile-visibility"),
    path("admin/mentor-profiles/<int:mentor_id>/booking-access/", admin_views.admin_mentor_profile_booking_access, name="admin-mentor-profile-booking-access"),

    # -----------------------------------------------------------------------
    # Admin — Sessions
    # -----------------------------------------------------------------------
    path("admin/sessions/", admin_views.admin_session_list, name="admin-session-list"),
    path("admin/sessions/<int:session_id>/", admin_views.admin_session_detail, name="admin-session-detail"),
    path("admin/sessions/<int:session_id>/cancel/", admin_views.admin_session_cancel, name="admin-session-cancel"),

    # -----------------------------------------------------------------------
    # Admin — Review Moderation
    # -----------------------------------------------------------------------
    path("admin/reviews/", admin_views.admin_review_list, name="admin-review-list"),
    path("admin/reviews/<int:review_id>/", admin_views.admin_review_detail, name="admin-review-detail"),
    path("admin/reviews/<int:review_id>/hide/", admin_views.admin_review_hide, name="admin-review-hide"),
    path("admin/reviews/<int:review_id>/unhide/", admin_views.admin_review_unhide, name="admin-review-unhide"),
    path("admin/reviews/<int:review_id>/remove/", admin_views.admin_review_remove, name="admin-review-remove"),
    path("admin/reviews/<int:review_id>/restore/", admin_views.admin_review_restore, name="admin-review-restore"),

    # -----------------------------------------------------------------------
    # Admin — Categories (protected management)
    # -----------------------------------------------------------------------
    path("admin/categories/", admin_views.admin_category_list, name="admin-category-list"),
    path("admin/categories/<int:category_id>/", admin_views.admin_category_detail, name="admin-category-detail"),
    path("admin/categories/<int:category_id>/archive/", admin_views.admin_category_archive, name="admin-category-archive"),
    path("admin/categories/<int:category_id>/restore/", admin_views.admin_category_restore, name="admin-category-restore"),

    # -----------------------------------------------------------------------
    # Admin — Expertise (protected management)
    # -----------------------------------------------------------------------
    path("admin/expertise/", admin_views.admin_expertise_list, name="admin-expertise-list"),
    path("admin/expertise/<int:expertise_id>/", admin_views.admin_expertise_detail, name="admin-expertise-detail"),
    path("admin/expertise/<int:expertise_id>/archive/", admin_views.admin_expertise_archive, name="admin-expertise-archive"),
    path("admin/expertise/<int:expertise_id>/restore/", admin_views.admin_expertise_restore, name="admin-expertise-restore"),
]
