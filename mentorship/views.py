from django.contrib.auth import authenticate, get_user_model, logout
from django.db import IntegrityError, transaction
from django.db.models import Avg, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from urllib.parse import parse_qs
import json

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AvailabilityWindow,
    Category,
    Conversation,
    Expertise,
    MentorApplication,
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
from .permissions import IsProvider, IsMentorUser, IsReviewer
from . import services as onboarding_services


ProviderOrAdmin = IsProvider | IsAdminUser


def _tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "access_token": str(refresh.access_token),
        "refresh_token": str(refresh),
    }


def _get_request_data(request):
    try:
        data = request.data
    except ParseError:
        data = None

    if data:
        return data
    if request.body:
        try:
            return json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            text = request.body.decode("utf-8", errors="replace")
            parsed = parse_qs(text, keep_blank_values=True)
            return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    return {}


def _mentor_summary(mentor):
    rating = mentor.reviews.aggregate(avg=Avg("rating"))["avg"] or 0
    session_count = mentor.sessions.exclude(status=MentorshipSession.Status.DRAFT).count()
    user = mentor.user
    profile = getattr(user, "profile", None)
    return {
        "id": mentor.id,
        "name": user.get_full_name() or user.email,
        "headline": mentor.headline,
        "company": mentor.company,
        "city": profile.city if profile else "",
        "rating": round(rating, 1),
        "sessions": session_count,
        "repeat_rate": float(mentor.repeat_rate),
        "verified": profile.is_linkedin_verified if profile else False,
        "starting_price": min((float(pkg.price_usd) for pkg in mentor.packages.filter(is_active=True)), default=None),
        "expertise": list(mentor.expertise.values_list("name", flat=True)),
    }


def _category_payload(category):
    return {
        "id": category.id,
        "name": category.name,
        "emoji": category.emoji,
        "slug": category.slug,
        "is_active": category.is_active,
        "sort_order": category.sort_order,
    }


def _expertise_payload(expertise):
    return {
        "id": expertise.id,
        "name": expertise.name,
        "slug": expertise.slug,
        "is_active": expertise.is_active,
        "sort_order": expertise.sort_order,
    }


def _package_payload(package):
    return {
        "id": package.id,
        "mentor_id": package.mentor_id,
        "duration_minutes": package.duration_minutes,
        "price_usd": float(package.price_usd),
        "is_popular": package.is_popular,
        "is_active": package.is_active,
    }


def _availability_window_payload(window):
    return {
        "id": window.id,
        "mentor_id": window.mentor_id,
        "weekday": window.weekday,
        "starts_at": str(window.starts_at),
        "ends_at": str(window.ends_at),
        "timezone": window.timezone,
        "slot_interval_minutes": window.slot_interval_minutes,
        "is_active": window.is_active,
    }


def _review_payload(review):
    return {
        "id": review.id,
        "session_id": review.session_id,
        "mentor_id": review.mentor_id,
        "reviewer_id": review.reviewer_id,
        "rating": review.rating,
        "body": review.body,
        "created_at": review.created_at,
    }


def _data_list(data, key):
    if hasattr(data, "getlist"):
        values = data.getlist(key)
        if len(values) > 1:
            return values
    else:
        values = []
    value = data.get(key, values)
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return value
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _data_bool(data, key, default=False):
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _get_requested_mentor_profile(request):
    data = _get_request_data(request)
    mentor_id = data.get("mentor_id")
    if mentor_id in (None, ""):
        mentor_id = data.get("mentor_profile_id")
    if mentor_id in (None, ""):
        return None, Response({"mentor_id": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

    try:
        mentor_id = int(mentor_id)
    except (TypeError, ValueError):
        return None, Response({"mentor_id": ["A valid integer is required."]}, status=status.HTTP_400_BAD_REQUEST)

    mentor = MentorProfile.objects.filter(id=mentor_id).first()
    if mentor is None:
        return None, Response({"mentor_id": ["No MentorProfile matches the given query."]}, status=status.HTTP_404_NOT_FOUND)
    return mentor, None


def _user_role(user):
    profile = getattr(user, "profile", None)
    return profile.role if profile else UserProfile.Role.MENTEE


def _participant_name(user):
    return user.get_full_name() or user.email if user else ""


def _conversation_message_payload(message):
    return {
        "id": message.id,
        "sender_id": message.sender_id,
        "sender_name": _participant_name(message.sender),
        "body": message.body,
        "created_at": message.created_at,
        "read_at": message.read_at,
    }


def _conversation_payload(conversation, current_user):
    last_message = conversation.messages.order_by("-created_at").first()
    other_user = conversation.mentor if current_user.id == conversation.mentee_id else conversation.mentee
    return {
        "id": conversation.id,
        "type": conversation.type,
        "status": conversation.status,
        "mentor_id": conversation.mentor_id,
        "mentee_id": conversation.mentee_id,
        "session_id": conversation.session_id,
        "other_user_id": other_user.id if other_user else None,
        "other_user_name": _participant_name(other_user),
        "last_message": last_message.body if last_message else "",
        "last_message_at": last_message.created_at if last_message else None,
        "updated_at": conversation.updated_at,
    }


def _get_conversation_for_user(user, conversation_id):
    return get_object_or_404(
        Conversation.objects.filter(participants=user).select_related("mentor", "mentee", "session"),
        id=conversation_id,
    )


def _can_manage_mentor(request, mentor):
    if not getattr(request.user, "is_authenticated", False):
        return False
    if getattr(request.user, "is_staff", False):
        return True
    return request.user.id == mentor.user_id


@api_view(("GET", "POST"))
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def category_list(request):
    if request.method == "GET":
        return Response({"results": [_category_payload(category) for category in Category.objects.all()]})

    try:
        category = Category.objects.create(
            name=request.data.get("name", ""),
            emoji=request.data.get("emoji", ""),
            slug=request.data.get("slug", ""),
        )
    except IntegrityError:
        return Response({"detail": "Category with this name or slug already exists."}, status=status.HTTP_409_CONFLICT)
    return Response(_category_payload(category), status=status.HTTP_201_CREATED)


@api_view(("GET", "PATCH", "DELETE"))
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def category_detail(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == "GET":
        return Response(_category_payload(category))

    if request.method == "PATCH":
        category.name = request.data.get("name", category.name)
        category.emoji = request.data.get("emoji", category.emoji)
        category.slug = request.data.get("slug", category.slug)
        category.save()
        return Response(_category_payload(category))

    category.delete()
    return Response({"deleted": True})


@api_view(("GET", "POST"))
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def expertise_list(request):
    if request.method == "GET":
        return Response({"results": [_expertise_payload(expertise) for expertise in Expertise.objects.all()]})

    try:
        expertise = Expertise.objects.create(
            name=request.data.get("name", ""),
            slug=request.data.get("slug", ""),
        )
    except IntegrityError:
        return Response({"detail": "Expertise with this name or slug already exists."}, status=status.HTTP_409_CONFLICT)
    return Response(_expertise_payload(expertise), status=status.HTTP_201_CREATED)


@api_view(("GET", "PATCH", "DELETE"))
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def expertise_detail(request, expertise_id):
    expertise = get_object_or_404(Expertise, id=expertise_id)
    if request.method == "GET":
        return Response(_expertise_payload(expertise))

    if request.method == "PATCH":
        expertise.name = request.data.get("name", expertise.name)
        expertise.slug = request.data.get("slug", expertise.slug)
        expertise.save()
        return Response(_expertise_payload(expertise))

    expertise.delete()
    return Response({"deleted": True})


@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def mentor_profile_list(request):
    if request.method == "GET":
        mentors = MentorProfile.objects.filter(is_active=True).prefetch_related("expertise", "packages", "categories")
        return Response(
            {
                "results": [
                    {
                        "id": mentor.id,
                        "name": mentor.user.get_full_name() or mentor.user.email,
                        "headline": mentor.headline,
                        "company": mentor.company,
                        "bio": mentor.bio,
                        "years_experience": mentor.years_experience,
                        "categories": list(mentor.categories.values_list("name", flat=True)),
                        "expertise": list(mentor.expertise.values_list("name", flat=True)),
                        "starting_price": min(
                            (float(pkg.price_usd) for pkg in mentor.packages.filter(is_active=True)),
                            default=None,
                        ),
                        "is_active": mentor.is_active,
                    }
                    for mentor in mentors
                ]
            }
        )
    if MentorProfile.objects.filter(user=request.user).exists():
        return Response({"detail": "Mentor profile already exists for this user."}, status=status.HTTP_409_CONFLICT)

    data = _get_request_data(request)
    mentor = MentorProfile.objects.create(
        user=request.user,
        headline=data.get("headline", ""),
        company=data.get("company", ""),
        bio=data.get("bio", ""),
        years_experience=data.get("years_experience", 0),
        repeat_rate=data.get("repeat_rate", 0),
        profile_completion=data.get("profile_completion", 0),
        intro_video_url=data.get("intro_video_url", ""),
        auto_confirm_bookings=_data_bool(data, "auto_confirm_bookings", True),
        is_active=_data_bool(data, "is_active", True),
    )
    category_ids = _data_list(data, "category_ids")
    expertise_ids = _data_list(data, "expertise_ids")
    if category_ids:
        mentor.categories.set(Category.objects.filter(id__in=category_ids))
    if expertise_ids:
        mentor.expertise.set(Expertise.objects.filter(id__in=expertise_ids))

    return Response(
        {"id": mentor.id, "headline": mentor.headline, "company": mentor.company, "is_active": mentor.is_active},
        status=status.HTTP_201_CREATED,
    )


@api_view(("GET", "PATCH", "DELETE"))
@authentication_classes([JWTAuthentication])
@permission_classes([AllowAny])
@transaction.atomic
def mentor_profile_detail(request, mentor_id):
    mentor = get_object_or_404(MentorProfile.objects.prefetch_related("expertise", "packages", "categories"), id=mentor_id)
    if request.method == "GET":
        return Response(
            {
                "id": mentor.id,
                "headline": mentor.headline,
                "company": mentor.company,
                "bio": mentor.bio,
                "years_experience": mentor.years_experience,
                "repeat_rate": float(mentor.repeat_rate),
                "profile_completion": mentor.profile_completion,
                "intro_video_url": mentor.intro_video_url,
                "auto_confirm_bookings": mentor.auto_confirm_bookings,
                "is_active": mentor.is_active,
                "categories": list(mentor.categories.values_list("id", flat=True)),
                "expertise": list(mentor.expertise.values_list("id", flat=True)),
            }
        )

    if not _can_manage_mentor(request, mentor):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "PATCH":
        data = _get_request_data(request)
        mentor.headline = data.get("headline", mentor.headline)
        mentor.company = data.get("company", mentor.company)
        mentor.bio = data.get("bio", mentor.bio)
        mentor.years_experience = data.get("years_experience", mentor.years_experience)
        mentor.repeat_rate = data.get("repeat_rate", mentor.repeat_rate)
        mentor.profile_completion = data.get("profile_completion", mentor.profile_completion)
        mentor.intro_video_url = data.get("intro_video_url", mentor.intro_video_url)
        mentor.auto_confirm_bookings = _data_bool(data, "auto_confirm_bookings", mentor.auto_confirm_bookings)
        mentor.is_active = _data_bool(data, "is_active", mentor.is_active)
        mentor.save()
        if "category_ids" in data:
            mentor.categories.set(Category.objects.filter(id__in=_data_list(data, "category_ids")))
        if "expertise_ids" in data:
            mentor.expertise.set(Expertise.objects.filter(id__in=_data_list(data, "expertise_ids")))
        return Response({"id": mentor.id, "headline": mentor.headline, "company": mentor.company, "is_active": mentor.is_active})

    mentor.is_active = False
    mentor.save(update_fields=["is_active"])
    return Response({"deleted": True})


@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def package_list(request):
    if request.method == "GET":
        packages = SessionPackage.objects.all()
        if request.query_params.get("mentor_id"):
            packages = packages.filter(mentor_id=request.query_params["mentor_id"])
        return Response({"results": [_package_payload(package) for package in packages]})

    data = _get_request_data(request)
    mentor, error = _get_requested_mentor_profile(request)
    if error is not None:
        return error
    if not _can_manage_mentor(request, mentor):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    package = SessionPackage.objects.create(
        mentor=mentor,
        duration_minutes=data.get("duration_minutes", 0),
        price_usd=data.get("price_usd", 0),
        is_popular=_data_bool(data, "is_popular", False),
        is_active=_data_bool(data, "is_active", True),
    )
    return Response(_package_payload(package), status=status.HTTP_201_CREATED)


@api_view(("GET", "PATCH", "DELETE"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def package_detail(request, package_id):
    package = get_object_or_404(SessionPackage, id=package_id)
    if request.method == "GET":
        return Response(_package_payload(package))

    if not _can_manage_mentor(request, package.mentor):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "PATCH":
        package.duration_minutes = request.data.get("duration_minutes", package.duration_minutes)
        package.price_usd = request.data.get("price_usd", package.price_usd)
        package.is_popular = _data_bool(request.data, "is_popular", package.is_popular)
        package.is_active = _data_bool(request.data, "is_active", package.is_active)
        package.save()
        return Response(_package_payload(package))

    package.delete()
    return Response({"deleted": True})


@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def availability_window_list(request):
    if request.method == "GET":
        windows = AvailabilityWindow.objects.all()
        if request.query_params.get("mentor_id"):
            windows = windows.filter(mentor_id=request.query_params["mentor_id"])
        return Response({"results": [_availability_window_payload(window) for window in windows]})

    data = _get_request_data(request)

    # Ownership: derive the mentor profile from the authenticated user, not client-supplied ID.
    # Accept an explicit mentor_id only if the caller is staff; otherwise always use the token owner.
    if request.user.is_staff:
        mentor, error = _get_requested_mentor_profile(request)
        if error is not None:
            return error
        if not _can_manage_mentor(request, mentor):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    else:
        mentor = MentorProfile.objects.filter(user=request.user).first()
        if mentor is None:
            return Response({"detail": "No mentor profile found for this account."}, status=status.HTTP_403_FORBIDDEN)

    window = AvailabilityWindow.objects.create(
        mentor=mentor,
        weekday=data.get("weekday", 0),
        starts_at=data.get("starts_at", "00:00"),
        ends_at=data.get("ends_at", "00:00"),
        timezone=data.get("timezone", "America/Los_Angeles"),
        slot_interval_minutes=data.get("slot_interval_minutes", 15),
        is_active=_data_bool(data, "is_active", True),
    )
    return Response(_availability_window_payload(window), status=status.HTTP_201_CREATED)


@api_view(("GET", "PATCH", "DELETE"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def availability_window_detail(request, window_id):
    window = get_object_or_404(AvailabilityWindow, id=window_id)
    if request.method == "GET":
        return Response(_availability_window_payload(window))

    if not _can_manage_mentor(request, window.mentor):
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "PATCH":
        window.weekday = request.data.get("weekday", window.weekday)
        window.starts_at = request.data.get("starts_at", window.starts_at)
        window.ends_at = request.data.get("ends_at", window.ends_at)
        window.timezone = request.data.get("timezone", window.timezone)
        window.slot_interval_minutes = request.data.get("slot_interval_minutes", window.slot_interval_minutes)
        window.is_active = _data_bool(request.data, "is_active", window.is_active)
        window.save()
        return Response(_availability_window_payload(window))

    window.delete()
    return Response({"deleted": True})


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def payment_detail(request, session_id):
    payment = get_object_or_404(Payment, session_id=session_id)
    if payment.session.mentee != request.user and payment.session.mentor.user != request.user:
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    return Response(
        {
            "session_id": payment.session_id,
            "amount_usd": float(payment.amount_usd),
            "status": payment.status,
            "provider": payment.provider,
            "provider_payment_id": payment.provider_payment_id,
            "paid_at": payment.paid_at,
        }
    )


@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def review_list(request):
    if request.method == "GET":
        reviews = Review.objects.all()
        if request.query_params.get("mentor_id"):
            reviews = reviews.filter(mentor_id=request.query_params["mentor_id"])
        if request.query_params.get("session_id"):
            reviews = reviews.filter(session_id=request.query_params["session_id"])
        return Response({"results": [_review_payload(review) for review in reviews.select_related("reviewer", "mentor")]})

    session = get_object_or_404(MentorshipSession, id=request.data.get("session_id"), mentee=request.user)
    review, _ = Review.objects.update_or_create(
        session=session,
        defaults={
            "reviewer": request.user,
            "mentor": session.mentor,
            "rating": request.data.get("rating", 5),
            "body": request.data.get("body", ""),
        },
    )
    return Response({"review_id": review.id, "rating": review.rating}, status=status.HTTP_201_CREATED)


@api_view(("GET", "PATCH", "DELETE"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def review_detail(request, review_id):
    review = get_object_or_404(Review, id=review_id)
    if request.method == "GET":
        return Response(_review_payload(review))

    if request.user != review.reviewer and not request.user.is_staff:
        return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "PATCH":
        review.rating = request.data.get("rating", review.rating)
        review.body = request.data.get("body", review.body)
        review.save()
        return Response({"id": review.id, "rating": review.rating, "body": review.body})

    review.delete()
    return Response({"deleted": True})


@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def conversations(request):
    if request.method == "GET":
        conversations_qs = request.user.conversations.prefetch_related("messages").select_related("mentor", "mentee", "session")
        results = [_conversation_payload(conversation, request.user) for conversation in conversations_qs]
        return Response({"results": results})

    data = _get_request_data(request)
    conversation_type = (data.get("type") or "inquiry").lower()

    if conversation_type == Conversation.Type.INQUIRY:
        if _user_role(request.user) != UserProfile.Role.MENTEE:
            return Response({"detail": "Only mentees can start inquiry conversations."}, status=status.HTTP_403_FORBIDDEN)

        # Accept domain payload: {type, mentor_id} where mentor_id is MentorProfile.id
        # Also accept legacy {type, mentor_profile_id} alias
        raw_mentor_id = data.get("mentor_id") or data.get("mentor_profile_id")
        if raw_mentor_id in (None, ""):
            return Response({"detail": "mentor_id is required for inquiry conversations."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            mentor_profile_id = int(raw_mentor_id)
        except (TypeError, ValueError):
            return Response({"detail": "mentor_id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        mentor = MentorProfile.objects.filter(id=mentor_profile_id).first()
        if mentor is None:
            return Response({"detail": "Mentor not found."}, status=status.HTTP_404_NOT_FOUND)

        if not mentor.allow_pre_booking_messages:
            return Response({"detail": "This mentor is not accepting inquiry chats."}, status=status.HTTP_403_FORBIDDEN)

        existing = (
            Conversation.objects.filter(
                type=Conversation.Type.INQUIRY,
                mentor_id=mentor.user_id,
                mentee_id=request.user.id,
                status=Conversation.Status.OPEN,
            )
            .first()
        )
        if existing is not None:
            return Response({"id": existing.id, "type": existing.type, "status": existing.status}, status=status.HTTP_200_OK)

        conversation = Conversation.objects.create(
            type=Conversation.Type.INQUIRY,
            status=Conversation.Status.OPEN,
            mentor=mentor.user,
            mentee=request.user,
        )
        conversation.participants.add(request.user, mentor.user)
        return Response({"id": conversation.id, "type": conversation.type, "status": conversation.status}, status=status.HTTP_201_CREATED)

    if conversation_type == Conversation.Type.SESSION:
        session_id = data.get("session_id")
        if not session_id:
            return Response({"detail": "session_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        session = get_object_or_404(MentorshipSession.objects.select_related("mentor__user", "mentee"), id=session_id)
        if session.mentee_id != request.user.id and session.mentor.user_id != request.user.id:
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        has_paid_session = Payment.objects.filter(session=session, status=Payment.Status.PAID).exists()
        if not (
            session.status in {MentorshipSession.Status.CONFIRMED, MentorshipSession.Status.IN_PROGRESS, MentorshipSession.Status.COMPLETED}
            or has_paid_session
        ):
            return Response({"detail": "Session chat is only available after payment confirmation."}, status=status.HTTP_403_FORBIDDEN)

        existing = Conversation.objects.filter(type=Conversation.Type.SESSION, session=session, status=Conversation.Status.OPEN).first()
        if existing is not None:
            return Response({"id": existing.id, "type": existing.type, "status": existing.status}, status=status.HTTP_200_OK)

        conversation = Conversation.objects.create(
            type=Conversation.Type.SESSION,
            status=Conversation.Status.OPEN,
            mentor=session.mentor.user,
            mentee=session.mentee,
            session=session,
            related_session=session,
        )
        conversation.participants.add(request.user, session.mentor.user)
        return Response({"id": conversation.id, "type": conversation.type, "status": conversation.status}, status=status.HTTP_201_CREATED)

    return Response({"detail": "Unsupported conversation type."}, status=status.HTTP_400_BAD_REQUEST)


@api_view(("GET", "DELETE"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def conversation_detail(request, conversation_id):
    conversation = _get_conversation_for_user(request.user, conversation_id)
    if request.method == "GET":
        return Response(
            {
                "id": conversation.id,
                "type": conversation.type,
                "status": conversation.status,
                "mentor_id": conversation.mentor_id,
                "mentee_id": conversation.mentee_id,
                "session_id": conversation.session_id,
                "messages": [
                    _conversation_message_payload(message)
                    for message in conversation.messages.select_related("sender").all()
                ],
            }
        )
    conversation.delete()
    return Response({"deleted": True})


@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def send_message(request, conversation_id):
    conversation = _get_conversation_for_user(request.user, conversation_id)
    if request.method == "GET":
        return Response({"messages": [_conversation_message_payload(message) for message in conversation.messages.select_related("sender").all()]})

    data = _get_request_data(request)
    body = (data.get("body") or "").strip()
    if not body:
        return Response({"detail": "Message body is required."}, status=status.HTTP_400_BAD_REQUEST)

    if conversation.status in {Conversation.Status.LOCKED, Conversation.Status.ARCHIVED}:
        return Response({"detail": "Conversation is closed."}, status=status.HTTP_403_FORBIDDEN)

    if conversation.type == Conversation.Type.INQUIRY and conversation.mentee_id == request.user.id:
        mentor_profile = getattr(conversation.mentor, "mentorprofile", None) if conversation.mentor_id else None
        limit = mentor_profile.pre_booking_message_limit if mentor_profile else 3
        if conversation.mentee_message_count >= limit:
            return Response({"detail": f"Pre-booking inquiry chats allow up to {limit} messages."}, status=status.HTTP_403_FORBIDDEN)

    message = Message.objects.create(conversation=conversation, sender=request.user, body=body)
    if conversation.type == Conversation.Type.INQUIRY and conversation.mentee_id == request.user.id:
        conversation.mentee_message_count = conversation.mentee_message_count + 1
        conversation.save(update_fields=["mentee_message_count", "updated_at"])
    else:
        conversation.save(update_fields=["updated_at"])
    return Response({"message_id": message.id, "created_at": message.created_at}, status=status.HTTP_201_CREATED)


@api_view(("POST",))
@authentication_classes([])
@permission_classes([AllowAny])
@transaction.atomic
def register(request):
    User = get_user_model()
    data = _get_request_data(request)
    email = data.get("email")
    password = data.get("password")
    role = data.get("role", UserProfile.Role.MENTEE)

    if not email or not password:
        return Response({"detail": "Email and password are required."}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
        return Response({"detail": "User with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
        )
    except IntegrityError:
        return Response({"detail": "User with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

    UserProfile.objects.create(
        user=user,
        role=role,
        avatar_initials=data.get("avatar_initials", ""),
        city=data.get("city", ""),
        linkedin_url=data.get("linkedin_url", ""),
    )

    response_data = {
        "id": user.id,
        "email": user.email,
        "role": role,
        **_tokens_for_user(user),
    }

    # Mentor registration: create onboarding draft (not a production MentorProfile yet).
    if role == UserProfile.Role.MENTOR:
        application = MentorApplication.objects.create(
            user=user,
            status=MentorApplication.Status.DRAFT,
            current_step=MentorApplication.Step.PROFESSIONAL_PROFILE,
            completion_percent=0,
            version=1,
        )
        MentorApplicationReviewEvent(
            application=application,
            actor=user,
            event_type=MentorApplicationReviewEvent.EventType.APPLICATION_CREATED,
            metadata={},
        ).save()

        response_data["onboarding"] = {
            "application_id": application.id,
            "status": application.status,
            "current_step": application.current_step,
            "completion_percent": application.completion_percent,
            "version": application.version,
        }

    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(("POST",))
@authentication_classes([])
@permission_classes([AllowAny])
def login_view(request):
    data = _get_request_data(request)
    user = authenticate(request, username=data.get("email"), password=data.get("password"))
    if user is None:
        return Response({"detail": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

    profile = getattr(user, "profile", None)
    role = profile.role if profile else UserProfile.Role.MENTEE

    response_data = {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": role,
        **_tokens_for_user(user),
    }

    # Include mentor-specific routing data so the app doesn't need a second request.
    if role == UserProfile.Role.MENTOR:
        mentor_profile = getattr(user, "mentorprofile", None)
        if mentor_profile:
            response_data["mentor_profile_id"] = mentor_profile.id
        else:
            response_data["mentor_profile_id"] = None

        application = getattr(user, "mentor_application", None)
        if application:
            response_data["onboarding"] = {
                "application_id": application.id,
                "status": application.status,
                "current_step": application.current_step,
                "completion_percent": application.completion_percent,
                "version": application.version,
            }

    return Response(response_data)


@api_view(("POST",))
@authentication_classes([])
@permission_classes([AllowAny])
def token_refresh(request):
    data = _get_request_data(request)
    serializer = TokenRefreshSerializer(data={"refresh": data.get("refresh_token") or data.get("refresh")})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    return Response({"access_token": data["access"], "refresh_token": data.get("refresh")})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({"detail": "Signed out"})


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def profile(request):
    sessions = MentorshipSession.objects.filter(mentee=request.user)
    return Response(
        {
            "name": request.user.get_full_name() or request.user.email,
            "email": request.user.email,
            "role": request.user.profile.role,
            "sessions": sessions.count(),
            "spent_usd": sessions.filter(payment__status=Payment.Status.PAID).aggregate(total=Sum("payment__amount_usd"))["total"] or 0,
            "mentors": sessions.values("mentor").distinct().count(),
        }
    )


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def mentor_dashboard(request):
    if not hasattr(request.user, "mentorprofile"):
        return Response({"detail": "User is not a mentor."}, status=status.HTTP_403_FORBIDDEN)
    mentor = request.user.mentorprofile
    now = timezone.now()

    all_sessions = MentorshipSession.objects.filter(mentor=mentor)
    completed_sessions = all_sessions.filter(status=MentorshipSession.Status.COMPLETED)
    upcoming_sessions = (
        all_sessions.filter(starts_at__gte=now)
        .exclude(status=MentorshipSession.Status.CANCELLED)
    )
    total_non_draft = all_sessions.exclude(status=MentorshipSession.Status.DRAFT)

    earnings = (
        Payment.objects.filter(session__mentor=mentor, status=Payment.Status.PAID)
        .aggregate(total=Sum("amount_usd"))["total"] or 0
    )

    # Average rating from published reviews only
    from django.db.models import Count as DCount
    rating_data = (
        mentor.reviews
        .filter(visibility_status=Review.VisibilityStatus.PUBLISHED)
        .aggregate(avg=Avg("rating"), count=DCount("id"))
    )
    avg_rating = round(rating_data["avg"] or 0, 2)
    review_count = rating_data["count"]

    # Repeat client rate — mentees with more than one completed session
    completed_mentee_ids = (
        completed_sessions.values_list("mentee_id", flat=True)
    )
    total_unique_mentees = completed_sessions.values("mentee").distinct().count()
    repeat_mentees = (
        completed_sessions.values("mentee")
        .annotate(cnt=DCount("id"))
        .filter(cnt__gt=1)
        .count()
    )
    repeat_client_percent = round(
        (repeat_mentees / total_unique_mentees * 100) if total_unique_mentees else 0, 1
    )

    return Response({
        "mentor_id": mentor.id,
        "total_sessions": total_non_draft.count(),
        "completed_sessions": completed_sessions.count(),
        "upcoming_sessions_count": upcoming_sessions.count(),
        "earnings_usd": float(earnings),
        "currency": "USD",
        "average_rating": avg_rating,
        "review_count": review_count,
        "repeat_client_percent": repeat_client_percent,
    })


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def home(request):
    featured = _verified_mentor_qs().prefetch_related("expertise", "packages")[:8]
    upcoming = (
        MentorshipSession.objects.filter(mentee=request.user, starts_at__gte=timezone.now())
        .exclude(status=MentorshipSession.Status.CANCELLED)
        .select_related("mentor__user", "package")
        .first()
    )
    return Response(
        {
            "user": {
                "name": request.user.get_full_name() or request.user.email,
                "role": request.user.profile.role,
            },
            "upcoming_session_id": upcoming.id if upcoming else None,
            "categories": [_category_payload(category) for category in Category.objects.all()],
            "featured_mentors": [_mentor_summary(mentor) for mentor in featured],
        }
    )


@api_view(("GET",))
@authentication_classes([])
@permission_classes([AllowAny])
def mentor_list(request):
    mentors = _verified_mentor_qs().prefetch_related("expertise", "packages", "reviews")
    query = request.query_params.get("q")
    category = request.query_params.get("category")

    if query:
        mentors = mentors.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(headline__icontains=query)
            | Q(company__icontains=query)
            | Q(expertise__name__icontains=query)
        ).distinct()
    if category:
        mentors = mentors.filter(categories__slug=category)

    # Pagination
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except (TypeError, ValueError):
        page, page_size = 1, 20

    total = mentors.count()
    start = (page - 1) * page_size
    page_qs = mentors[start: start + page_size]

    base_url = request.build_absolute_uri(request.path)
    def _page_url(p):
        params = request.query_params.copy()
        params["page"] = p
        params["page_size"] = page_size
        return base_url + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    return Response({
        "count": total,
        "next": _page_url(page + 1) if start + page_size < total else None,
        "previous": _page_url(page - 1) if page > 1 else None,
        "results": [_mentor_summary(mentor) for mentor in page_qs],
    })


@api_view(("GET",))
@authentication_classes([])
@permission_classes([AllowAny])
def mentor_detail(request, mentor_id):
    mentor = get_object_or_404(
        _verified_mentor_qs().prefetch_related("expertise", "packages", "reviews"),
        id=mentor_id,
    )
    data = _mentor_summary(mentor)
    data.update(
        {
            "bio": mentor.bio,
            "years_experience": mentor.years_experience,
            "profile_completion": mentor.profile_completion,
            "packages": [_package_payload(package) for package in mentor.packages.filter(is_active=True)],
            "reviews": list(
                mentor.reviews.select_related("reviewer").values(
                    "id", "rating", "body", "reviewer__first_name", "reviewer__last_name", "created_at"
                )[:5]
            ),
        }
    )
    return Response(data)


@api_view(("GET",))
@authentication_classes([])
@permission_classes([AllowAny])
def mentor_availability(request, mentor_id):
    """
    Without date params: returns weekly recurring windows + booked start times (legacy behaviour).
    With ?from=&to=&duration_minutes=&timezone= : returns concrete bookable slots for the range.
    """
    import zoneinfo
    from datetime import date, datetime, timedelta as td

    mentor = get_object_or_404(_verified_mentor_qs(), id=mentor_id)
    booked = mentor.sessions.filter(starts_at__gte=timezone.now()).exclude(
        status__in=[MentorshipSession.Status.DRAFT, MentorshipSession.Status.CANCELLED]
    )

    from_str = request.query_params.get("from")
    to_str = request.query_params.get("to")

    # Without date params return the legacy response.
    if not from_str or not to_str:
        return Response(
            {
                "mentor_id": mentor.id,
                "weekly_windows": [_availability_window_payload(w) for w in mentor.availability.filter(is_active=True)],
                "booked_starts": list(booked.values_list("starts_at", flat=True)),
            }
        )

    # --- Concrete slots ---
    try:
        from_date = date.fromisoformat(from_str)
        to_date = date.fromisoformat(to_str)
    except ValueError:
        return Response({"detail": "from and to must be YYYY-MM-DD dates."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        duration_minutes = int(request.query_params.get("duration_minutes", 30))
    except (TypeError, ValueError):
        return Response({"detail": "duration_minutes must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

    tz_str = request.query_params.get("timezone", "UTC")
    try:
        local_tz = zoneinfo.ZoneInfo(tz_str)
    except Exception:
        return Response({"detail": f"Invalid timezone '{tz_str}'."}, status=status.HTTP_400_BAD_REQUEST)

    # Build a set of already-booked slot starts (UTC-aware datetimes).
    booked_starts = set(booked.values_list("starts_at", flat=True))

    # Map Django's 0-based weekday (Mon=0) to ISO 1-based (Mon=1) used by AvailabilityWindow.
    windows = mentor.availability.filter(is_active=True)
    window_map = {}  # iso_weekday -> [(starts_at, ends_at, interval_minutes)]
    for w in windows:
        iso_wd = w.weekday + 1  # convert 0-based → 1-based
        window_map.setdefault(iso_wd, []).append((w.starts_at, w.ends_at, w.slot_interval_minutes))

    now_utc = timezone.now()
    slots = []
    current = from_date
    while current <= to_date:
        iso_wd = current.isoweekday()  # 1=Mon … 7=Sun
        for (win_start, win_end, interval) in window_map.get(iso_wd, []):
            # Build naive local datetimes for this window on this date.
            slot_start = datetime(current.year, current.month, current.day,
                                   win_start.hour, win_start.minute, tzinfo=local_tz)
            window_end_dt = datetime(current.year, current.month, current.day,
                                      win_end.hour, win_end.minute, tzinfo=local_tz)

            while slot_start < window_end_dt:
                slot_end = slot_start + td(minutes=duration_minutes)
                if slot_end > window_end_dt:
                    break  # slot doesn't fit in this window
                slot_start_utc = slot_start.astimezone(timezone.utc)
                if slot_start_utc > now_utc:  # don't offer past slots
                    available = slot_start_utc not in booked_starts
                    slots.append({
                        "starts_at": slot_start.isoformat(),
                        "ends_at": slot_end.isoformat(),
                        "available": available,
                    })
                slot_start += td(minutes=interval)

        current += td(days=1)

    return Response({
        "mentor_id": mentor.id,
        "timezone": tz_str,
        "duration_minutes": duration_minutes,
        "slots": slots,
    })


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def session_detail(request, session_id):
    session = get_object_or_404(
        MentorshipSession.objects.select_related("mentor__user", "mentee", "package"),
        Q(mentee=request.user) | Q(mentor__user=request.user),
        id=session_id,
    )
    return Response(
        {
            "id": session.id,
            "mentor": session.mentor.user.get_full_name() or session.mentor.user.email,
            "mentee": session.mentee.get_full_name() or session.mentee.email,
            "starts_at": session.starts_at,
            "duration_minutes": session.package.duration_minutes,
            "goals": session.goals,
            "status": session.status,
            "video_room_url": session.video_room_url,
        }
    )


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def confirm_payment(request, session_id):
    session = get_object_or_404(MentorshipSession, id=session_id, mentee=request.user)
    payment = get_object_or_404(Payment, session=session)
    payment.status = Payment.Status.PAID
    payment.provider_payment_id = request.data.get("provider_payment_id", "")
    payment.paid_at = timezone.now()
    payment.save(update_fields=["status", "provider_payment_id", "paid_at"])

    session.status = MentorshipSession.Status.CONFIRMED
    session.video_room_url = session.video_room_url or f"https://video.example.test/sessions/{session.id}"
    session.save(update_fields=["status", "video_room_url"])
    return Response({"session_id": session.id, "status": session.status, "video_room_url": session.video_room_url})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def complete_session(request, session_id):
    session = get_object_or_404(MentorshipSession, Q(mentee=request.user) | Q(mentor__user=request.user), id=session_id)
    session.status = MentorshipSession.Status.COMPLETED
    session.save(update_fields=["status"])
    return Response({"session_id": session.id, "status": session.status})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def create_review(request, session_id):
    session = get_object_or_404(MentorshipSession, id=session_id, mentee=request.user)
    review, _ = Review.objects.update_or_create(
        session=session,
        defaults={
            "reviewer": request.user,
            "mentor": session.mentor,
            "rating": request.data.get("rating", 5),
            "body": request.data.get("body", ""),
        },
    )
    return Response({"review_id": review.id, "rating": review.rating}, status=status.HTTP_201_CREATED)


# =============================================================================
# Mentor Onboarding Endpoints
# =============================================================================

def _get_mentor_application_or_404(user):
    """Fetch the authenticated mentor's application. Returns 404 if not found."""
    try:
        return MentorApplication.objects.get(user=user)
    except MentorApplication.DoesNotExist:
        return None


def _etag_value(application):
    return f'"application-{application.id}-version-{application.version}"'


def _check_if_match(request, application):
    """
    Validate the If-Match header for optimistic concurrency.
    Returns None if the version matches or header is absent.
    Returns a 409 Response if stale.
    """
    if_match = request.META.get("HTTP_IF_MATCH") or request.data.get("version")
    if not if_match:
        return None  # No version check requested — allow through.

    # Accept either full ETag string or bare version integer.
    expected = _etag_value(application)
    if str(if_match).strip('"') != expected.strip('"'):
        return Response(
            {
                "code": "stale_application_version",
                "detail": "This application was updated by another request.",
                "current_version": application.version,
            },
            status=status.HTTP_409_CONFLICT,
        )
    return None


@api_view(("GET", "PATCH"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def mentor_onboarding_draft_view(request):
    """
    GET  /api/mentor-onboarding/ — Load the full resumable draft.
    PATCH /api/mentor-onboarding/ — Save one or more draft sections.
    Both methods use the bearer token to identify the owner — no ID in the URL.
    """
    profile = getattr(request.user, "profile", None)
    if not profile or profile.role != UserProfile.Role.MENTOR:
        return Response(
            {"code": "forbidden", "detail": "Only mentor accounts have an onboarding application."},
            status=status.HTTP_403_FORBIDDEN,
        )

    application = _get_mentor_application_or_404(request.user)
    if application is None:
        return Response({"code": "not_found", "detail": "No onboarding application found."}, status=status.HTTP_404_NOT_FOUND)

    # ---- GET ----------------------------------------------------------------
    if request.method == "GET":
        resp = Response(onboarding_services.serialize_application(application))
        resp["ETag"] = _etag_value(application)
        return resp

    # ---- PATCH --------------------------------------------------------------
    if not application.can_edit():
        return Response(
            {
                "code": "application_not_editable",
                "detail": f"Applications in '{application.status}' status cannot be edited.",
            },
            status=status.HTTP_409_CONFLICT,
        )

    conflict = _check_if_match(request, application)
    if conflict is not None:
        return conflict

    data = _get_request_data(request)
    errors = {}

    # --- current_step ---
    new_step = data.get("current_step")
    if new_step is not None:
        valid_steps = {s.value for s in MentorApplication.Step}
        if new_step not in valid_steps:
            errors["current_step"] = [f"Must be one of: {sorted(valid_steps)}."]
        else:
            application.current_step = new_step

    # --- Professional profile section ---
    if "professional_profile" in data:
        pp = data["professional_profile"]

        profession = pp.get("profession")
        if profession is not None:
            valid_professions = {p.value for p in MentorApplication.Profession}
            if profession == "" or profession is None:
                application.profession = ""
            elif profession not in valid_professions:
                errors["professional_profile.profession"] = [f"Must be one of: {sorted(valid_professions)}."]
            else:
                application.profession = profession

        headline = pp.get("headline")
        if headline is not None:
            if headline == "" or headline is None:
                application.headline = ""
            elif len(str(headline)) > 120:
                errors["professional_profile.headline"] = ["Maximum 120 characters."]
            else:
                application.headline = str(headline)

        company = pp.get("company")
        if company is not None:
            if len(str(company)) > 120:
                errors["professional_profile.company"] = ["Maximum 120 characters."]
            else:
                application.company = str(company) if company else ""

        years = pp.get("years_experience")
        if years is not None:
            try:
                years = int(years)
                if not (0 <= years <= 60):
                    raise ValueError
                application.years_experience = years
            except (TypeError, ValueError):
                errors["professional_profile.years_experience"] = ["Must be an integer between 0 and 60."]

        bio = pp.get("bio")
        if bio is not None:
            application.bio = str(bio) if bio else ""

        linkedin = pp.get("linkedin_url")
        if linkedin is not None:
            if linkedin and not onboarding_services._is_valid_https_url(str(linkedin)):
                errors["professional_profile.linkedin_url"] = ["Must be a valid HTTPS URL."]
            else:
                application.linkedin_url = str(linkedin) if linkedin else ""

        portfolio = pp.get("portfolio_url")
        if portfolio is not None:
            if portfolio and not onboarding_services._is_valid_https_url(str(portfolio)):
                errors["professional_profile.portfolio_url"] = ["Must be a valid HTTPS URL."]
            else:
                application.portfolio_url = str(portfolio) if portfolio else ""

    # --- Expertise section ---
    if "category_ids" in data:
        raw_ids = _data_list(data, "category_ids")
        try:
            cat_ids = [int(i) for i in raw_ids]
        except (TypeError, ValueError):
            errors["category_ids"] = ["All values must be integers."]
            cat_ids = None

        if cat_ids is not None:
            ref_errors = onboarding_services.validate_category_expertise_refs(cat_ids, None)
            errors.update(ref_errors)
            if not ref_errors:
                application.save()
                application.categories.set(Category.objects.filter(id__in=cat_ids))

    if "expertise_ids" in data:
        raw_ids = _data_list(data, "expertise_ids")
        try:
            exp_ids = [int(i) for i in raw_ids]
        except (TypeError, ValueError):
            errors["expertise_ids"] = ["All values must be integers."]
            exp_ids = None

        if exp_ids is not None:
            ref_errors = onboarding_services.validate_category_expertise_refs(None, exp_ids)
            errors.update(ref_errors)
            if not ref_errors:
                application.save()
                application.expertise.set(Expertise.objects.filter(id__in=exp_ids))

    # --- Services section ---
    if "accepts_inquiries" in data:
        application.accepts_inquiries = _data_bool(data, "accepts_inquiries", application.accepts_inquiries)

    if "packages" in data:
        packages_data = data.get("packages") or []
        if not isinstance(packages_data, list):
            errors["packages"] = ["Must be a list."]
        else:
            application.save()
            _, pkg_errors = onboarding_services.upsert_packages(application, packages_data)
            errors.update(pkg_errors)

    # --- Availability section ---
    if "timezone" in data:
        tz_val = data.get("timezone") or ""
        if tz_val and not onboarding_services._is_valid_iana_timezone(tz_val):
            errors["timezone"] = ["Must be a valid IANA timezone identifier (e.g. 'Asia/Karachi')."]
        else:
            application.timezone = tz_val

    if "availability_windows" in data:
        windows_data = data.get("availability_windows") or []
        if not isinstance(windows_data, list):
            errors["availability_windows"] = ["Must be a list."]
        else:
            application.save()
            _, win_errors = onboarding_services.upsert_availability_windows(
                application, windows_data, application.timezone
            )
            errors.update(win_errors)

    if errors:
        return Response(
            {"code": "validation_error", "detail": "Some fields need attention.", "errors": errors},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    application.completion_percent = onboarding_services.calculate_completion_percent(application)
    application.version += 1
    application.save()

    MentorApplicationReviewEvent(
        application=application,
        actor=request.user,
        event_type=MentorApplicationReviewEvent.EventType.DRAFT_UPDATED,
        metadata={"step": application.current_step, "version": application.version},
    ).save()

    resp = Response(onboarding_services.serialize_application(application))
    resp["ETag"] = _etag_value(application)
    return resp


# Legacy alias — delegates to the combined view above
@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def mentor_onboarding_draft(request):
    """Kept for internal use only — do not call from another @api_view."""
    return mentor_onboarding_draft_view(request._request)


# =============================================================================
# Document Upload Endpoints
# =============================================================================

@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def document_upload_request(request):
    """POST /api/mentor-onboarding/documents/upload-request/"""
    profile = getattr(request.user, "profile", None)
    if not profile or profile.role != UserProfile.Role.MENTOR:
        return Response({"code": "forbidden", "detail": "Mentor accounts only."}, status=status.HTTP_403_FORBIDDEN)

    application = _get_mentor_application_or_404(request.user)
    if application is None:
        return Response({"code": "not_found", "detail": "No onboarding application found."}, status=status.HTTP_404_NOT_FOUND)

    if not application.can_edit():
        return Response(
            {"code": "application_not_editable", "detail": "Documents can only be uploaded in draft or changes_requested status."},
            status=status.HTTP_409_CONFLICT,
        )

    data = _get_request_data(request)
    errors = {}

    document_type = data.get("document_type", "")
    valid_types = {dt.value for dt in MentorVerificationDocument.DocumentType}
    if document_type not in valid_types:
        errors["document_type"] = [f"Must be one of: {sorted(valid_types)}."]

    file_name = (data.get("file_name") or "").strip()
    if not file_name:
        errors["file_name"] = ["This field is required."]

    content_type = (data.get("content_type") or "").strip().lower()
    if content_type not in MentorVerificationDocument.ALLOWED_CONTENT_TYPES:
        errors["content_type"] = [
            f"Allowed types: {sorted(MentorVerificationDocument.ALLOWED_CONTENT_TYPES)}."
        ]
        return Response({"code": "validation_error", "errors": errors}, status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    size_bytes = data.get("size_bytes")
    try:
        size_bytes = int(size_bytes)
        if size_bytes <= 0 or size_bytes > MentorVerificationDocument.MAX_SIZE_BYTES:
            raise ValueError
    except (TypeError, ValueError):
        errors["size_bytes"] = [f"Must be a positive integer up to {MentorVerificationDocument.MAX_SIZE_BYTES} bytes (10 MB)."]

    if errors:
        return Response({"code": "validation_error", "errors": errors}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    document = MentorVerificationDocument.objects.create(
        application=application,
        document_type=document_type,
        original_file_name=file_name,
        storage_key="pending",  # Replaced below after URL generation.
        content_type=content_type,
        size_bytes=size_bytes,
        status=MentorVerificationDocument.DocumentStatus.REQUESTED,
    )

    url_info = onboarding_services.generate_upload_url(document)
    document.storage_key = url_info["storage_key"]
    document.save(update_fields=["storage_key"])

    MentorApplicationReviewEvent(
        application=application,
        actor=request.user,
        event_type=MentorApplicationReviewEvent.EventType.DOCUMENT_UPLOADED,
        metadata={"document_id": document.id, "document_type": document_type},
    ).save()

    return Response(
        {
            "document_id": document.id,
            "upload_url": url_info["upload_url"],
            "upload_method": url_info["upload_method"],
            "upload_headers": url_info["upload_headers"],
            "expires_at": url_info["expires_at"].isoformat() + "Z",
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def document_confirm(request, document_id):
    """POST /api/mentor-onboarding/documents/<id>/confirm/"""
    document = get_object_or_404(MentorVerificationDocument, id=document_id)

    if document.application.user_id != request.user.id:
        return Response({"code": "not_found", "detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND)

    if not document.application.can_edit():
        return Response(
            {"code": "application_not_editable", "detail": "Documents can only be confirmed in draft or changes_requested status."},
            status=status.HTTP_409_CONFLICT,
        )

    data = _get_request_data(request)
    checksum = (data.get("checksum_sha256") or "").strip().lower()

    ok, error_msg = onboarding_services.verify_uploaded_document(document, checksum)
    if not ok:
        return Response(
            {"code": "validation_error", "errors": {"checksum_sha256": [error_msg]}},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    return Response(
        {
            "id": document.id,
            "document_type": document.document_type,
            "file_name": document.original_file_name,
            "status": document.status,
            "uploaded_at": document.uploaded_at.isoformat() + "Z" if document.uploaded_at else None,
        }
    )


@api_view(("DELETE",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def document_delete(request, document_id):
    """DELETE /api/mentor-onboarding/documents/<id>/"""
    document = get_object_or_404(MentorVerificationDocument, id=document_id)

    if document.application.user_id != request.user.id:
        return Response({"code": "not_found", "detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND)

    if not document.application.can_edit():
        return Response(
            {"code": "forbidden", "detail": "Documents can only be deleted in draft or changes_requested status."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Block deletion of documents that were part of a previously submitted revision.
    # A document is "submitted evidence" if it has ever reached scanning or beyond.
    submitted_statuses = {
        MentorVerificationDocument.DocumentStatus.SCANNING,
        MentorVerificationDocument.DocumentStatus.READY,
        MentorVerificationDocument.DocumentStatus.UNSAFE,
        MentorVerificationDocument.DocumentStatus.REJECTED,
    }
    if document.status in submitted_statuses:
        return Response(
            {
                "code": "forbidden",
                "detail": (
                    "This document was submitted as evidence and cannot be deleted. "
                    "Upload a replacement document instead."
                ),
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Only allow deletion of documents that were never confirmed (still in requested/uploaded).
    # In production also remove the S3 object here for requested/uploaded docs that never completed.
    document.status = MentorVerificationDocument.DocumentStatus.DELETED
    document.save(update_fields=["status", "updated_at"])

    return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Submit & Status Endpoints
# =============================================================================

@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def mentor_onboarding_submit(request):
    """POST /api/mentor-onboarding/submit/"""
    profile = getattr(request.user, "profile", None)
    if not profile or profile.role != UserProfile.Role.MENTOR:
        return Response({"code": "forbidden", "detail": "Only mentor accounts can submit an application."}, status=status.HTTP_403_FORBIDDEN)

    application = _get_mentor_application_or_404(request.user)
    if application is None:
        return Response({"code": "not_found", "detail": "No onboarding application found."}, status=status.HTTP_404_NOT_FOUND)

    # Idempotency: already submitted and not yet reviewed.
    if application.status == MentorApplication.Status.PENDING_REVIEW:
        return Response(
            {
                "application_id": application.id,
                "status": application.status,
                "submitted_at": application.submitted_at.isoformat() + "Z" if application.submitted_at else None,
                "estimated_review_days": 3,
            }
        )

    data = _get_request_data(request)
    confirm_accurate = _data_bool(data, "confirm_information_accurate", False)
    terms_version = (data.get("terms_version") or "").strip()

    updated_application, errors = onboarding_services.submit_application(
        application=application,
        confirm_accurate=confirm_accurate,
        terms_version=terms_version,
        actor=request.user,
    )

    if errors:
        return Response(
            {
                "code": "validation_error",
                "detail": "Complete the required mentor information.",
                "errors": errors,
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    return Response(
        {
            "application_id": updated_application.id,
            "status": updated_application.status,
            "submitted_at": updated_application.submitted_at.isoformat() + "Z",
            "estimated_review_days": 3,
        }
    )


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def mentor_onboarding_status(request):
    """GET /api/mentor-onboarding/status/"""
    profile = getattr(request.user, "profile", None)
    if not profile or profile.role != UserProfile.Role.MENTOR:
        return Response({"code": "forbidden", "detail": "Only mentor accounts have an onboarding status."}, status=status.HTTP_403_FORBIDDEN)

    application = _get_mentor_application_or_404(request.user)
    if application is None:
        return Response({"code": "not_found", "detail": "No onboarding application found."}, status=status.HTTP_404_NOT_FOUND)

    return Response(
        {
            "application_id": application.id,
            "status": application.status,
            "current_step": application.current_step,
            "completion_percent": application.completion_percent,
            "submitted_at": application.submitted_at.isoformat() + "Z" if application.submitted_at else None,
            "reviewed_at": application.reviewed_at.isoformat() + "Z" if application.reviewed_at else None,
            "review_notes": application.review_notes or None,
            "fields_requiring_changes": application.fields_requiring_changes or [],
            "can_edit": application.can_edit(),
            "can_submit": application.can_submit(),
        }
    )


# =============================================================================
# Admin / Reviewer Endpoints
# =============================================================================

def _application_queue_item(app):
    user = app.user
    return {
        "id": app.id,
        "mentor": {
            "id": user.id,
            "name": user.get_full_name() or user.email,
            "email": user.email,
        },
        "profession": app.profession,
        "headline": app.headline,
        "status": app.status,
        "submitted_at": app.submitted_at.isoformat() + "Z" if app.submitted_at else None,
        "document_count": app.documents.exclude(
            status=MentorVerificationDocument.DocumentStatus.DELETED
        ).count(),
    }


def _application_detail_payload(app):
    payload = onboarding_services.serialize_application(app)
    payload["mentor"] = {
        "id": app.user.id,
        "name": app.user.get_full_name() or app.user.email,
        "email": app.user.email,
    }
    payload["review_events"] = [
        {
            "event_type": ev.event_type,
            "actor_id": ev.actor_id,
            "metadata": ev.metadata,
            "created_at": ev.created_at.isoformat() + "Z",
        }
        for ev in app.review_events.all()
    ]
    return payload


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_application_list(request):
    """GET /api/admin/mentor-applications/"""
    if not request.user.is_staff:
        return Response({"code": "forbidden", "detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    from django.db.models import Q as DQ

    qs = MentorApplication.objects.select_related("user").prefetch_related("documents")

    # Filters
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)

    profession_filter = request.query_params.get("profession")
    if profession_filter:
        qs = qs.filter(profession=profession_filter)

    q = request.query_params.get("q")
    if q:
        qs = qs.filter(
            DQ(user__first_name__icontains=q)
            | DQ(user__last_name__icontains=q)
            | DQ(user__email__icontains=q)
            | DQ(headline__icontains=q)
        )

    submitted_after = request.query_params.get("submitted_after")
    if submitted_after:
        qs = qs.filter(submitted_at__gte=submitted_after)

    submitted_before = request.query_params.get("submitted_before")
    if submitted_before:
        qs = qs.filter(submitted_at__lte=submitted_before)

    ordering = request.query_params.get("ordering", "-submitted_at")
    allowed_orderings = {"submitted_at", "-submitted_at", "status", "-status", "created_at", "-created_at"}
    if ordering not in allowed_orderings:
        ordering = "-submitted_at"
    qs = qs.order_by(ordering)

    # Simple pagination
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 25))))
    except (TypeError, ValueError):
        page, page_size = 1, 25

    total = qs.count()
    start = (page - 1) * page_size
    results = qs[start: start + page_size]

    return Response(
        {
            "count": total,
            "page": page,
            "page_size": page_size,
            "results": [_application_queue_item(app) for app in results],
        }
    )


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_application_detail(request, application_id):
    """GET /api/admin/mentor-applications/<id>/"""
    if not request.user.is_staff:
        return Response({"code": "forbidden", "detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    app = get_object_or_404(
        MentorApplication.objects.select_related("user", "reviewer").prefetch_related(
            "categories", "expertise", "documents", "packages", "availability_windows", "review_events"
        ),
        id=application_id,
    )
    return Response(_application_detail_payload(app))


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_application_approve(request, application_id):
    """POST /api/admin/mentor-applications/<id>/approve/"""
    if not request.user.is_staff:
        return Response({"code": "forbidden", "detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    app = get_object_or_404(MentorApplication, id=application_id)
    data = _get_request_data(request)

    try:
        updated = onboarding_services.approve_application(
            application=app,
            reviewer=request.user,
            notes=data.get("notes", ""),
        )
    except ValueError as exc:
        current_status = exc.args[1] if len(exc.args) > 1 else app.status
        return Response(
            {
                "code": "application_already_reviewed",
                "detail": "Another reviewer has already completed this application.",
                "current_status": current_status,
            },
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        {
            "application_id": updated.id,
            "status": updated.status,
            "reviewed_at": updated.reviewed_at.isoformat() + "Z",
        }
    )


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_application_request_changes(request, application_id):
    """POST /api/admin/mentor-applications/<id>/request-changes/"""
    if not request.user.is_staff:
        return Response({"code": "forbidden", "detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    app = get_object_or_404(MentorApplication, id=application_id)
    data = _get_request_data(request)

    notes = (data.get("notes") or "").strip()
    if not notes:
        return Response(
            {"code": "validation_error", "errors": {"notes": ["Notes are required when requesting changes."]}},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    fields = data.get("fields_requiring_changes") or []
    if not isinstance(fields, list):
        fields = [str(fields)]

    try:
        updated = onboarding_services.request_changes(
            application=app,
            reviewer=request.user,
            notes=notes,
            fields_requiring_changes=fields,
        )
    except ValueError as exc:
        current_status = exc.args[1] if len(exc.args) > 1 else app.status
        return Response(
            {
                "code": "application_already_reviewed",
                "detail": "Another reviewer has already completed this application.",
                "current_status": current_status,
            },
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        {
            "application_id": updated.id,
            "status": updated.status,
            "review_notes": updated.review_notes,
            "fields_requiring_changes": updated.fields_requiring_changes,
        }
    )


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_application_reject(request, application_id):
    """POST /api/admin/mentor-applications/<id>/reject/"""
    if not request.user.is_staff:
        return Response({"code": "forbidden", "detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    app = get_object_or_404(MentorApplication, id=application_id)
    data = _get_request_data(request)

    notes = (data.get("notes") or "").strip()
    reason_code = (data.get("reason_code") or "").strip()
    if not notes or not reason_code:
        return Response(
            {
                "code": "validation_error",
                "errors": {
                    "reason_code": ["Required."] if not reason_code else [],
                    "notes": ["Required."] if not notes else [],
                },
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    try:
        updated = onboarding_services.reject_application(
            application=app,
            reviewer=request.user,
            reason_code=reason_code,
            notes=notes,
        )
    except ValueError as exc:
        current_status = exc.args[1] if len(exc.args) > 1 else app.status
        return Response(
            {
                "code": "application_already_reviewed",
                "detail": "Another reviewer has already completed this application.",
                "current_status": current_status,
            },
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        {"application_id": updated.id, "status": updated.status}
    )


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_application_reopen(request, application_id):
    """POST /api/admin/mentor-applications/<id>/reopen/"""
    if not request.user.is_staff:
        return Response({"code": "forbidden", "detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    app = get_object_or_404(MentorApplication, id=application_id)

    try:
        updated = onboarding_services.reopen_application(application=app, staff_user=request.user)
    except ValueError as exc:
        return Response(
            {"code": "invalid_transition", "detail": str(exc.args[0])},
            status=status.HTTP_409_CONFLICT,
        )

    return Response({"application_id": updated.id, "status": updated.status})


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_document_download(request, application_id, document_id):
    """GET /api/admin/mentor-applications/<id>/documents/<doc_id>/download/"""
    if not request.user.is_staff:
        return Response({"code": "forbidden", "detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    app = get_object_or_404(MentorApplication, id=application_id)
    document = get_object_or_404(MentorVerificationDocument, id=document_id, application=app)

    url_info = onboarding_services.generate_download_url(document)

    MentorApplicationReviewEvent(
        application=app,
        actor=request.user,
        event_type=MentorApplicationReviewEvent.EventType.DOCUMENT_DOWNLOADED,
        metadata={"document_id": document.id, "document_type": document.document_type},
    ).save()

    return Response(
        {
            "document_id": document.id,
            "document_type": document.document_type,
            "file_name": document.original_file_name,
            "download_url": url_info["download_url"],
            "expires_at": url_info["expires_at"].isoformat() + "Z",
        }
    )


# =============================================================================
# Updated discovery/booking views — enforce verification
# =============================================================================

def _verified_mentor_qs():
    """Base queryset for publicly visible mentors."""
    return MentorProfile.objects.filter(
        is_active=True,
        is_verified=True,
        user__is_active=True,
        user__mentor_application__status=MentorApplication.Status.VERIFIED,
    )


# =============================================================================
# Health endpoint
# =============================================================================

@api_view(("GET",))
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    """GET /api/health/ — unauthenticated liveness probe."""
    return Response({"status": "ok"})


# =============================================================================
# Session list + self-service cancel
# =============================================================================

def _session_detail_payload(session):
    """Full session payload for both mentor and mentee views."""
    payload = {
        "id": session.id,
        "mentor_id": session.mentor_id,
        "mentor_name": session.mentor.user.get_full_name() or session.mentor.user.email,
        "mentee_id": session.mentee_id,
        "mentee_name": session.mentee.get_full_name() or session.mentee.email,
        "starts_at": session.starts_at.isoformat() + "Z" if session.starts_at else None,
        "duration_minutes": session.package.duration_minutes,
        "price_usd": float(session.package.price_usd),
        "topic": session.topic,
        "goals": session.goals,
        "status": session.status,
        "video_room_url": session.video_room_url,
        "created_at": session.created_at.isoformat() + "Z",
        "updated_at": session.updated_at.isoformat() + "Z",
    }
    payment = getattr(session, "payment", None)
    if payment:
        payload["payment"] = {
            "status": payment.status,
            "amount_usd": float(payment.amount_usd),
            "paid_at": payment.paid_at.isoformat() + "Z" if payment.paid_at else None,
        }
    else:
        payload["payment"] = None
    return payload


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def session_list(request):
    """GET /api/sessions/ — paginated list of the authenticated user's sessions."""
    qs = MentorshipSession.objects.filter(
        Q(mentee=request.user) | Q(mentor__user=request.user)
    ).select_related("mentor__user", "mentee", "package").order_by("-starts_at")

    # Filters
    sess_status = request.query_params.get("status")
    if sess_status:
        qs = qs.filter(status=sess_status)

    from_dt = request.query_params.get("from")
    to_dt = request.query_params.get("to")
    if from_dt:
        qs = qs.filter(starts_at__gte=from_dt)
    if to_dt:
        qs = qs.filter(starts_at__lte=to_dt)

    # Pagination
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except (TypeError, ValueError):
        page, page_size = 1, 20

    total = qs.count()
    start = (page - 1) * page_size

    return Response({
        "count": total,
        "page": page,
        "page_size": page_size,
        "has_next": start + page_size < total,
        "has_previous": page > 1,
        "results": [_session_detail_payload(s) for s in qs[start: start + page_size]],
    })


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def cancel_session(request, session_id):
    """POST /api/sessions/<id>/cancel/ — mentee or mentor self-service cancel."""
    session = get_object_or_404(
        MentorshipSession.objects.select_related("mentor__user", "mentee"),
        Q(mentee=request.user) | Q(mentor__user=request.user),
        id=session_id,
    )

    cancellable = {
        MentorshipSession.Status.PENDING_PAYMENT,
        MentorshipSession.Status.CONFIRMED,
        MentorshipSession.Status.DRAFT,
    }
    if session.status not in cancellable:
        return Response(
            {
                "code": "invalid_transition",
                "detail": f"A session in '{session.status}' status cannot be cancelled.",
            },
            status=status.HTTP_409_CONFLICT,
        )

    session.status = MentorshipSession.Status.CANCELLED
    session.save(update_fields=["status", "updated_at"])

    return Response({
        "session_id": session.id,
        "status": session.status,
    })


# =============================================================================
# Bookings — GET (list) + POST (create) on same URL
# =============================================================================

@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def bookings(request):
    """
    GET  /api/bookings/ — paginated list of the caller's sessions.
    POST /api/bookings/ — create a new booking.
    """
    if request.method == "GET":
        qs = MentorshipSession.objects.filter(
            Q(mentee=request.user) | Q(mentor__user=request.user)
        ).select_related("mentor__user", "mentee", "package").order_by("-starts_at")

        sess_status = request.query_params.get("status")
        if sess_status:
            qs = qs.filter(status=sess_status)
        from_dt = request.query_params.get("from")
        to_dt = request.query_params.get("to")
        if from_dt:
            qs = qs.filter(starts_at__gte=from_dt)
        if to_dt:
            qs = qs.filter(starts_at__lte=to_dt)

        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except (TypeError, ValueError):
            page, page_size = 1, 20

        total = qs.count()
        start = (page - 1) * page_size
        return Response({
            "count": total,
            "page": page,
            "page_size": page_size,
            "has_next": start + page_size < total,
            "has_previous": page > 1,
            "results": [_session_detail_payload(s) for s in qs[start: start + page_size]],
        })

    # POST — create booking
    package = get_object_or_404(SessionPackage, id=request.data.get("package_id"), is_active=True)
    mentor = package.mentor
    is_eligible = (
        mentor.is_active
        and mentor.is_verified
        and mentor.user.is_active
        and MentorApplication.objects.filter(
            user=mentor.user,
            status=MentorApplication.Status.VERIFIED,
        ).exists()
    )
    if not is_eligible:
        return Response(
            {"code": "mentor_not_available", "detail": "This mentor is not currently available for bookings."},
            status=status.HTTP_403_FORBIDDEN,
        )

    session = MentorshipSession.objects.create(
        mentee=request.user,
        mentor=mentor,
        package=package,
        starts_at=request.data.get("starts_at"),
        goals=request.data.get("goals", ""),
        topic=request.data.get("topic", ""),
        status=MentorshipSession.Status.PENDING_PAYMENT,
    )
    Payment.objects.create(session=session, amount_usd=package.price_usd)
    return Response({"session_id": session.id, "payment_status": session.payment.status}, status=status.HTTP_201_CREATED)
