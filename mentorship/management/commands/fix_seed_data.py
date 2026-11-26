"""
Management command: fix_seed_data

Marks all active MentorProfile records as is_verified=True so they appear
in discovery. Run this once against the live database after deploying.

Usage:
    python manage.py fix_seed_data
"""
from django.core.management.base import BaseCommand
from mentorship.models import MentorProfile, UserProfile


class Command(BaseCommand):
    help = "Mark all active mentor profiles as verified so they appear in discovery."

    def handle(self, *args, **options):
        # Mark all active MentorProfiles as verified
        updated = MentorProfile.objects.filter(
            is_active=True, is_verified=False
        ).update(is_verified=True)
        self.stdout.write(
            self.style.SUCCESS(f"Marked {updated} MentorProfile(s) as is_verified=True.")
        )

        # Also ensure their UserProfile role is set to mentor
        mentor_user_ids = MentorProfile.objects.filter(
            is_active=True
        ).values_list("user_id", flat=True)

        role_updated = UserProfile.objects.filter(
            user_id__in=mentor_user_ids,
            role=UserProfile.Role.MENTEE,
        ).update(role=UserProfile.Role.MENTOR)

        self.stdout.write(
            self.style.SUCCESS(f"Fixed {role_updated} UserProfile role(s) to mentor.")
        )

        self.stdout.write(self.style.SUCCESS("Done."))
