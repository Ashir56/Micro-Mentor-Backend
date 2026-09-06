"""
Admin panel API views — Phase 1.

All endpoints require the caller to be authenticated AND is_staff=True.
The _require_staff() helper returns a 403 Response early if the check fails;
call it at the top of every admin view.

Endpoints implemented:
  GET  /api/admin/dashboard/
  GET  /api/admin/users/
  GET  /api/admin/users/<id>/
  PATCH /api/admin/users/<id>/status/
  POST /api/admin/users/<id>/revoke-sessions/
  GET  /api/admin/users/<id>/sessions/
  GET  /api/admin/users/<id>/reviews/
  GET  /api/admin/mentor-profiles/
  GET  /api/admin/mentor-profiles/<id>/
  PATCH /api/admin/mentor-profiles/<id>/
  PATCH /api/admin/mentor-profiles/<id>/visibility/
  PATCH /api/admin/mentor-profiles/<id>/booking-access/
  GET  /api/admin/sessions/
  GET  /api/admin/sessions/<id>/
  POST /api/admin/sessions/<id>/cancel/
  GET  /api/admin/reviews/
  GET  /api/admin/reviews/<id>/
  POST /api/admin/reviews/<id>/hide/
  POST /api/admin/reviews/<id>/unhide/
  POST /api/admin/reviews/<id>/remove/
  POST /api/admin/reviews/<id>/restore/
  GET  /api/admin/categories/
  POST /api/admin/categories/
  PATCH /api/admin/categories/<id>/
  POST /api/admin/categories/<id>/archive/
  POST /api/admin/categories/<id>/restore/
  GET  /api/admin/expertise/
  POST /api/admin/expertise/
  PATCH /api/admin/expertise/<id>/
  POST /api/admin/expertise/<id>/archive/
  POST /api/admin/expertise/<id>/restore/
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone as tz

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import (
    AvailabilityWindow,
    Category,
    Expertise,
    MentorApplication,
    MentorProfile,
    MentorshipSession,
    MentorVerificationDocument,
    Payment,
    Review,
    SessionPackage,
    UserProfile,
)
from .api_helpers import (
    data_response, created_response, no_content_response,
    error_response, validation_error, forbidden_error,
    not_found_error, conflict_error, get_request_id,
)


# ---------------------------------------------------------------------------
# Shared guard
# ---------------------------------------------------------------------------

def _require_staff(request):
    """Return a 403 Response if the caller is not staff, else None."""
    if not (request.user and request.user.is_authenticated and request.user.is_staff):
        return forbidden_error("Staff access required.", request=request)
    return None


def _paginate(queryset, request, default_page_size=25):
    """Return (page_qs, meta_dict) for simple page/page_size pagination."""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", default_page_size))))
    except (TypeError, ValueError):
        page, page_size = 1, default_page_size
    total = queryset.count()
    start = (page - 1) * page_size
    return queryset[start: start + page_size], {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "has_next": start + page_size < total,
        "has_previous": page > 1,
    }


def _user_summary(user):
    profile = getattr(user, "profile", None)
    return {
        "id": user.id,
        "name": user.get_full_name() or user.email,
        "email": user.email,
        "role": profile.role if profile else None,
        "account_status": profile.account_status if profile else "active",
        "is_active": user.is_active,
        "date_joined": user.date_joined.isoformat() + "Z",
        "last_login": user.last_login.isoformat() + "Z" if user.last_login else None,
    }


def _review_payload(review, include_body=True):
    payload = {
        "id": review.id,
        "session_id": review.session_id,
        "mentor_id": review.mentor_id,
        "reviewer_id": review.reviewer_id,
        "reviewer_name": review.reviewer.get_full_name() or review.reviewer.email,
        "rating": review.rating,
        "visibility_status": review.visibility_status,
        "moderation_reason": review.moderation_reason or None,
        "moderated_at": review.moderated_at.isoformat() + "Z" if review.moderated_at else None,
        "created_at": review.created_at.isoformat() + "Z",
    }
    if include_body:
        payload["body"] = review.body
    return payload


def _session_payload(session):
    return {
        "id": session.id,
        "mentor_id": session.mentor_id,
        "mentor_name": session.mentor.user.get_full_name() or session.mentor.user.email,
        "mentee_id": session.mentee_id,
        "mentee_name": session.mentee.get_full_name() or session.mentee.email,
        "starts_at": session.starts_at.isoformat() + "Z" if session.starts_at else None,
        "duration_minutes": session.package.duration_minutes,
        "status": session.status,
        "topic": session.topic,
        "goals": session.goals,
        "video_room_url": session.video_room_url,
        "created_at": session.created_at.isoformat() + "Z",
        "updated_at": session.updated_at.isoformat() + "Z",
    }


def _mentor_profile_payload(mentor, include_detail=False):
    user = mentor.user
    profile = getattr(user, "profile", None)
    app = getattr(user, "mentor_application", None)

    is_discoverable = (
        mentor.is_active
        and mentor.is_verified
        and mentor.is_discovery_enabled
        and user.is_active
        and (profile.account_status == UserProfile.AccountStatus.ACTIVE if profile else True)
        and (app.status == MentorApplication.Status.VERIFIED if app else False)
    )
    is_bookable = is_discoverable and mentor.is_booking_enabled and mentor.packages.filter(is_active=True).exists()

    payload = {
        "id": mentor.id,
        "user_id": user.id,
        "name": user.get_full_name() or user.email,
        "email": user.email,
        "headline": mentor.headline,
        "company": mentor.company,
        "is_active": mentor.is_active,
        "is_verified": mentor.is_verified,
        "is_discovery_enabled": mentor.is_discovery_enabled,
        "is_booking_enabled": mentor.is_booking_enabled,
        "is_discoverable": is_discoverable,
        "is_bookable": is_bookable,
        "application_id": app.id if app else None,
        "application_status": app.status if app else None,
        "created_at": mentor.created_at.isoformat() + "Z",
        "updated_at": mentor.updated_at.isoformat() + "Z",
    }
    if include_detail:
        payload.update({
            "bio": mentor.bio,
            "years_experience": mentor.years_experience,
            "categories": list(mentor.categories.values("id", "name", "slug")),
            "expertise": list(mentor.expertise.values("id", "name", "slug")),
            "packages": [
                {
                    "id": pkg.id,
                    "duration_minutes": pkg.duration_minutes,
                    "price_usd": str(pkg.price_usd),
                    "is_popular": pkg.is_popular,
                    "is_active": pkg.is_active,
                }
                for pkg in mentor.packages.all()
            ],
            "rating": round(mentor.reviews.filter(
                visibility_status=Review.VisibilityStatus.PUBLISHED
            ).aggregate(avg=Avg("rating"))["avg"] or 0, 1),
            "session_count": mentor.sessions.exclude(
                status=MentorshipSession.Status.DRAFT
            ).count(),
        })
    return payload


# =============================================================================
# Dashboard
# =============================================================================

@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_dashboard(request):
    """GET /api/admin/dashboard/"""
    guard = _require_staff(request)
    if guard:
        return guard

    User = get_user_model()
    now = tz.now()

    # Parse optional date filters
    date_from_str = request.query_params.get("date_from")
    date_to_str = request.query_params.get("date_to")
    try:
        from django.utils.dateparse import parse_datetime
        date_from = parse_datetime(date_from_str) if date_from_str else None
        date_to = parse_datetime(date_to_str) if date_to_str else None
    except Exception:
        date_from = date_to = None

    # User counts
    total_users = User.objects.count()
    mentor_profile_ids = UserProfile.objects.filter(role=UserProfile.Role.MENTOR).values_list("user_id", flat=True)
    mentee_profile_ids = UserProfile.objects.filter(role=UserProfile.Role.MENTEE).values_list("user_id", flat=True)
    total_mentors = mentor_profile_ids.count()
    total_mentees = mentee_profile_ids.count()

    # Application funnel
    app_qs = MentorApplication.objects
    pending_verifications = app_qs.filter(status=MentorApplication.Status.PENDING_REVIEW).count()
    verified_mentors = app_qs.filter(status=MentorApplication.Status.VERIFIED).count()
    rejected_applications = app_qs.filter(status=MentorApplication.Status.REJECTED).count()
    changes_requested = app_qs.filter(status=MentorApplication.Status.CHANGES_REQUESTED).count()

    suspended_mentors = UserProfile.objects.filter(
        role=UserProfile.Role.MENTOR,
        account_status=UserProfile.AccountStatus.SUSPENDED,
    ).count()

    # Sessions
    session_qs = MentorshipSession.objects
    upcoming_sessions = session_qs.filter(
        starts_at__gt=now,
        status__in=[MentorshipSession.Status.CONFIRMED, MentorshipSession.Status.PENDING_PAYMENT],
    ).count()
    completed_sessions = session_qs.filter(status=MentorshipSession.Status.COMPLETED).count()
    cancelled_sessions = session_qs.filter(status=MentorshipSession.Status.CANCELLED).count()

    # Period-filtered sessions
    period_sessions_q = Q()
    if date_from:
        period_sessions_q &= Q(starts_at__gte=date_from)
    if date_to:
        period_sessions_q &= Q(starts_at__lt=date_to)
    period_completed = session_qs.filter(
        period_sessions_q, status=MentorshipSession.Status.COMPLETED
    ).count()

    # Payments
    paid_payments = Payment.objects.filter(status=Payment.Status.PAID)
    if date_from:
        paid_payments = paid_payments.filter(paid_at__gte=date_from)
    if date_to:
        paid_payments = paid_payments.filter(paid_at__lt=date_to)

    gross_volume = paid_payments.aggregate(total=Sum("amount_usd"))["total"] or 0
    platform_revenue = paid_payments.aggregate(total=Sum("platform_fee_usd"))["total"] or 0

    payment_failures = Payment.objects.filter(status=Payment.Status.FAILED).count()

    # Reviews
    published_reviews = Review.objects.filter(visibility_status=Review.VisibilityStatus.PUBLISHED)
    avg_rating_data = published_reviews.aggregate(avg=Avg("rating"), count=Count("id"))
    avg_rating = round(avg_rating_data["avg"] or 0, 2)
    rating_count = avg_rating_data["count"]

    hidden_removed_reviews = Review.objects.filter(
        visibility_status__in=[
            Review.VisibilityStatus.HIDDEN,
            Review.VisibilityStatus.REMOVED,
        ]
    ).count()

    # Recent applications (pending only, last 5)
    recent_applications = MentorApplication.objects.filter(
        status=MentorApplication.Status.PENDING_REVIEW
    ).select_related("user").order_by("submitted_at")[:5]

    # Recent sessions (last 5 upcoming)
    recent_bookings = MentorshipSession.objects.filter(
        starts_at__gt=now,
        status__in=[MentorshipSession.Status.CONFIRMED, MentorshipSession.Status.PENDING_PAYMENT],
    ).select_related("mentor__user", "mentee").order_by("starts_at")[:5]

    return Response({
        "generated_at": now.isoformat() + "Z",
        "period": {
            "date_from": date_from_str,
            "date_to": date_to_str,
        },
        "users": {
            "total": total_users,
            "total_mentors": total_mentors,
            "total_mentees": total_mentees,
            "suspended_mentors": suspended_mentors,
        },
        "applications": {
            "pending_review": pending_verifications,
            "changes_requested": changes_requested,
            "verified": verified_mentors,
            "rejected": rejected_applications,
        },
        "sessions": {
            "upcoming": upcoming_sessions,
            "completed_total": completed_sessions,
            "cancelled_total": cancelled_sessions,
            "completed_in_period": period_completed,
        },
        "payments": {
            "gross_volume_usd": float(gross_volume),
            "platform_revenue_usd": float(platform_revenue),
            "payment_failures": payment_failures,
        },
        "reviews": {
            "average_rating": avg_rating,
            "rating_count": rating_count,
            "moderated_count": hidden_removed_reviews,
        },
        "recent_applications": [
            {
                "id": app.id,
                "mentor_name": app.user.get_full_name() or app.user.email,
                "mentor_email": app.user.email,
                "profession": app.profession,
                "submitted_at": app.submitted_at.isoformat() + "Z" if app.submitted_at else None,
            }
            for app in recent_applications
        ],
        "recent_bookings": [
            {
                "id": s.id,
                "mentor_name": s.mentor.user.get_full_name() or s.mentor.user.email,
                "mentee_name": s.mentee.get_full_name() or s.mentee.email,
                "starts_at": s.starts_at.isoformat() + "Z",
                "status": s.status,
            }
            for s in recent_bookings
        ],
    })


# =============================================================================
# User Management
# =============================================================================

@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_user_list(request):
    """GET /api/admin/users/"""
    guard = _require_staff(request)
    if guard:
        return guard

    User = get_user_model()
    qs = User.objects.select_related("profile").order_by("-date_joined")

    # Filters
    role = request.query_params.get("role")
    if role in (UserProfile.Role.MENTOR, UserProfile.Role.MENTEE):
        qs = qs.filter(profile__role=role)

    account_status = request.query_params.get("account_status")
    if account_status:
        qs = qs.filter(profile__account_status=account_status)

    q = request.query_params.get("q")
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
        )

    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if date_from:
        qs = qs.filter(date_joined__gte=date_from)
    if date_to:
        qs = qs.filter(date_joined__lt=date_to)

    page_qs, pagination = _paginate(qs, request)
    return Response({
        "data": [_user_summary(u) for u in page_qs],
        "pagination": pagination,
    })


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_user_detail(request, user_id):
    """GET /api/admin/users/<id>/"""
    guard = _require_staff(request)
    if guard:
        return guard

    User = get_user_model()
    user = get_object_or_404(User.objects.select_related("profile"), id=user_id)
    profile = getattr(user, "profile", None)
    app = getattr(user, "mentor_application", None)

    session_count = MentorshipSession.objects.filter(
        Q(mentee=user) | Q(mentor__user=user)
    ).count()

    review_count = Review.objects.filter(reviewer=user).count()

    return Response({
        "data": {
            **_user_summary(user),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "city": profile.city if profile else None,
            "status_reason": profile.status_reason if profile else None,
            "status_changed_at": (
                profile.status_changed_at.isoformat() + "Z"
                if profile and profile.status_changed_at else None
            ),
            "application_id": app.id if app else None,
            "application_status": app.status if app else None,
            "session_count": session_count,
            "review_count": review_count,
            "is_staff": user.is_staff,
        }
    })


@api_view(("PATCH",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_user_status(request, user_id):
    """PATCH /api/admin/users/<id>/status/  — enable/disable/suspend"""
    guard = _require_staff(request)
    if guard:
        return guard

    User = get_user_model()
    user = get_object_or_404(User.objects.select_related("profile"), id=user_id)
    profile = getattr(user, "profile", None)

    new_status = request.data.get("status")
    reason = (request.data.get("reason") or "").strip()

    valid_statuses = {s.value for s in UserProfile.AccountStatus}
    if new_status not in valid_statuses:
        return validation_error(
            {"status": [f"Must be one of: {sorted(valid_statuses)}."]}, request=request
        )
    if not reason:
        return validation_error(
            {"reason": ["A reason is required for status changes."]}, request=request
        )

    if profile:
        profile.account_status = new_status
        profile.status_reason = reason
        profile.status_changed_at = tz.now()
        profile.save(update_fields=["account_status", "status_reason", "status_changed_at"])

    # Disable Django user is_active flag for disabled/suspended accounts.
    if new_status in (UserProfile.AccountStatus.DISABLED, UserProfile.AccountStatus.SUSPENDED):
        user.is_active = False
        user.save(update_fields=["is_active"])
        # Blacklist all outstanding refresh tokens immediately.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
            for token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception:
            pass
    elif new_status == UserProfile.AccountStatus.ACTIVE:
        user.is_active = True
        user.save(update_fields=["is_active"])

    return Response({
        "data": {
            "user_id": user.id,
            "account_status": new_status,
            "is_active": user.is_active,
            "reason": reason,
        }
    })


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_user_revoke_sessions(request, user_id):
    """POST /api/admin/users/<id>/revoke-sessions/"""
    guard = _require_staff(request)
    if guard:
        return guard

    User = get_user_model()
    user = get_object_or_404(User, id=user_id)
    reason = (request.data.get("reason") or "").strip()
    if not reason:
        return validation_error({"reason": ["A reason is required."]}, request=request)

    # Blacklist all outstanding refresh tokens for this user so they cannot
    # obtain new access tokens. Existing access tokens still work until their
    # natural 60-minute expiry (unavoidable without a token introspection proxy).
    try:
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        tokens = OutstandingToken.objects.filter(user=user)
        blacklisted_count = 0
        for token in tokens:
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            if created:
                blacklisted_count += 1
    except Exception:
        blacklisted_count = 0

    return data_response({
        "user_id": user.id,
        "blacklisted_tokens": blacklisted_count,
        "message": (
            f"Blacklisted {blacklisted_count} refresh token(s). "
            "New access tokens cannot be issued. Existing access tokens expire within 60 minutes."
        ),
        "reason": reason,
    }, request=request)


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_user_sessions(request, user_id):
    """GET /api/admin/users/<id>/sessions/"""
    guard = _require_staff(request)
    if guard:
        return guard

    User = get_user_model()
    user = get_object_or_404(User, id=user_id)
    qs = MentorshipSession.objects.filter(
        Q(mentee=user) | Q(mentor__user=user)
    ).select_related("mentor__user", "mentee", "package").order_by("-starts_at")

    page_qs, pagination = _paginate(qs, request)
    return Response({
        "data": [_session_payload(s) for s in page_qs],
        "pagination": pagination,
    })


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_user_reviews(request, user_id):
    """GET /api/admin/users/<id>/reviews/"""
    guard = _require_staff(request)
    if guard:
        return guard

    User = get_user_model()
    user = get_object_or_404(User, id=user_id)
    qs = Review.objects.filter(
        reviewer=user
    ).select_related("reviewer", "mentor__user").order_by("-created_at")

    page_qs, pagination = _paginate(qs, request)
    return Response({
        "data": [_review_payload(r) for r in page_qs],
        "pagination": pagination,
    })


# =============================================================================
# Live Mentor Profiles
# =============================================================================

@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_mentor_profile_list(request):
    """GET /api/admin/mentor-profiles/"""
    guard = _require_staff(request)
    if guard:
        return guard

    qs = MentorProfile.objects.select_related(
        "user", "user__profile", "user__mentor_application"
    ).prefetch_related("categories", "expertise", "packages")

    # Filters
    verified = request.query_params.get("verified")
    if verified is not None:
        qs = qs.filter(is_verified=verified.lower() in ("1", "true", "yes"))

    discovery = request.query_params.get("discovery_enabled")
    if discovery is not None:
        qs = qs.filter(is_discovery_enabled=discovery.lower() in ("1", "true", "yes"))

    booking = request.query_params.get("booking_enabled")
    if booking is not None:
        qs = qs.filter(is_booking_enabled=booking.lower() in ("1", "true", "yes"))

    account_status = request.query_params.get("account_status")
    if account_status:
        qs = qs.filter(user__profile__account_status=account_status)

    q = request.query_params.get("q")
    if q:
        qs = qs.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__email__icontains=q)
            | Q(headline__icontains=q)
        )

    qs = qs.order_by("-created_at")
    page_qs, pagination = _paginate(qs, request)
    return Response({
        "data": [_mentor_profile_payload(m) for m in page_qs],
        "pagination": pagination,
    })


@api_view(("GET", "PATCH"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_mentor_profile_detail(request, mentor_id):
    """GET/PATCH /api/admin/mentor-profiles/<id>/"""
    guard = _require_staff(request)
    if guard:
        return guard

    mentor = get_object_or_404(
        MentorProfile.objects.select_related(
            "user", "user__profile", "user__mentor_application"
        ).prefetch_related("categories", "expertise", "packages"),
        id=mentor_id,
    )

    if request.method == "GET":
        return Response({"data": _mentor_profile_payload(mentor, include_detail=True)})

    # PATCH — only allow editorial fields, not verification
    data = request.data
    allowed = {"headline", "company", "bio", "years_experience", "auto_confirm_bookings",
               "allow_pre_booking_messages", "pre_booking_message_limit"}
    for field in allowed:
        if field in data:
            setattr(mentor, field, data[field])
    mentor.save()
    return Response({"data": _mentor_profile_payload(mentor, include_detail=True)})


@api_view(("PATCH",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_mentor_profile_visibility(request, mentor_id):
    """PATCH /api/admin/mentor-profiles/<id>/visibility/"""
    guard = _require_staff(request)
    if guard:
        return guard

    mentor = get_object_or_404(MentorProfile, id=mentor_id)
    enabled = request.data.get("enabled")
    reason = (request.data.get("reason") or "").strip()

    if enabled is None:
        return validation_error({"enabled": ["Required boolean."]}, request=request)
    if not reason:
        return validation_error({"reason": ["A reason is required."]}, request=request)

    mentor.is_discovery_enabled = bool(enabled)
    mentor.save(update_fields=["is_discovery_enabled", "updated_at"])
    return Response({
        "data": {
            "mentor_id": mentor.id,
            "is_discovery_enabled": mentor.is_discovery_enabled,
            "reason": reason,
        }
    })


@api_view(("PATCH",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_mentor_profile_booking_access(request, mentor_id):
    """PATCH /api/admin/mentor-profiles/<id>/booking-access/"""
    guard = _require_staff(request)
    if guard:
        return guard

    mentor = get_object_or_404(MentorProfile, id=mentor_id)
    enabled = request.data.get("enabled")
    reason = (request.data.get("reason") or "").strip()

    if enabled is None:
        return validation_error({"enabled": ["Required boolean."]}, request=request)
    if not reason:
        return validation_error({"reason": ["A reason is required."]}, request=request)

    mentor.is_booking_enabled = bool(enabled)
    mentor.save(update_fields=["is_booking_enabled", "updated_at"])
    return Response({
        "data": {
            "mentor_id": mentor.id,
            "is_booking_enabled": mentor.is_booking_enabled,
            "reason": reason,
        }
    })


# =============================================================================
# Sessions
# =============================================================================

@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_session_list(request):
    """GET /api/admin/sessions/"""
    guard = _require_staff(request)
    if guard:
        return guard

    qs = MentorshipSession.objects.select_related(
        "mentor__user", "mentee", "package"
    ).order_by("-starts_at")

    # Filters
    sess_status = request.query_params.get("status")
    if sess_status:
        qs = qs.filter(status=sess_status)

    mentor_id = request.query_params.get("mentor_id")
    if mentor_id:
        qs = qs.filter(mentor_id=mentor_id)

    mentee_id = request.query_params.get("mentee_id")
    if mentee_id:
        qs = qs.filter(mentee_id=mentee_id)

    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if date_from:
        qs = qs.filter(starts_at__gte=date_from)
    if date_to:
        qs = qs.filter(starts_at__lt=date_to)

    q = request.query_params.get("q")
    if q:
        qs = qs.filter(
            Q(mentor__user__first_name__icontains=q)
            | Q(mentor__user__last_name__icontains=q)
            | Q(mentee__first_name__icontains=q)
            | Q(mentee__last_name__icontains=q)
            | Q(topic__icontains=q)
        )

    page_qs, pagination = _paginate(qs, request)
    return Response({
        "data": [_session_payload(s) for s in page_qs],
        "pagination": pagination,
    })


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_session_detail(request, session_id):
    """GET /api/admin/sessions/<id>/"""
    guard = _require_staff(request)
    if guard:
        return guard

    session = get_object_or_404(
        MentorshipSession.objects.select_related("mentor__user", "mentee", "package"),
        id=session_id,
    )
    payload = _session_payload(session)

    # Include payment info
    payment = getattr(session, "payment", None)
    if payment:
        payload["payment"] = {
            "id": payment.id,
            "amount_usd": float(payment.amount_usd),
            "platform_fee_usd": float(payment.platform_fee_usd),
            "status": payment.status,
            "provider": payment.provider,
            "provider_payment_id": payment.provider_payment_id,
            "paid_at": payment.paid_at.isoformat() + "Z" if payment.paid_at else None,
        }
    else:
        payload["payment"] = None

    # Include review info
    review = getattr(session, "review", None)
    if review:
        payload["review"] = {
            "id": review.id,
            "rating": review.rating,
            "visibility_status": review.visibility_status,
        }
    else:
        payload["review"] = None

    return Response({"data": payload})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_session_cancel(request, session_id):
    """POST /api/admin/sessions/<id>/cancel/"""
    guard = _require_staff(request)
    if guard:
        return guard

    session = get_object_or_404(MentorshipSession, id=session_id)
    reason = (request.data.get("reason") or "").strip()

    if not reason:
        return validation_error({"reason": ["A reason is required."]}, request=request)

    cancellable = {
        MentorshipSession.Status.PENDING_PAYMENT,
        MentorshipSession.Status.CONFIRMED,
        MentorshipSession.Status.DRAFT,
    }
    if session.status not in cancellable:
        return conflict_error(
            "invalid_transition",
            f"Cannot cancel a session in '{session.status}' status.",
            details={"current_status": session.status},
            request=request,
        )

    session.status = MentorshipSession.Status.CANCELLED
    session.save(update_fields=["status", "updated_at"])

    return Response({
        "data": {
            "session_id": session.id,
            "status": session.status,
            "reason": reason,
        }
    })


# =============================================================================
# Review Moderation
# =============================================================================

@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_review_list(request):
    """GET /api/admin/reviews/"""
    guard = _require_staff(request)
    if guard:
        return guard

    qs = Review.objects.select_related(
        "reviewer", "mentor__user", "session"
    ).order_by("-created_at")

    # Filters
    vis_status = request.query_params.get("visibility_status")
    if vis_status:
        qs = qs.filter(visibility_status=vis_status)

    mentor_id = request.query_params.get("mentor_id")
    if mentor_id:
        qs = qs.filter(mentor_id=mentor_id)

    reviewer_id = request.query_params.get("reviewer_id")
    if reviewer_id:
        qs = qs.filter(reviewer_id=reviewer_id)

    rating = request.query_params.get("rating")
    if rating:
        try:
            qs = qs.filter(rating=int(rating))
        except (TypeError, ValueError):
            pass

    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if date_from:
        qs = qs.filter(created_at__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__lt=date_to)

    q = request.query_params.get("q")
    if q:
        qs = qs.filter(
            Q(body__icontains=q)
            | Q(reviewer__first_name__icontains=q)
            | Q(reviewer__last_name__icontains=q)
            | Q(reviewer__email__icontains=q)
        )

    page_qs, pagination = _paginate(qs, request)
    return Response({
        "data": [_review_payload(r) for r in page_qs],
        "pagination": pagination,
    })


@api_view(("GET",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def admin_review_detail(request, review_id):
    """GET /api/admin/reviews/<id>/"""
    guard = _require_staff(request)
    if guard:
        return guard

    review = get_object_or_404(
        Review.objects.select_related("reviewer", "mentor__user", "session", "moderated_by"),
        id=review_id,
    )
    payload = _review_payload(review)
    payload["moderated_by_id"] = review.moderated_by_id
    return Response({"data": payload})


def _moderate_review(request, review_id, new_visibility, require_reason=True):
    """Shared logic for hide/unhide/remove/restore."""
    guard = _require_staff(request)
    if guard:
        return guard

    review = get_object_or_404(Review, id=review_id)
    reason = (request.data.get("reason") or "").strip()

    if require_reason and not reason:
        return validation_error({"reason": ["A reason is required."]}, request=request)

    # Prevent invalid transitions
    current = review.visibility_status
    valid_transitions = {
        Review.VisibilityStatus.PUBLISHED: {
            Review.VisibilityStatus.HIDDEN,
            Review.VisibilityStatus.REMOVED,
        },
        Review.VisibilityStatus.HIDDEN: {
            Review.VisibilityStatus.PUBLISHED,
            Review.VisibilityStatus.REMOVED,
        },
        Review.VisibilityStatus.REMOVED: {
            Review.VisibilityStatus.PUBLISHED,
        },
    }
    if new_visibility not in valid_transitions.get(current, set()):
        return conflict_error(
            "invalid_transition",
            f"Cannot move from '{current}' to '{new_visibility}'.",
            request=request,
        )

    review.visibility_status = new_visibility
    review.moderation_reason = reason
    review.moderated_by = request.user
    review.moderated_at = tz.now()
    review.save(update_fields=[
        "visibility_status", "moderation_reason", "moderated_by",
        "moderated_at"
    ])

    return Response({
        "data": {
            "review_id": review.id,
            "visibility_status": review.visibility_status,
            "reason": reason,
        }
    })


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_review_hide(request, review_id):
    """POST /api/admin/reviews/<id>/hide/"""
    return _moderate_review(request, review_id, Review.VisibilityStatus.HIDDEN)


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_review_unhide(request, review_id):
    """POST /api/admin/reviews/<id>/unhide/"""
    return _moderate_review(request, review_id, Review.VisibilityStatus.PUBLISHED)


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_review_remove(request, review_id):
    """POST /api/admin/reviews/<id>/remove/"""
    return _moderate_review(request, review_id, Review.VisibilityStatus.REMOVED)


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_review_restore(request, review_id):
    """POST /api/admin/reviews/<id>/restore/"""
    return _moderate_review(request, review_id, Review.VisibilityStatus.PUBLISHED)


# =============================================================================
# Categories — admin-protected management
# =============================================================================

@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_category_list(request):
    """GET/POST /api/admin/categories/"""
    guard = _require_staff(request)
    if guard:
        return guard

    if request.method == "GET":
        include_archived = request.query_params.get("include_archived", "").lower() in ("1", "true", "yes")
        qs = Category.objects.all() if include_archived else Category.objects.filter(is_active=True)

        q = request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))

        ordering = request.query_params.get("ordering", "sort_order")
        allowed_orderings = {"sort_order", "-sort_order", "name", "-name", "id", "-id"}
        if ordering not in allowed_orderings:
            ordering = "sort_order"
        qs = qs.order_by(ordering)

        page_qs, pagination = _paginate(qs, request)
        return Response({
            "data": [
                {
                    "id": c.id,
                    "name": c.name,
                    "slug": c.slug,
                    "emoji": c.emoji,
                    "is_active": c.is_active,
                    "sort_order": c.sort_order,
                    "mentor_count": MentorProfile.objects.filter(
                        categories=c, is_active=True
                    ).count(),
                }
                for c in page_qs
            ],
            "pagination": pagination,
        })

    # POST — create
    from django.utils.text import slugify
    from django.db import IntegrityError

    name = (request.data.get("name") or "").strip()
    if not name:
        return validation_error({"name": ["This field is required."]}, request=request)
    slug = (request.data.get("slug") or slugify(name)).strip()
    try:
        category = Category.objects.create(
            name=name,
            slug=slug,
            emoji=request.data.get("emoji", ""),
            sort_order=request.data.get("sort_order", 0),
            is_active=True,
        )
    except IntegrityError:
        return conflict_error(
            "duplicate_slug",
            "A category with this name or slug already exists.",
            request=request,
        )
    return data_response(
        {"id": category.id, "name": category.name, "slug": category.slug},
        request=request, status_code=status.HTTP_201_CREATED,
    )


@api_view(("PATCH",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_category_detail(request, category_id):
    """PATCH /api/admin/categories/<id>/"""
    guard = _require_staff(request)
    if guard:
        return guard

    category = get_object_or_404(Category, id=category_id)
    for field in ("name", "emoji", "sort_order"):
        if field in request.data:
            setattr(category, field, request.data[field])
    category.save()
    return Response({"data": {"id": category.id, "name": category.name, "slug": category.slug, "is_active": category.is_active}})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_category_archive(request, category_id):
    """POST /api/admin/categories/<id>/archive/"""
    guard = _require_staff(request)
    if guard:
        return guard

    category = get_object_or_404(Category, id=category_id)
    category.is_active = False
    category.save(update_fields=["is_active"])
    return Response({"data": {"id": category.id, "is_active": False}})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_category_restore(request, category_id):
    """POST /api/admin/categories/<id>/restore/"""
    guard = _require_staff(request)
    if guard:
        return guard

    category = get_object_or_404(Category, id=category_id)
    category.is_active = True
    category.save(update_fields=["is_active"])
    return Response({"data": {"id": category.id, "is_active": True}})


# =============================================================================
# Expertise — admin-protected management
# =============================================================================

@api_view(("GET", "POST"))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_expertise_list(request):
    """GET/POST /api/admin/expertise/"""
    guard = _require_staff(request)
    if guard:
        return guard

    if request.method == "GET":
        include_archived = request.query_params.get("include_archived", "").lower() in ("1", "true", "yes")
        qs = Expertise.objects.all() if include_archived else Expertise.objects.filter(is_active=True)

        q = request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))

        ordering = request.query_params.get("ordering", "sort_order")
        allowed_orderings = {"sort_order", "-sort_order", "name", "-name", "id", "-id"}
        if ordering not in allowed_orderings:
            ordering = "sort_order"
        qs = qs.order_by(ordering)

        page_qs, pagination = _paginate(qs, request)
        return Response({
            "data": [
                {
                    "id": e.id,
                    "name": e.name,
                    "slug": e.slug,
                    "is_active": e.is_active,
                    "sort_order": e.sort_order,
                }
                for e in page_qs
            ],
            "pagination": pagination,
        })

    # POST — create
    from django.utils.text import slugify
    from django.db import IntegrityError

    name = (request.data.get("name") or "").strip()
    if not name:
        return validation_error({"name": ["This field is required."]}, request=request)
    slug = (request.data.get("slug") or slugify(name)).strip()
    try:
        expertise = Expertise.objects.create(
            name=name, slug=slug,
            sort_order=request.data.get("sort_order", 0),
            is_active=True,
        )
    except IntegrityError:
        return conflict_error(
            "duplicate_slug",
            "An expertise with this name or slug already exists.",
            request=request,
        )
    return data_response(
        {"id": expertise.id, "name": expertise.name, "slug": expertise.slug},
        request=request, status_code=status.HTTP_201_CREATED,
    )


@api_view(("PATCH",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_expertise_detail(request, expertise_id):
    """PATCH /api/admin/expertise/<id>/"""
    guard = _require_staff(request)
    if guard:
        return guard

    expertise = get_object_or_404(Expertise, id=expertise_id)
    for field in ("name", "sort_order"):
        if field in request.data:
            setattr(expertise, field, request.data[field])
    expertise.save()
    return Response({"data": {"id": expertise.id, "name": expertise.name, "slug": expertise.slug, "is_active": expertise.is_active}})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_expertise_archive(request, expertise_id):
    """POST /api/admin/expertise/<id>/archive/"""
    guard = _require_staff(request)
    if guard:
        return guard

    expertise = get_object_or_404(Expertise, id=expertise_id)
    expertise.is_active = False
    expertise.save(update_fields=["is_active"])
    return Response({"data": {"id": expertise.id, "is_active": False}})


@api_view(("POST",))
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_expertise_restore(request, expertise_id):
    """POST /api/admin/expertise/<id>/restore/"""
    guard = _require_staff(request)
    if guard:
        return guard

    expertise = get_object_or_404(Expertise, id=expertise_id)
    expertise.is_active = True
    expertise.save(update_fields=["is_active"])
    return Response({"data": {"id": expertise.id, "is_active": True}})
