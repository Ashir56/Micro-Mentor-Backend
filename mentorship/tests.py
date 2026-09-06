from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import MentorProfile, MentorshipSession, SessionPackage, UserProfile


class RootHealthTests(TestCase):
    def test_root_returns_ok(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_health_returns_ok(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_mentor_profile_create_requires_authentication(self):
        response = self.client.post(
            "/api/mentor-profiles/",
            {"headline": "Test Mentor", "company": "Example"},
        )
        self.assertEqual(response.status_code, 401)


class PackageApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="mentor@example.com", email="mentor@example.com", password="secret")
        self.mentor_profile = MentorProfile.objects.create(user=self.user, headline="Test Mentor", company="Example", bio="Bio")
        self.client.force_authenticate(user=self.user)

    def test_create_package_requires_mentor_id(self):
        response = self.client.post(reverse("package-list"), {"duration_minutes": 60, "price_usd": 20}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("mentor_id", response.json())

    def test_create_package_accepts_mentor_profile_id_alias(self):
        response = self.client.post(
            reverse("package-list"),
            {"mentor_profile_id": self.mentor_profile.id, "duration_minutes": 60, "price_usd": 20},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["mentor_id"], self.mentor_profile.id)


class ConversationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.mentor_user = get_user_model().objects.create_user(
            username="mentor.chat@example.com",
            email="mentor.chat@example.com",
            password="secret",
        )
        self.mentee_user = get_user_model().objects.create_user(
            username="mentee.chat@example.com",
            email="mentee.chat@example.com",
            password="secret",
        )
        UserProfile.objects.create(user=self.mentor_user, role=UserProfile.Role.MENTOR)
        UserProfile.objects.create(user=self.mentee_user, role=UserProfile.Role.MENTEE)
        self.mentor_profile = MentorProfile.objects.create(
            user=self.mentor_user,
            headline="Chat Mentor",
            company="Example",
            bio="Bio",
            allow_pre_booking_messages=True,
            pre_booking_message_limit=2,
        )

    def test_inquiry_conversation_is_reused_and_limits_messages(self):
        self.client.force_authenticate(user=self.mentee_user)

        create_response = self.client.post(
            reverse("conversation-list"),
            {"type": "inquiry", "mentor_id": self.mentor_profile.id},
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        conversation_id = create_response.json()["id"]

        reuse_response = self.client.post(
            reverse("conversation-list"),
            {"type": "inquiry", "mentor_id": self.mentor_profile.id},
            format="json",
        )
        self.assertEqual(reuse_response.status_code, 200)
        self.assertEqual(reuse_response.json()["id"], conversation_id)

        for idx in range(2):
            message_response = self.client.post(
                reverse("send-message", args=[conversation_id]),
                {"body": f"hello {idx}"},
                format="json",
            )
            self.assertEqual(message_response.status_code, 201)

        blocked_response = self.client.post(
            reverse("send-message", args=[conversation_id]),
            {"body": "too many"},
            format="json",
        )
        self.assertEqual(blocked_response.status_code, 403)

    def test_session_conversation_requires_a_paid_session(self):
        self.client.force_authenticate(user=self.mentee_user)
        package = SessionPackage.objects.create(mentor=self.mentor_profile, duration_minutes=60, price_usd=20)
        session = MentorshipSession.objects.create(
            mentee=self.mentee_user,
            mentor=self.mentor_profile,
            package=package,
            starts_at="2099-01-01T10:00:00Z",
            status=MentorshipSession.Status.PENDING_PAYMENT,
        )

        response = self.client.post(
            reverse("conversation-list"),
            {"type": "session", "session_id": session.id},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
