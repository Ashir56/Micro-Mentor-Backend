from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AvailabilityWindow,
    Category,
    Conversation,
    Expertise,
    MentorApplication,
    MentorApplicationAvailability,
    MentorApplicationPackage,
    MentorApplicationReviewEvent,
    MentorProfile,
    MentorshipSession,
    MentorVerificationDocument,
    Message,
    Payment,
    Review,
    SessionPackage,
    UserProfile,
)


# ---------------------------------------------------------------------------
# Existing models
# ---------------------------------------------------------------------------

admin.site.register(UserProfile)
admin.site.register(Category)
admin.site.register(Expertise)
admin.site.register(MentorProfile)
admin.site.register(SessionPackage)
admin.site.register(AvailabilityWindow)
admin.site.register(MentorshipSession)
admin.site.register(Payment)
admin.site.register(Review)
admin.site.register(Conversation)
admin.site.register(Message)


# ---------------------------------------------------------------------------
# Mentor Onboarding models
# ---------------------------------------------------------------------------

class MentorApplicationPackageInline(admin.TabularInline):
    model = MentorApplicationPackage
    extra = 0
    readonly_fields = ("client_id", "duration_minutes", "price_usd", "is_popular", "is_active")
    can_delete = False


class MentorApplicationAvailabilityInline(admin.TabularInline):
    model = MentorApplicationAvailability
    extra = 0
    readonly_fields = ("client_id", "weekday", "starts_at", "ends_at", "slot_interval_minutes", "is_active")
    can_delete = False


class MentorVerificationDocumentInline(admin.TabularInline):
    model = MentorVerificationDocument
    extra = 0
    readonly_fields = ("document_type", "original_file_name", "content_type", "size_bytes", "status", "uploaded_at")
    exclude = ("storage_key", "checksum_sha256")  # Never show private storage key in admin
    can_delete = False


class MentorApplicationReviewEventInline(admin.TabularInline):
    model = MentorApplicationReviewEvent
    extra = 0
    readonly_fields = ("event_type", "actor", "metadata", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MentorApplication)
class MentorApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "mentor_name",
        "mentor_email",
        "profession",
        "status_badge",
        "completion_percent",
        "submitted_at",
        "reviewed_at",
        "reviewer",
    )
    list_filter = ("status", "profession")
    search_fields = ("user__email", "user__first_name", "user__last_name", "headline")
    ordering = ("-submitted_at", "-created_at")
    readonly_fields = (
        "user", "status", "version", "submitted_at", "reviewed_at",
        "reviewer", "created_at", "updated_at", "completion_percent",
        "terms_version", "terms_accepted_at",
    )
    inlines = [
        MentorVerificationDocumentInline,
        MentorApplicationPackageInline,
        MentorApplicationAvailabilityInline,
        MentorApplicationReviewEventInline,
    ]
    fieldsets = (
        ("Mentor", {
            "fields": ("user", "status", "current_step", "completion_percent", "version")
        }),
        ("Professional Profile", {
            "fields": ("profession", "headline", "company", "years_experience", "bio", "linkedin_url", "portfolio_url")
        }),
        ("Session Config", {
            "fields": ("timezone", "accepts_inquiries")
        }),
        ("Submission", {
            "fields": ("terms_version", "terms_accepted_at", "submitted_at")
        }),
        ("Review", {
            "fields": ("reviewed_at", "reviewer", "review_notes", "fields_requiring_changes")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def mentor_name(self, obj):
        return obj.user.get_full_name() or obj.user.email
    mentor_name.short_description = "Mentor"

    def mentor_email(self, obj):
        return obj.user.email
    mentor_email.short_description = "Email"

    def status_badge(self, obj):
        colours = {
            "draft": "#6c757d",
            "pending_review": "#fd7e14",
            "changes_requested": "#0dcaf0",
            "verified": "#198754",
            "rejected": "#dc3545",
        }
        colour = colours.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">{}</span>',
            colour,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "reviewer")


@admin.register(MentorVerificationDocument)
class MentorVerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "application_id", "document_type", "original_file_name", "status", "uploaded_at")
    list_filter = ("status", "document_type")
    readonly_fields = ("storage_key", "checksum_sha256", "application", "uploaded_at", "created_at", "updated_at")
    search_fields = ("application__user__email", "original_file_name")

    def has_add_permission(self, request):
        return False  # Documents are created only through the API


@admin.register(MentorApplicationReviewEvent)
class MentorApplicationReviewEventAdmin(admin.ModelAdmin):
    list_display = ("id", "application_id", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("application", "actor", "event_type", "metadata", "created_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # Audit log is immutable

    def has_delete_permission(self, request, obj=None):
        return False  # Audit log is immutable
