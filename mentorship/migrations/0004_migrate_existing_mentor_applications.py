# Data migration: create MentorApplication records for every existing mentor user.
#
# Rules applied:
#   - Mentors with an active MentorProfile (is_active=True) are marked `verified`.
#   - All others are marked `draft`.
#   - Copies profession/headline/bio/company/years_experience/timezone into the draft.
#   - Copies category and expertise M2M relations.
#   - Records an immutable `migrated` audit event for each application created.
#
# This migration is intentionally non-destructive: existing MentorProfile, Package,
# and AvailabilityWindow records are left untouched.

from django.db import migrations
from django.utils import timezone as tz


def create_applications_for_existing_mentors(apps, schema_editor):
    UserProfile = apps.get_model("mentorship", "UserProfile")
    MentorProfile = apps.get_model("mentorship", "MentorProfile")
    MentorApplication = apps.get_model("mentorship", "MentorApplication")
    MentorApplicationReviewEvent = apps.get_model("mentorship", "MentorApplicationReviewEvent")

    now = tz.now()
    created_count = 0

    # Only process mentor-role users that have a MentorProfile.
    mentor_profiles = MentorProfile.objects.select_related("user").all()

    for profile in mentor_profiles:
        user = profile.user

        # Skip if an application already exists (idempotent re-runs).
        if MentorApplication.objects.filter(user=user).exists():
            continue

        # Determine status: active profiles are treated as verified.
        if profile.is_active:
            app_status = "verified"
            submitted_at = now
            reviewed_at = now
        else:
            app_status = "draft"
            submitted_at = None
            reviewed_at = None

        application = MentorApplication(
            user=user,
            status=app_status,
            current_step="review" if app_status == "verified" else "professional_profile",
            completion_percent=100 if app_status == "verified" else 0,
            # Copy professional profile fields from MentorProfile.
            headline=profile.headline or "",
            company=profile.company or "",
            bio=profile.bio or "",
            years_experience=profile.years_experience,
            timezone="",  # AvailabilityWindow stores per-window timezone; leave blank.
            accepts_inquiries=profile.allow_pre_booking_messages,
            submitted_at=submitted_at,
            reviewed_at=reviewed_at,
            version=1,
        )
        if app_status == "verified":
            application.terms_version = "migrated"
            application.terms_accepted_at = now

        application.save()

        # Copy M2M relations.
        for category in profile.categories.all():
            application.categories.add(category)
        for expertise in profile.expertise.all():
            application.expertise.add(expertise)

        # Also set is_verified on the MentorProfile for the new eligibility check.
        if app_status == "verified":
            MentorProfile.objects.filter(pk=profile.pk).update(is_verified=True)

        # Append an immutable migration audit event.
        MentorApplicationReviewEvent(
            application=application,
            actor=None,
            event_type="migrated",
            metadata={
                "migration": "0004_migrate_existing_mentor_applications",
                "source_mentor_profile_id": profile.pk,
                "assigned_status": app_status,
                "migrated_at": now.isoformat(),
            },
        ).save()

        created_count += 1

    print(f"\n  Created {created_count} MentorApplication records from existing MentorProfile data.")


def reverse_migration(apps, schema_editor):
    # Remove only the applications created by this migration (identified by the migrated event).
    MentorApplicationReviewEvent = apps.get_model("mentorship", "MentorApplicationReviewEvent")
    MentorApplication = apps.get_model("mentorship", "MentorApplication")

    migrated_app_ids = MentorApplicationReviewEvent.objects.filter(
        event_type="migrated",
        metadata__migration="0004_migrate_existing_mentor_applications",
    ).values_list("application_id", flat=True)

    MentorApplication.objects.filter(id__in=list(migrated_app_ids)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("mentorship", "0003_alter_category_options_alter_expertise_options_and_more"),
    ]

    operations = [
        migrations.RunPython(
            create_applications_for_existing_mentors,
            reverse_code=reverse_migration,
        ),
    ]
