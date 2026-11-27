"""
Management command: seed_availability

Creates sample AvailabilityWindow records for all verified mentors
so the slot-generation endpoint returns actual data.

Usage:
    python manage.py seed_availability
"""
from django.core.management.base import BaseCommand
from mentorship.models import AvailabilityWindow, MentorProfile
from datetime import time


SAMPLE_WINDOWS = [
    # (weekday 0=Mon, starts_at, ends_at, interval)
    (0, time(9, 0),  time(17, 0), 30),   # Monday 9am-5pm
    (2, time(9, 0),  time(17, 0), 30),   # Wednesday 9am-5pm
    (4, time(10, 0), time(15, 0), 60),   # Friday 10am-3pm
]


class Command(BaseCommand):
    help = "Seed availability windows for all verified mentors."

    def handle(self, *args, **options):
        mentors = MentorProfile.objects.filter(is_verified=True, is_active=True)
        created = 0
        for mentor in mentors:
            if mentor.availability.filter(is_active=True).exists():
                self.stdout.write(f"  Mentor {mentor.id} already has windows, skipping.")
                continue
            for (weekday, starts, ends, interval) in SAMPLE_WINDOWS:
                AvailabilityWindow.objects.get_or_create(
                    mentor=mentor,
                    weekday=weekday,
                    starts_at=starts,
                    defaults={
                        "ends_at": ends,
                        "timezone": "America/New_York",
                        "slot_interval_minutes": interval,
                        "is_active": True,
                    },
                )
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f"Created {created} availability window(s) for {mentors.count()} mentor(s)."
        ))
