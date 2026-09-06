"""
Mentor onboarding service layer.

All non-trivial business logic lives here so that views stay thin and
logic is independently testable.
"""

import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import zoneinfo
from django.conf import settings
from django.db import transaction
from django.utils import timezone as tz

from .models import (
    AvailabilityWindow,
    Category,
    Expertise,
    MentorApplication,
    MentorApplicationAvailability,
    MentorApplicationPackage,
    MentorApplicationReviewEvent,
    MentorProfile,
    MentorVerificationDocument,
    SessionPackage,
    UserProfile,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CURRENT_TERMS_VERSION = "mentor-terms-2026-08"

# Completion-percent weights (must sum to 100)
COMPLETION_WEIGHTS = {
    "professional_profile": 25,
    "expertise": 15,
    "documents": 25,
    "packages": 15,
    "availability": 15,
    "terms": 5,
}

ALLOWED_DURATIONS = {15, 30, 45, 60}
ALLOWED_INTERVALS = {15, 30, 45, 60}

# Document types that satisfy the professional-evidence requirement.
PROFESSIONAL_DOC_TYPES = {
    MentorVerificationDocument.DocumentType.EMPLOYMENT,
    MentorVerificationDocument.DocumentType.CERTIFICATE,
    MentorVerificationDocument.DocumentType.EDUCATION,
    MentorVerificationDocument.DocumentType.PORTFOLIO,
}

URL_SCHEME_RE = re.compile(r"^https://", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_https_url(value):
    """Return True if value is a non-empty string starting with https://."""
    return bool(value) and bool(URL_SCHEME_RE.match(str(value)))


def _is_valid_iana_timezone(tz_str):
    try:
        zoneinfo.ZoneInfo(tz_str)
        return True
    except (zoneinfo.ZoneInfoNotFoundError, Exception):
        return False


def _windows_overlap(starts_a, ends_a, starts_b, ends_b):
    """Return True if two time ranges overlap (exclusive end boundary)."""
    return starts_a < ends_b and starts_b < ends_a


# ---------------------------------------------------------------------------
# Completion percentage
# ---------------------------------------------------------------------------

def calculate_completion_percent(application):
    """Return an integer 0–100 representing how complete the draft is."""
    score = 0

    # Professional profile (25 pts) — all required fields present
    profile_fields = [
        application.profession,
        application.headline,
        application.bio,
        application.years_experience is not None,
    ]
    if all(profile_fields):
        score += COMPLETION_WEIGHTS["professional_profile"]

    # Expertise (15 pts) — at least one category and one expertise
    has_categories = application.categories.filter(is_active=True).exists()
    has_expertise = application.expertise.filter(is_active=True).exists()
    if has_categories and has_expertise:
        score += COMPLETION_WEIGHTS["expertise"]

    # Documents (25 pts) — at least one ready identity OR professional document
    ready_docs = application.documents.filter(
        status=MentorVerificationDocument.DocumentStatus.READY
    )
    has_ready_doc = ready_docs.exists()
    if has_ready_doc:
        score += COMPLETION_WEIGHTS["documents"]

    # Packages (15 pts) — at least one active package
    has_package = application.packages.filter(is_active=True).exists()
    if has_package:
        score += COMPLETION_WEIGHTS["packages"]

    # Availability (15 pts) — at least one active window and timezone set
    has_window = application.availability_windows.filter(is_active=True).exists()
    has_timezone = bool(application.timezone) and _is_valid_iana_timezone(application.timezone)
    if has_window and has_timezone:
        score += COMPLETION_WEIGHTS["availability"]

    # Terms (5 pts)
    if application.terms_version == CURRENT_TERMS_VERSION:
        score += COMPLETION_WEIGHTS["terms"]

    return score


# ---------------------------------------------------------------------------
# Draft update helpers
# ---------------------------------------------------------------------------

def upsert_packages(application, packages_data):
    """
    Replace the full package list for the application.
    - Upsert by client_id (create or update).
    - Delete packages whose client_id is not in the supplied list.
    Returns (packages_queryset, errors_dict).
    """
    errors = {}
    supplied_client_ids = set()

    for idx, pkg_data in enumerate(packages_data):
        client_id = pkg_data.get("client_id")
        if not client_id:
            errors[f"packages[{idx}].client_id"] = ["client_id is required."]
            continue

        supplied_client_ids.add(client_id)

        duration = pkg_data.get("duration_minutes")
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            errors[f"packages[{idx}].duration_minutes"] = ["A valid integer is required."]
            continue
        if duration not in ALLOWED_DURATIONS:
            errors[f"packages[{idx}].duration_minutes"] = [
                f"Allowed values: {sorted(ALLOWED_DURATIONS)}."
            ]
            continue

        price_raw = pkg_data.get("price_usd")
        try:
            price = Decimal(str(price_raw))
            if price <= 0:
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            errors[f"packages[{idx}].price_usd"] = [
                "A positive decimal value is required (e.g. \"20.00\")."
            ]
            continue

        is_popular = bool(pkg_data.get("is_popular", False))
        is_active = bool(pkg_data.get("is_active", True))

        MentorApplicationPackage.objects.update_or_create(
            application=application,
            client_id=client_id,
            defaults={
                "duration_minutes": duration,
                "price_usd": price,
                "is_popular": is_popular,
                "is_active": is_active,
            },
        )

    if errors:
        return None, errors

    # Enforce: at most one active popular package.
    active_popular = application.packages.filter(is_popular=True, is_active=True)
    if active_popular.count() > 1:
        errors["packages"] = ["At most one active package may be marked popular."]
        return None, errors

    # Remove draft packages omitted from the supplied list.
    application.packages.exclude(client_id__in=supplied_client_ids).delete()

    return application.packages.all(), {}


def upsert_availability_windows(application, windows_data, timezone_str):
    """
    Replace the full availability window list for the application.
    Validates: ISO weekday, time order, no overlaps on the same weekday.
    Returns (windows_queryset, errors_dict).
    """
    errors = {}
    supplied_client_ids = set()
    # Build a map of weekday → list of (starts_at, ends_at, client_id) to check overlaps.
    weekday_windows = {}  # weekday → [(starts, ends, client_id)]

    for idx, win_data in enumerate(windows_data):
        client_id = win_data.get("client_id")
        if not client_id:
            errors[f"availability_windows[{idx}].client_id"] = ["client_id is required."]
            continue

        supplied_client_ids.add(client_id)

        weekday = win_data.get("weekday")
        try:
            weekday = int(weekday)
        except (TypeError, ValueError):
            errors[f"availability_windows[{idx}].weekday"] = ["A valid integer (1–7) is required."]
            continue
        if not (1 <= weekday <= 7):
            errors[f"availability_windows[{idx}].weekday"] = ["Must be between 1 (Monday) and 7 (Sunday)."]
            continue

        starts_raw = win_data.get("starts_at")
        ends_raw = win_data.get("ends_at")
        try:
            starts = datetime.strptime(str(starts_raw), "%H:%M:%S").time()
            ends = datetime.strptime(str(ends_raw), "%H:%M:%S").time()
        except (ValueError, TypeError):
            errors[f"availability_windows[{idx}].starts_at"] = ["Expected HH:MM:SS format."]
            continue

        if ends <= starts:
            errors[f"availability_windows[{idx}].ends_at"] = [
                "ends_at must be after starts_at."
            ]
            continue

        interval = win_data.get("slot_interval_minutes", 30)
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            errors[f"availability_windows[{idx}].slot_interval_minutes"] = [
                "A valid integer is required."
            ]
            continue
        if interval not in ALLOWED_INTERVALS:
            errors[f"availability_windows[{idx}].slot_interval_minutes"] = [
                f"Allowed values: {sorted(ALLOWED_INTERVALS)}."
            ]
            continue

        is_active = bool(win_data.get("is_active", True))

        # Overlap check against already-validated windows in this request.
        if is_active:
            for (prev_starts, prev_ends, prev_cid) in weekday_windows.get(weekday, []):
                if _windows_overlap(starts, ends, prev_starts, prev_ends):
                    errors[f"availability_windows[{idx}]"] = [
                        f"This window overlaps with client_id '{prev_cid}' on weekday {weekday}."
                    ]
                    break

        weekday_windows.setdefault(weekday, []).append((starts, ends, client_id))

    if errors:
        return None, errors

    # Persist — upsert by client_id.
    for idx, win_data in enumerate(windows_data):
        client_id = win_data.get("client_id")
        if not client_id:
            continue

        starts = datetime.strptime(str(win_data["starts_at"]), "%H:%M:%S").time()
        ends = datetime.strptime(str(win_data["ends_at"]), "%H:%M:%S").time()
        interval = int(win_data.get("slot_interval_minutes", 30))
        is_active = bool(win_data.get("is_active", True))

        MentorApplicationAvailability.objects.update_or_create(
            application=application,
            client_id=client_id,
            defaults={
                "weekday": int(win_data["weekday"]),
                "starts_at": starts,
                "ends_at": ends,
                "slot_interval_minutes": interval,
                "is_active": is_active,
            },
        )

    # Remove windows omitted from the supplied list.
    application.availability_windows.exclude(client_id__in=supplied_client_ids).delete()

    return application.availability_windows.all(), {}


def validate_category_expertise_refs(category_ids, expertise_ids):
    """
    Validate that all supplied IDs exist and are active.
    Returns errors dict (may be empty).
    """
    errors = {}

    if category_ids is not None:
        found = set(Category.objects.filter(id__in=category_ids, is_active=True).values_list("id", flat=True))
        unknown = [cid for cid in category_ids if int(cid) not in found]
        if unknown:
            errors["category_ids"] = [f"Unknown or inactive category IDs: {unknown}."]

    if expertise_ids is not None:
        found = set(Expertise.objects.filter(id__in=expertise_ids, is_active=True).values_list("id", flat=True))
        unknown = [eid for eid in expertise_ids if int(eid) not in found]
        if unknown:
            errors["expertise_ids"] = [f"Unknown or inactive expertise IDs: {unknown}."]

    return errors


# ---------------------------------------------------------------------------
# Application serialization
# ---------------------------------------------------------------------------

def serialize_application(application):
    """Return the full normalized draft dict for API responses."""
    packages = list(
        application.packages.values(
            "id", "client_id", "duration_minutes", "price_usd", "is_popular", "is_active"
        )
    )
    # Serialize Decimal price as string.
    for pkg in packages:
        pkg["price_usd"] = str(pkg["price_usd"])

    windows = list(
        application.availability_windows.values(
            "id", "client_id", "weekday", "starts_at", "ends_at",
            "slot_interval_minutes", "is_active"
        )
    )
    for win in windows:
        win["starts_at"] = str(win["starts_at"])
        win["ends_at"] = str(win["ends_at"])

    documents = []
    for doc in application.documents.exclude(
        status=MentorVerificationDocument.DocumentStatus.DELETED
    ):
        documents.append({
            "id": doc.id,
            "document_type": doc.document_type,
            "file_name": doc.original_file_name,
            "status": doc.status,
            "uploaded_at": doc.uploaded_at.isoformat() + "Z" if doc.uploaded_at else None,
            "created_at": doc.created_at.isoformat() + "Z",
        })

    return {
        "id": application.id,
        "status": application.status,
        "current_step": application.current_step,
        "completion_percent": application.completion_percent,
        "version": application.version,
        "professional_profile": {
            "profession": application.profession or None,
            "headline": application.headline or None,
            "company": application.company or None,
            "years_experience": application.years_experience,
            "bio": application.bio or None,
            "linkedin_url": application.linkedin_url or None,
            "portfolio_url": application.portfolio_url or None,
        },
        "category_ids": list(application.categories.values_list("id", flat=True)),
        "expertise_ids": list(application.expertise.values_list("id", flat=True)),
        "documents": documents,
        "packages": packages,
        "timezone": application.timezone or None,
        "availability_windows": windows,
        "accepts_inquiries": application.accepts_inquiries,
        "submitted_at": application.submitted_at.isoformat() + "Z" if application.submitted_at else None,
        "reviewed_at": application.reviewed_at.isoformat() + "Z" if application.reviewed_at else None,
        "review_notes": application.review_notes or None,
        "fields_requiring_changes": application.fields_requiring_changes or [],
        "can_edit": application.can_edit(),
        "can_submit": application.can_submit(),
    }


# ---------------------------------------------------------------------------
# Submission validation
# ---------------------------------------------------------------------------

def validate_for_submission(application):
    """
    Run the full pre-submission validation in one pass.
    Returns a dict of field-path → [error messages]. Empty dict means valid.
    """
    errors = {}

    # Status
    if not application.can_submit():
        errors["status"] = [
            f"Cannot submit from status '{application.status}'."
        ]
        return errors  # No point continuing if status is wrong.

    # Profession
    valid_professions = {p.value for p in MentorApplication.Profession}
    if not application.profession or application.profession not in valid_professions:
        errors["professional_profile.profession"] = ["A valid profession is required."]

    # Headline
    if not application.headline:
        errors["professional_profile.headline"] = ["This field is required."]
    elif not (10 <= len(application.headline) <= 120):
        errors["professional_profile.headline"] = ["Must be between 10 and 120 characters."]

    # Company — optional, max 120
    if application.company and len(application.company) > 120:
        errors["professional_profile.company"] = ["Maximum 120 characters."]

    # Years experience
    if application.years_experience is None:
        errors["professional_profile.years_experience"] = ["This field is required."]
    elif not (0 <= application.years_experience <= 60):
        errors["professional_profile.years_experience"] = ["Must be between 0 and 60."]

    # Bio
    if not application.bio:
        errors["professional_profile.bio"] = ["This field is required."]
    elif not (80 <= len(application.bio) <= 2000):
        errors["professional_profile.bio"] = ["Must be between 80 and 2,000 characters."]

    # LinkedIn URL (optional, must be https if set)
    if application.linkedin_url and not _is_valid_https_url(application.linkedin_url):
        errors["professional_profile.linkedin_url"] = ["Must be a valid HTTPS URL."]

    # Portfolio URL (optional)
    if application.portfolio_url and not _is_valid_https_url(application.portfolio_url):
        errors["professional_profile.portfolio_url"] = ["Must be a valid HTTPS URL."]

    # Categories
    if not application.categories.filter(is_active=True).exists():
        errors["category_ids"] = ["Select at least one active category."]

    # Expertise
    if not application.expertise.filter(is_active=True).exists():
        errors["expertise_ids"] = ["Select at least one expertise."]

    # Documents — at least one ready professional document
    # This check is skipped when REQUIRE_DOCUMENTS_FOR_SUBMISSION=False (default until S3 is configured).
    if getattr(settings, "REQUIRE_DOCUMENTS_FOR_SUBMISSION", False):
        ready_professional = application.documents.filter(
            document_type__in=list(PROFESSIONAL_DOC_TYPES),
            status=MentorVerificationDocument.DocumentStatus.READY,
        )
        if not ready_professional.exists():
            errors["documents.employment"] = [
                "Add at least one ready professional proof document (employment, certificate, education, or portfolio)."
            ]

    # Packages — at least one active package
    if not application.packages.filter(is_active=True).exists():
        errors["packages"] = ["Add at least one active session package."]

    # Availability
    if not application.availability_windows.filter(is_active=True).exists():
        errors["availability_windows"] = ["Add at least one availability window."]

    if not application.timezone or not _is_valid_iana_timezone(application.timezone):
        errors["timezone"] = ["A valid IANA timezone is required (e.g. 'Asia/Karachi')."]

    return errors


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

@transaction.atomic
def submit_application(application, confirm_accurate, terms_version, actor):
    """
    Atomically validate and submit the application.

    Returns (updated_application, errors_dict).
    On success errors_dict is empty and application.status == pending_review.
    """
    # Re-fetch with lock to prevent concurrent submissions.
    application = MentorApplication.objects.select_for_update().get(pk=application.pk)

    errors = validate_for_submission(application)
    if errors:
        return application, errors

    if not confirm_accurate:
        errors["confirm_information_accurate"] = [
            "You must confirm that the information is accurate."
        ]
        return application, errors

    if terms_version != CURRENT_TERMS_VERSION:
        errors["terms_version"] = [
            f"Please accept the current terms version '{CURRENT_TERMS_VERSION}'."
        ]
        return application, errors

    now = tz.now()
    is_resubmission = application.status == MentorApplication.Status.CHANGES_REQUESTED

    application.status = MentorApplication.Status.PENDING_REVIEW
    application.terms_version = terms_version
    application.terms_accepted_at = now
    application.submitted_at = now
    application.review_notes = ""
    application.fields_requiring_changes = []
    application.version += 1
    application.save()

    event_type = (
        MentorApplicationReviewEvent.EventType.RESUBMITTED
        if is_resubmission
        else MentorApplicationReviewEvent.EventType.SUBMITTED
    )
    MentorApplicationReviewEvent(
        application=application,
        actor=actor,
        event_type=event_type,
        metadata={"terms_version": terms_version},
    ).save()

    return application, {}


# ---------------------------------------------------------------------------
# Reviewer actions
# ---------------------------------------------------------------------------

@transaction.atomic
def approve_application(application, reviewer, notes=""):
    """
    Atomically approve a pending_review application.
    Creates/updates production MentorProfile, SessionPackage, AvailabilityWindow.
    Idempotent — retrying does not duplicate records.
    """
    application = MentorApplication.objects.select_for_update().get(pk=application.pk)

    if application.status != MentorApplication.Status.PENDING_REVIEW:
        raise ValueError(
            f"Expected pending_review, got '{application.status}'.",
            application.status,
        )

    now = tz.now()
    user = application.user

    # Create or update production MentorProfile.
    mentor_profile, _ = MentorProfile.objects.update_or_create(
        user=user,
        defaults={
            "headline": application.headline or "",
            "company": application.company or "",
            "bio": application.bio or "",
            "years_experience": application.years_experience or 0,
            "is_active": True,
            "is_verified": True,
        },
    )

    # Copy categories and expertise.
    mentor_profile.categories.set(application.categories.all())
    mentor_profile.expertise.set(application.expertise.all())

    # Create or update production SessionPackages (idempotent by duration).
    for draft_pkg in application.packages.filter(is_active=True):
        SessionPackage.objects.update_or_create(
            mentor=mentor_profile,
            duration_minutes=draft_pkg.duration_minutes,
            defaults={
                "price_usd": draft_pkg.price_usd,
                "is_popular": draft_pkg.is_popular,
                "is_active": True,
            },
        )

    # Create or update production AvailabilityWindows (idempotent by weekday+starts_at).
    # Convert ISO weekday (1=Mon) to the existing model's 0-based weekday (0=Mon).
    for draft_win in application.availability_windows.filter(is_active=True):
        zero_based_weekday = draft_win.weekday - 1
        AvailabilityWindow.objects.update_or_create(
            mentor=mentor_profile,
            weekday=zero_based_weekday,
            starts_at=draft_win.starts_at,
            defaults={
                "ends_at": draft_win.ends_at,
                "timezone": application.timezone or "UTC",
                "slot_interval_minutes": draft_win.slot_interval_minutes,
                "is_active": True,
            },
        )

    # Update application status.
    application.status = MentorApplication.Status.VERIFIED
    application.reviewer = reviewer
    application.reviewed_at = now
    application.review_notes = notes
    application.version += 1
    application.save()

    MentorApplicationReviewEvent(
        application=application,
        actor=reviewer,
        event_type=MentorApplicationReviewEvent.EventType.APPROVED,
        metadata={"notes": notes},
    ).save()

    return application


@transaction.atomic
def request_changes(application, reviewer, notes, fields_requiring_changes):
    """Move application to changes_requested with reviewer notes."""
    application = MentorApplication.objects.select_for_update().get(pk=application.pk)

    if application.status != MentorApplication.Status.PENDING_REVIEW:
        raise ValueError(
            f"Expected pending_review, got '{application.status}'.",
            application.status,
        )

    now = tz.now()
    application.status = MentorApplication.Status.CHANGES_REQUESTED
    application.reviewer = reviewer
    application.reviewed_at = now
    application.review_notes = notes
    application.fields_requiring_changes = fields_requiring_changes or []
    application.version += 1
    application.save()

    MentorApplicationReviewEvent(
        application=application,
        actor=reviewer,
        event_type=MentorApplicationReviewEvent.EventType.CHANGES_REQUESTED,
        metadata={"notes": notes, "fields": fields_requiring_changes},
    ).save()

    return application


@transaction.atomic
def reject_application(application, reviewer, reason_code, notes):
    """Move application to rejected."""
    application = MentorApplication.objects.select_for_update().get(pk=application.pk)

    if application.status != MentorApplication.Status.PENDING_REVIEW:
        raise ValueError(
            f"Expected pending_review, got '{application.status}'.",
            application.status,
        )

    now = tz.now()
    application.status = MentorApplication.Status.REJECTED
    application.reviewer = reviewer
    application.reviewed_at = now
    application.review_notes = notes
    application.version += 1
    application.save()

    MentorApplicationReviewEvent(
        application=application,
        actor=reviewer,
        event_type=MentorApplicationReviewEvent.EventType.REJECTED,
        metadata={"reason_code": reason_code, "notes": notes},
    ).save()

    return application


@transaction.atomic
def reopen_application(application, staff_user):
    """Staff-only: reopen a rejected application back to draft."""
    application = MentorApplication.objects.select_for_update().get(pk=application.pk)

    if application.status != MentorApplication.Status.REJECTED:
        raise ValueError(
            f"Can only reopen rejected applications, got '{application.status}'.",
            application.status,
        )

    application.status = MentorApplication.Status.DRAFT
    application.review_notes = ""
    application.fields_requiring_changes = []
    application.version += 1
    application.save()

    MentorApplicationReviewEvent(
        application=application,
        actor=staff_user,
        event_type=MentorApplicationReviewEvent.EventType.REOPENED,
        metadata={},
    ).save()

    return application


# ---------------------------------------------------------------------------
# Storage helpers — real S3 presigned URL implementation
# ---------------------------------------------------------------------------

def _get_s3_client():
    """Return a boto3 S3 client using credentials from settings."""
    import boto3
    return boto3.client(
        "s3",
        region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
        aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", ""),
    )


def _s3_configured():
    """Return True if S3 credentials are present in settings."""
    return bool(
        getattr(settings, "AWS_ACCESS_KEY_ID", "")
        and getattr(settings, "AWS_SECRET_ACCESS_KEY", "")
        and getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
    )


def generate_upload_url(document):
    """
    Generate a short-lived presigned PUT URL for direct-to-S3 upload.
    Falls back to a placeholder URL when S3 is not configured.

    Returns dict with: storage_key, upload_url, upload_method, upload_headers, expires_at
    """
    storage_key = f"mentor-docs/{document.application_id}/{uuid.uuid4().hex}/{document.original_file_name}"
    expires_at = tz.now() + timedelta(minutes=10)

    if not _s3_configured():
        # Stub for local development without S3 credentials.
        upload_url = f"https://private-storage.example/upload?key={storage_key}"
        return {
            "storage_key": storage_key,
            "upload_url": upload_url,
            "upload_method": "PUT",
            "upload_headers": {"Content-Type": document.content_type},
            "expires_at": expires_at,
        }

    import boto3
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    s3 = _get_s3_client()

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": storage_key,
            "ContentType": document.content_type,
            "ContentLength": document.size_bytes,
        },
        ExpiresIn=600,  # 10 minutes
    )

    return {
        "storage_key": storage_key,
        "upload_url": upload_url,
        "upload_method": "PUT",
        "upload_headers": {"Content-Type": document.content_type},
        "expires_at": expires_at,
    }


def generate_download_url(document):
    """
    Generate a short-lived presigned GET URL for reviewer access.
    Falls back to a placeholder URL when S3 is not configured.
    """
    expires_at = tz.now() + timedelta(minutes=15)

    if not _s3_configured():
        download_url = f"https://private-storage.example/download?key={document.storage_key}"
        return {"download_url": download_url, "expires_at": expires_at}

    bucket = settings.AWS_STORAGE_BUCKET_NAME
    s3 = _get_s3_client()

    download_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": document.storage_key},
        ExpiresIn=900,  # 15 minutes
    )

    return {"download_url": download_url, "expires_at": expires_at}


def verify_uploaded_document(document, checksum_sha256):
    """
    Verify an uploaded document by checking it exists in S3, then transition to scanning.

    When S3 is configured:
      1. HEAD the object to confirm it exists and size matches.
      2. Verify checksum_sha256 is present and correct length.
      3. Move status to scanning, then immediately mark ready (until async scan worker is wired up).

    When S3 is not configured (local dev stub):
      Trusts the client-supplied checksum and marks the document ready immediately.

    Returns (ok: bool, error_message: str | None)
    """
    if document.status != MentorVerificationDocument.DocumentStatus.REQUESTED:
        return False, "Document has already been confirmed or is in an invalid state."

    if not checksum_sha256 or len(checksum_sha256) != 64:
        return False, "checksum_sha256 must be a 64-character hex SHA-256 digest."

    if _s3_configured():
        try:
            import boto3
            from botocore.exceptions import ClientError

            bucket = settings.AWS_STORAGE_BUCKET_NAME
            s3 = _get_s3_client()
            head = s3.head_object(Bucket=bucket, Key=document.storage_key)

            # Verify the object size matches what the client declared.
            actual_size = head.get("ContentLength", 0)
            if actual_size != document.size_bytes:
                return False, (
                    f"Uploaded file size ({actual_size} bytes) does not match "
                    f"declared size ({document.size_bytes} bytes)."
                )

        except Exception as exc:
            return False, f"Could not verify upload in storage: {exc}"

    document.checksum_sha256 = checksum_sha256
    document.status = MentorVerificationDocument.DocumentStatus.SCANNING
    document.uploaded_at = tz.now()
    document.save(update_fields=["checksum_sha256", "status", "uploaded_at", "updated_at"])

    # TODO: replace with async task once Celery is wired up.
    # scan_document_task.delay(document.id)
    _mark_document_ready(document)

    return True, None


def _mark_document_ready(document):
    """Mark a document as ready after a successful scan. Called by the scan worker."""
    document.status = MentorVerificationDocument.DocumentStatus.READY
    document.save(update_fields=["status", "updated_at"])
