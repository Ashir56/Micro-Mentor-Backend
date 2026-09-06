from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class UserProfile(models.Model):
    class Role(models.TextChoices):
        MENTEE = "mentee", "Mentee"
        MENTOR = "mentor", "Mentor"

    class AccountStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"
        SUSPENDED = "suspended", "Suspended"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MENTEE)
    account_status = models.CharField(
        max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE, db_index=True
    )
    status_reason = models.TextField(blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    avatar_initials = models.CharField(max_length=4, blank=True)
    city = models.CharField(max_length=80, blank=True)
    linkedin_url = models.URLField(blank=True)
    is_linkedin_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.email} ({self.role})"


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    emoji = models.CharField(max_length=8, blank=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Expertise(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class MentorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    headline = models.CharField(max_length=160)
    company = models.CharField(max_length=120, blank=True)
    bio = models.TextField()
    years_experience = models.PositiveSmallIntegerField(default=0)
    categories = models.ManyToManyField(Category, blank=True)
    expertise = models.ManyToManyField(Expertise, blank=True)
    repeat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    profile_completion = models.PositiveSmallIntegerField(default=0)
    intro_video_url = models.URLField(blank=True)
    stripe_connect_account_id = models.CharField(max_length=120, blank=True)
    auto_confirm_bookings = models.BooleanField(default=True)
    allow_pre_booking_messages = models.BooleanField(default=False)
    pre_booking_message_limit = models.PositiveSmallIntegerField(default=3)
    is_active = models.BooleanField(default=True)
    # Set to True only after application is verified and approved.
    is_verified = models.BooleanField(default=False)
    # Admin-controlled visibility toggles (independent of verification).
    is_discovery_enabled = models.BooleanField(default=True)
    is_booking_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__first_name", "user__last_name"]

    def __str__(self):
        return self.user.get_full_name() or self.user.email


class SessionPackage(models.Model):
    mentor = models.ForeignKey(MentorProfile, on_delete=models.CASCADE, related_name="packages")
    duration_minutes = models.PositiveSmallIntegerField()
    price_usd = models.DecimalField(max_digits=8, decimal_places=2)
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["mentor", "duration_minutes"]
        constraints = [
            models.UniqueConstraint(
                fields=["mentor", "duration_minutes"],
                name="unique_package_duration_per_mentor",
            )
        ]

    def __str__(self):
        return f"{self.mentor} - {self.duration_minutes} min"


class AvailabilityWindow(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    mentor = models.ForeignKey(MentorProfile, on_delete=models.CASCADE, related_name="availability")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    timezone = models.CharField(max_length=64, default="America/Los_Angeles")
    slot_interval_minutes = models.PositiveSmallIntegerField(default=15)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["mentor", "weekday", "starts_at"]

    def __str__(self):
        return f"{self.mentor} {self.get_weekday_display()} {self.starts_at}-{self.ends_at}"


class MentorshipSession(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    mentee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mentee_sessions",
    )
    mentor = models.ForeignKey(MentorProfile, on_delete=models.CASCADE, related_name="sessions")
    package = models.ForeignKey(SessionPackage, on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    goals = models.TextField(blank=True)
    topic = models.CharField(max_length=140, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    video_room_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self):
        return f"{self.mentee} with {self.mentor} at {self.starts_at}"


class Payment(models.Model):
    class Status(models.TextChoices):
        REQUIRES_PAYMENT = "requires_payment", "Requires payment"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"
        FAILED = "failed", "Failed"

    session = models.OneToOneField(MentorshipSession, on_delete=models.CASCADE, related_name="payment")
    amount_usd = models.DecimalField(max_digits=8, decimal_places=2)
    platform_fee_usd = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.REQUIRES_PAYMENT)
    provider = models.CharField(max_length=40, default="stripe")
    provider_payment_id = models.CharField(max_length=140, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.session_id} - {self.status}"


class Review(models.Model):
    class VisibilityStatus(models.TextChoices):
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden"
        REMOVED = "removed", "Removed"

    session = models.OneToOneField(MentorshipSession, on_delete=models.CASCADE, related_name="review")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mentor = models.ForeignKey(MentorProfile, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    body = models.TextField(blank=True)
    visibility_status = models.CharField(
        max_length=20, choices=VisibilityStatus.choices, default=VisibilityStatus.PUBLISHED, db_index=True
    )
    moderation_reason = models.TextField(blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderated_reviews",
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}/5 for {self.mentor}"


class Conversation(models.Model):
    class Type(models.TextChoices):
        INQUIRY = "inquiry", "Inquiry"
        SESSION = "session", "Session"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        LOCKED = "locked", "Locked"
        ARCHIVED = "archived", "Archived"

    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="conversations")
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.INQUIRY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mentor_conversations",
    )
    mentee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mentee_conversations",
    )
    session = models.ForeignKey(
        MentorshipSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_conversations",
    )
    mentee_message_count = models.PositiveIntegerField(default=0)
    related_session = models.ForeignKey(
        MentorshipSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Conversation {self.pk}"


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Message {self.pk} by {self.sender}"


# ---------------------------------------------------------------------------
# Mentor Onboarding & Verification Models
# ---------------------------------------------------------------------------

class MentorApplication(models.Model):
    """One active onboarding application per mentor user."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_REVIEW = "pending_review", "Pending Review"
        CHANGES_REQUESTED = "changes_requested", "Changes Requested"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    class Step(models.TextChoices):
        PROFESSIONAL_PROFILE = "professional_profile", "Professional Profile"
        EXPERTISE = "expertise", "Expertise"
        VERIFICATION = "verification", "Verification"
        SERVICES = "services", "Services"
        AVAILABILITY = "availability", "Availability"
        REVIEW = "review", "Review"

    class Profession(models.TextChoices):
        SOFTWARE_ENGINEERING = "software_engineering", "Software Engineering"
        DATA_SCIENCE = "data_science", "Data Science"
        PRODUCT_MANAGEMENT = "product_management", "Product Management"
        DESIGN = "design", "Design"
        MARKETING = "marketing", "Marketing"
        FINANCE = "finance", "Finance"
        OPERATIONS = "operations", "Operations"
        HUMAN_RESOURCES = "human_resources", "Human Resources"
        SALES = "sales", "Sales"
        OTHER = "other", "Other"

    # Allowed status transitions. Keys are current status; values are allowed next statuses.
    ALLOWED_TRANSITIONS = {
        Status.DRAFT: {Status.PENDING_REVIEW},
        Status.PENDING_REVIEW: {Status.VERIFIED, Status.CHANGES_REQUESTED, Status.REJECTED},
        Status.CHANGES_REQUESTED: {Status.PENDING_REVIEW},
        Status.REJECTED: {Status.DRAFT},  # only via explicit staff reopen action
        Status.VERIFIED: set(),
    }

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mentor_application",
    )
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    current_step = models.CharField(
        max_length=40, choices=Step.choices, default=Step.PROFESSIONAL_PROFILE
    )
    completion_percent = models.PositiveSmallIntegerField(default=0)

    # Professional profile section
    profession = models.CharField(max_length=60, choices=Profession.choices, blank=True)
    headline = models.CharField(max_length=120, blank=True)
    company = models.CharField(max_length=120, blank=True)
    years_experience = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(60)]
    )
    bio = models.TextField(blank=True)
    linkedin_url = models.URLField(blank=True)
    portfolio_url = models.URLField(blank=True)

    # Expertise
    categories = models.ManyToManyField(Category, blank=True, related_name="applications")
    expertise = models.ManyToManyField(Expertise, blank=True, related_name="applications")

    # Availability/session config
    timezone = models.CharField(max_length=64, blank=True)
    accepts_inquiries = models.BooleanField(default=True)

    # Submission/terms
    terms_version = models.CharField(max_length=60, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Review fields (set by reviewer)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_applications",
    )
    review_notes = models.TextField(blank=True)
    fields_requiring_changes = models.JSONField(default=list, blank=True)

    # Optimistic concurrency version — incremented on every successful draft mutation.
    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "submitted_at"]),
        ]

    def __str__(self):
        return f"Application({self.user_id}) — {self.status}"

    def can_edit(self):
        return self.status in {self.Status.DRAFT, self.Status.CHANGES_REQUESTED}

    def can_submit(self):
        return self.status in {self.Status.DRAFT, self.Status.CHANGES_REQUESTED}

    def transition_to(self, new_status):
        """Validate and apply a status transition. Raises ValueError on illegal move."""
        allowed = self.ALLOWED_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition from '{self.status}' to '{new_status}'."
            )
        self.status = new_status


class MentorApplicationPackage(models.Model):
    """Draft session package owned by a MentorApplication."""

    ALLOWED_DURATIONS = [15, 30, 45, 60]

    application = models.ForeignKey(
        MentorApplication, on_delete=models.CASCADE, related_name="packages"
    )
    # client_id lets the mobile app retry saves idempotently.
    client_id = models.CharField(max_length=100)
    duration_minutes = models.PositiveSmallIntegerField(
        choices=[(d, str(d)) for d in ALLOWED_DURATIONS]
    )
    price_usd = models.DecimalField(max_digits=10, decimal_places=2)
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["duration_minutes"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "client_id"],
                name="unique_app_package_client_id",
            )
        ]

    def __str__(self):
        return f"DraftPackage({self.application_id}) {self.duration_minutes}min"


class MentorApplicationAvailability(models.Model):
    """Draft availability window owned by a MentorApplication.

    Uses ISO weekdays: 1=Monday … 7=Sunday.
    Times are stored in the application's local timezone.
    """

    ALLOWED_INTERVALS = [15, 30, 45, 60]

    application = models.ForeignKey(
        MentorApplication, on_delete=models.CASCADE, related_name="availability_windows"
    )
    client_id = models.CharField(max_length=100)
    # ISO weekday 1=Monday … 7=Sunday
    weekday = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    slot_interval_minutes = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in ALLOWED_INTERVALS], default=30
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["weekday", "starts_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "client_id"],
                name="unique_app_availability_client_id",
            )
        ]

    def __str__(self):
        return f"DraftWindow({self.application_id}) weekday={self.weekday} {self.starts_at}-{self.ends_at}"


class MentorVerificationDocument(models.Model):
    """Private verification document attached to a MentorApplication."""

    class DocumentType(models.TextChoices):
        IDENTITY = "identity", "Identity"
        EMPLOYMENT = "employment", "Employment"
        CERTIFICATE = "certificate", "Certificate"
        EDUCATION = "education", "Education"
        PORTFOLIO = "portfolio", "Portfolio"
        OTHER = "other", "Other"

    class DocumentStatus(models.TextChoices):
        REQUESTED = "requested", "Requested"
        UPLOADED = "uploaded", "Uploaded"
        SCANNING = "scanning", "Scanning"
        READY = "ready", "Ready"
        UNSAFE = "unsafe", "Unsafe"
        REJECTED = "rejected", "Rejected"
        DELETED = "deleted", "Deleted"

    ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
    MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

    application = models.ForeignKey(
        MentorApplication, on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(max_length=30, choices=DocumentType.choices)
    original_file_name = models.CharField(max_length=255)
    # Private object-storage key — never returned to clients directly.
    storage_key = models.CharField(max_length=512, unique=True)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.REQUESTED,
        db_index=True,
    )
    rejection_reason = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Doc({self.id}) {self.document_type} — {self.status}"


class MentorApplicationReviewEvent(models.Model):
    """Append-only audit log for all application lifecycle events.

    Records must never be updated or deleted through normal application code.
    """

    class EventType(models.TextChoices):
        APPLICATION_CREATED = "application_created", "Application Created"
        DRAFT_UPDATED = "draft_updated", "Draft Updated"
        DOCUMENT_UPLOADED = "document_uploaded", "Document Uploaded"
        DOCUMENT_DOWNLOADED = "document_downloaded", "Document Downloaded"
        SUBMITTED = "submitted", "Submitted"
        RESUBMITTED = "resubmitted", "Resubmitted"
        CHANGES_REQUESTED = "changes_requested", "Changes Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        REOPENED = "reopened", "Reopened"
        MIGRATED = "migrated", "Migrated"

    application = models.ForeignKey(
        MentorApplication, on_delete=models.CASCADE, related_name="review_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application_audit_events",
    )
    event_type = models.CharField(max_length=40, choices=EventType.choices, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Audit events are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events are immutable and cannot be deleted.")

    def __str__(self):
        return f"Event({self.event_type}) app={self.application_id} at {self.created_at}"
