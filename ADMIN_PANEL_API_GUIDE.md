# Admin Panel API Guide — Flutter Integration

**Date:** 6 September 2026  
**Audience:** Flutter developer building the admin web/mobile panel  
**Base URL:** All endpoints are under `/api/` (e.g. `https://your-domain.com/api/admin/dashboard/`)  
**Auth:** All admin endpoints require a staff user bearer token — same JWT flow as the mobile app

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Standard Response Format](#2-standard-response-format)
3. [Dashboard](#3-dashboard)
4. [User Management](#4-user-management)
5. [Mentor Applications (existing)](#5-mentor-applications-existing)
6. [Live Mentor Profiles](#6-live-mentor-profiles)
7. [Sessions](#7-sessions)
8. [Review Moderation](#8-review-moderation)
9. [Taxonomy — Categories & Expertise](#9-taxonomy--categories--expertise)
10. [Complete Endpoint Index](#10-complete-endpoint-index)

---

## 1. Authentication

Admin endpoints use the same JWT bearer token system as the mobile app. The staff user must have `is_staff = true` on their account. Any non-staff token returns `403`.

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

To get a token, use the existing login endpoint:

```http
POST /api/auth/login/
Content-Type: application/json

{ "email": "admin@example.com", "password": "..." }
```

Response:
```json
{ "id": 1, "email": "admin@example.com", "access_token": "...", "refresh_token": "..." }
```

Refresh using `POST /api/auth/token/refresh/` with `{ "refresh_token": "..." }`.

A non-staff token on any admin endpoint returns:
```json
{ "code": "forbidden", "detail": "Staff access required." }
```
HTTP `403`.

---

## 2. Standard Response Format

### Single resource
```json
{
  "data": { ... }
}
```

### Paginated list
```json
{
  "data": [ ... ],
  "pagination": {
    "page": 1,
    "page_size": 25,
    "total": 82,
    "total_pages": 4,
    "has_next": true,
    "has_previous": false
  }
}
```

### Error
```json
{
  "code": "validation_error",
  "errors": {
    "reason": ["A reason is required."]
  }
}
```

### Pagination query params
All list endpoints support:
- `page` (default: 1)
- `page_size` (default: 25, max: 100)

---

## 3. Dashboard

```http
GET /api/admin/dashboard/
GET /api/admin/dashboard/?date_from=2026-09-01T00:00:00Z&date_to=2026-09-30T00:00:00Z
```

Optional filters: `date_from`, `date_to` (ISO 8601 UTC).  
Period filters affect `sessions.completed_in_period` and `payments` metrics only.

**Response `200`:**
```json
{
  "generated_at": "2026-09-06T18:30:00Z",
  "period": {
    "date_from": "2026-09-01T00:00:00Z",
    "date_to": "2026-09-30T00:00:00Z"
  },
  "users": {
    "total": 248,
    "total_mentors": 42,
    "total_mentees": 206,
    "suspended_mentors": 2
  },
  "applications": {
    "pending_review": 7,
    "changes_requested": 3,
    "verified": 29,
    "rejected": 4
  },
  "sessions": {
    "upcoming": 18,
    "completed_total": 312,
    "cancelled_total": 24,
    "completed_in_period": 41
  },
  "payments": {
    "gross_volume_usd": 8420.00,
    "platform_revenue_usd": 842.00,
    "payment_failures": 3
  },
  "reviews": {
    "average_rating": 4.7,
    "rating_count": 289,
    "moderated_count": 5
  },
  "recent_applications": [
    {
      "id": 18,
      "mentor_name": "Sarah Chen",
      "mentor_email": "sarah@example.com",
      "profession": "software_engineering",
      "submitted_at": "2026-09-05T14:22:00Z"
    }
  ],
  "recent_bookings": [
    {
      "id": 91,
      "mentor_name": "Ali Hassan",
      "mentee_name": "John Doe",
      "starts_at": "2026-09-07T10:00:00Z",
      "status": "confirmed"
    }
  ]
}
```

`recent_applications` — up to 5 oldest pending review applications.  
`recent_bookings` — up to 5 upcoming confirmed sessions.

---

## 4. User Management

### List Users

```http
GET /api/admin/users/
```

**Query filters:**

| Param | Values | Description |
|-------|--------|-------------|
| `role` | `mentor`, `mentee` | Filter by user role |
| `account_status` | `active`, `disabled`, `suspended` | Filter by account status |
| `q` | string | Search by name or email |
| `date_from` | ISO datetime | Registered after |
| `date_to` | ISO datetime | Registered before |
| `page` | integer | Page number |
| `page_size` | integer | Results per page (max 100) |

**Response `200`:**
```json
{
  "data": [
    {
      "id": 42,
      "name": "Sarah Chen",
      "email": "sarah@example.com",
      "role": "mentor",
      "account_status": "active",
      "is_active": true,
      "date_joined": "2026-08-15T10:00:00Z",
      "last_login": "2026-09-06T09:12:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### User Detail

```http
GET /api/admin/users/<id>/
```

**Response `200`:**
```json
{
  "data": {
    "id": 42,
    "name": "Sarah Chen",
    "email": "sarah@example.com",
    "first_name": "Sarah",
    "last_name": "Chen",
    "role": "mentor",
    "account_status": "active",
    "is_active": true,
    "status_reason": null,
    "status_changed_at": null,
    "date_joined": "2026-08-15T10:00:00Z",
    "last_login": "2026-09-06T09:12:00Z",
    "city": "Karachi",
    "application_id": 18,
    "application_status": "verified",
    "session_count": 12,
    "review_count": 8,
    "is_staff": false
  }
}
```

---

### Change Account Status

```http
PATCH /api/admin/users/<id>/status/
Content-Type: application/json
```

```json
{
  "status": "suspended",
  "reason": "Reported for inappropriate behaviour in session."
}
```

Valid `status` values: `active`, `disabled`, `suspended`

- `disabled` and `suspended` → sets `is_active = false` (user cannot log in)
- `active` → restores `is_active = true`
- `reason` is **required** for all status changes

**Response `200`:**
```json
{
  "data": {
    "user_id": 42,
    "account_status": "suspended",
    "is_active": false,
    "reason": "Reported for inappropriate behaviour in session."
  }
}
```

**Error `422`** if `status` is invalid or `reason` is missing.

---

### Revoke Sessions

```http
POST /api/admin/users/<id>/revoke-sessions/
Content-Type: application/json
```

```json
{ "reason": "Account suspended by admin." }
```

Logs the revocation intent. Existing short-lived access tokens expire naturally (60-minute lifetime). `reason` is required.

**Response `200`:**
```json
{
  "data": {
    "user_id": 42,
    "message": "Session revocation recorded.",
    "reason": "Account suspended by admin."
  }
}
```

---

### User's Sessions

```http
GET /api/admin/users/<id>/sessions/
```

Returns a paginated list of all sessions the user was involved in (as mentor or mentee). Same shape as [Session List](#list-sessions).

---

### User's Reviews

```http
GET /api/admin/users/<id>/reviews/
```

Returns a paginated list of reviews written by this user.

---

## 5. Mentor Applications (existing)

These endpoints were built previously and are unchanged.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/mentor-applications/` | Queue list (filterable by status, profession, q, date) |
| `GET` | `/api/admin/mentor-applications/<id>/` | Full application detail + audit trail |
| `POST` | `/api/admin/mentor-applications/<id>/approve/` | Approve and activate mentor |
| `POST` | `/api/admin/mentor-applications/<id>/request-changes/` | Send back for corrections |
| `POST` | `/api/admin/mentor-applications/<id>/reject/` | Reject application |
| `POST` | `/api/admin/mentor-applications/<id>/reopen/` | Reopen rejected application |
| `GET` | `/api/admin/mentor-applications/<id>/documents/<doc_id>/download/` | Get signed download URL |

**Queue filters:** `status`, `profession`, `q`, `submitted_after`, `submitted_before`, `page`, `page_size`

**Approve body:**
```json
{ "notes": "Identity and professional experience verified." }
```

**Request changes body:**
```json
{
  "notes": "Please upload a readable employment letter.",
  "fields_requiring_changes": ["documents.employment"]
}
```

**Reject body:**
```json
{
  "reason_code": "insufficient_professional_evidence",
  "notes": "The supplied evidence does not demonstrate the stated experience."
}
```

---

## 6. Live Mentor Profiles

These are the production mentor profiles that are visible in discovery (verified mentors only).

### List Mentor Profiles

```http
GET /api/admin/mentor-profiles/
```

**Query filters:**

| Param | Values | Description |
|-------|--------|-------------|
| `verified` | `true`, `false` | Filter by verification status |
| `discovery_enabled` | `true`, `false` | Filter by discovery toggle |
| `booking_enabled` | `true`, `false` | Filter by booking toggle |
| `account_status` | `active`, `disabled`, `suspended` | Filter by user account status |
| `q` | string | Search by name, email, or headline |

**Response `200`:**
```json
{
  "data": [
    {
      "id": 7,
      "user_id": 42,
      "name": "Sarah Chen",
      "email": "sarah@example.com",
      "headline": "Senior Flutter Engineer",
      "company": "Acme",
      "is_active": true,
      "is_verified": true,
      "is_discovery_enabled": true,
      "is_booking_enabled": true,
      "is_discoverable": true,
      "is_bookable": true,
      "application_id": 18,
      "application_status": "verified",
      "created_at": "2026-09-01T10:00:00Z",
      "updated_at": "2026-09-06T09:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

`is_discoverable` and `is_bookable` are computed server-side — use these flags to show eligibility badges in the UI. Do not compute eligibility from individual flags yourself.

---

### Mentor Profile Detail

```http
GET /api/admin/mentor-profiles/<id>/
```

Returns the full profile including `bio`, `years_experience`, `categories`, `expertise`, `packages`, `rating`, and `session_count`.

---

### Edit Editorial Fields

```http
PATCH /api/admin/mentor-profiles/<id>/
Content-Type: application/json
```

```json
{
  "headline": "Updated headline",
  "bio": "Updated bio text.",
  "company": "New Company Name"
}
```

Allowed fields: `headline`, `company`, `bio`, `years_experience`, `auto_confirm_bookings`, `allow_pre_booking_messages`, `pre_booking_message_limit`

Verification status, user identity, and application data cannot be changed through this endpoint.

---

### Toggle Discovery Visibility

```http
PATCH /api/admin/mentor-profiles/<id>/visibility/
Content-Type: application/json
```

```json
{
  "enabled": false,
  "reason": "Profile under review for policy violation."
}
```

Both `enabled` (boolean) and `reason` (string) are required.

**Response `200`:**
```json
{
  "data": {
    "mentor_id": 7,
    "is_discovery_enabled": false,
    "reason": "Profile under review for policy violation."
  }
}
```

---

### Toggle Booking Access

```http
PATCH /api/admin/mentor-profiles/<id>/booking-access/
Content-Type: application/json
```

```json
{
  "enabled": false,
  "reason": "Pending payment dispute resolution."
}
```

Same shape as visibility. Controls `is_booking_enabled` independently of discovery.

---

## 7. Sessions

### List Sessions

```http
GET /api/admin/sessions/
```

**Query filters:**

| Param | Values | Description |
|-------|--------|-------------|
| `status` | `draft`, `pending_payment`, `confirmed`, `in_progress`, `completed`, `cancelled` | Session status |
| `mentor_id` | integer | Filter by mentor |
| `mentee_id` | integer | Filter by mentee |
| `date_from` | ISO datetime | Sessions starting after |
| `date_to` | ISO datetime | Sessions starting before |
| `q` | string | Search by mentor/mentee name or topic |

**Response `200`:**
```json
{
  "data": [
    {
      "id": 91,
      "mentor_id": 7,
      "mentor_name": "Sarah Chen",
      "mentee_id": 55,
      "mentee_name": "John Doe",
      "starts_at": "2026-09-07T10:00:00Z",
      "duration_minutes": 30,
      "status": "confirmed",
      "topic": "Flutter state management",
      "goals": "Understand BLoC pattern",
      "video_room_url": "https://video.example.test/sessions/91",
      "created_at": "2026-09-06T08:00:00Z",
      "updated_at": "2026-09-06T08:05:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### Session Detail

```http
GET /api/admin/sessions/<id>/
```

Returns the same fields as list plus `payment` and `review` blocks:

```json
{
  "data": {
    "id": 91,
    "mentor_id": 7,
    "mentor_name": "Sarah Chen",
    "mentee_id": 55,
    "mentee_name": "John Doe",
    "starts_at": "2026-09-07T10:00:00Z",
    "duration_minutes": 30,
    "status": "confirmed",
    "topic": "Flutter state management",
    "goals": "Understand BLoC pattern",
    "video_room_url": "https://video.example.test/sessions/91",
    "created_at": "2026-09-06T08:00:00Z",
    "updated_at": "2026-09-06T08:05:00Z",
    "payment": {
      "id": 34,
      "amount_usd": 35.00,
      "platform_fee_usd": 3.50,
      "status": "paid",
      "provider": "stripe",
      "provider_payment_id": "pi_xxxxx",
      "paid_at": "2026-09-06T08:10:00Z"
    },
    "review": {
      "id": 22,
      "rating": 5,
      "visibility_status": "published"
    }
  }
}
```

`payment` and `review` are `null` if they don't exist for this session.

---

### Cancel Session

```http
POST /api/admin/sessions/<id>/cancel/
Content-Type: application/json
```

```json
{ "reason": "Mentor requested cancellation due to emergency." }
```

`reason` is required. Only sessions in `pending_payment`, `confirmed`, or `draft` status can be cancelled. Cancelling a session does **not** automatically issue a refund — that is a separate step.

**Response `200`:**
```json
{
  "data": {
    "session_id": 91,
    "status": "cancelled",
    "reason": "Mentor requested cancellation due to emergency."
  }
}
```

**Error `409`** if the session is already `completed`, `cancelled`, or `in_progress`.

---

## 8. Review Moderation

Reviews have a `visibility_status` field:

| Status | Meaning |
|--------|---------|
| `published` | Visible publicly — default |
| `hidden` | Not shown to public but not deleted |
| `removed` | Soft-deleted — not shown anywhere |

### List Reviews

```http
GET /api/admin/reviews/
```

**Query filters:**

| Param | Values | Description |
|-------|--------|-------------|
| `visibility_status` | `published`, `hidden`, `removed` | Filter by visibility |
| `mentor_id` | integer | Reviews for a specific mentor |
| `reviewer_id` | integer | Reviews by a specific user |
| `rating` | 1–5 | Filter by rating |
| `date_from` | ISO datetime | Created after |
| `date_to` | ISO datetime | Created before |
| `q` | string | Search body or reviewer name/email |

**Response `200`:**
```json
{
  "data": [
    {
      "id": 22,
      "session_id": 91,
      "mentor_id": 7,
      "reviewer_id": 55,
      "reviewer_name": "John Doe",
      "rating": 5,
      "body": "Excellent session, learned a lot.",
      "visibility_status": "published",
      "moderation_reason": null,
      "moderated_at": null,
      "created_at": "2026-09-07T12:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

---

### Review Detail

```http
GET /api/admin/reviews/<id>/
```

Same as list item plus `moderated_by_id`.

---

### Moderation Actions

All four actions require `reason` in the body and return the same response shape.

**Hide** (published → hidden):
```http
POST /api/admin/reviews/<id>/hide/
Content-Type: application/json

{ "reason": "Contains personally identifiable information." }
```

**Unhide** (hidden → published):
```http
POST /api/admin/reviews/<id>/unhide/
Content-Type: application/json

{ "reason": "Reviewed — no policy violation found." }
```

**Remove** (published or hidden → removed):
```http
POST /api/admin/reviews/<id>/remove/
Content-Type: application/json

{ "reason": "Violates community guidelines — harassment." }
```

**Restore** (removed → published):
```http
POST /api/admin/reviews/<id>/restore/
Content-Type: application/json

{ "reason": "Restored after appeal — content acceptable." }
```

**Response `200` (all four):**
```json
{
  "data": {
    "review_id": 22,
    "visibility_status": "hidden",
    "reason": "Contains personally identifiable information."
  }
}
```

**Error `409`** for an invalid transition (e.g. trying to unhide a `removed` review).

**Valid transition map:**

| From | Can go to |
|------|-----------|
| `published` | `hidden`, `removed` |
| `hidden` | `published`, `removed` |
| `removed` | `published` only |

---

## 9. Taxonomy — Categories & Expertise

These endpoints are staff-protected. The public `GET /api/categories/` and `GET /api/expertise/` endpoints remain available for the mobile app and only return `is_active=true` items.

### Categories

**List (with archived):**
```http
GET /api/admin/categories/?include_archived=true
```

**Query filters:** `include_archived`, `q` (name/slug search), `ordering` (`sort_order`, `name`, `id` — prefix with `-` for descending), `page`, `page_size`

**Response `200`:**
```json
{
  "data": [
    {
      "id": 1,
      "name": "Mobile Development",
      "slug": "mobile-development",
      "emoji": "📱",
      "is_active": true,
      "sort_order": 10,
      "mentor_count": 14
    }
  ],
  "pagination": { ... }
}
```

`mentor_count` is the number of active verified mentors in this category.

**Create:**
```http
POST /api/admin/categories/
Content-Type: application/json

{
  "name": "Machine Learning",
  "emoji": "🤖",
  "sort_order": 20
}
```

`slug` is auto-generated from the name if omitted. Returns `409` if name or slug already exists.

**Edit:**
```http
PATCH /api/admin/categories/<id>/
Content-Type: application/json

{ "name": "ML & AI", "sort_order": 15 }
```

Allowed fields: `name`, `emoji`, `sort_order`. Slug is not directly editable.

**Archive:**
```http
POST /api/admin/categories/<id>/archive/
```

No body required. Sets `is_active = false`. The category no longer appears in public or mentor onboarding selection. Existing mentor associations are preserved.

**Restore:**
```http
POST /api/admin/categories/<id>/restore/
```

Sets `is_active = true`. Makes the category available again for selection.

---

### Expertise

Same shape as categories. No `emoji` or `mentor_count` in responses.

**List:**
```http
GET /api/admin/expertise/?include_archived=true
```

**Create:**
```http
POST /api/admin/expertise/
Content-Type: application/json

{ "name": "SwiftUI", "sort_order": 5 }
```

**Edit:**
```http
PATCH /api/admin/expertise/<id>/
Content-Type: application/json

{ "name": "SwiftUI & UIKit" }
```

**Archive / Restore:**
```http
POST /api/admin/expertise/<id>/archive/
POST /api/admin/expertise/<id>/restore/
```

---

## 10. Complete Endpoint Index

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/dashboard/` | Aggregate stats and recent activity |

### Users
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/users/` | List all users with filters |
| `GET` | `/api/admin/users/<id>/` | User detail |
| `PATCH` | `/api/admin/users/<id>/status/` | Change account status |
| `POST` | `/api/admin/users/<id>/revoke-sessions/` | Log session revocation |
| `GET` | `/api/admin/users/<id>/sessions/` | User's session history |
| `GET` | `/api/admin/users/<id>/reviews/` | Reviews written by user |

### Mentor Applications
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/mentor-applications/` | Application queue |
| `GET` | `/api/admin/mentor-applications/<id>/` | Full application detail |
| `POST` | `/api/admin/mentor-applications/<id>/approve/` | Approve |
| `POST` | `/api/admin/mentor-applications/<id>/request-changes/` | Request changes |
| `POST` | `/api/admin/mentor-applications/<id>/reject/` | Reject |
| `POST` | `/api/admin/mentor-applications/<id>/reopen/` | Reopen rejected |
| `GET` | `/api/admin/mentor-applications/<id>/documents/<doc_id>/download/` | Signed download URL |

### Live Mentor Profiles
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/mentor-profiles/` | List with filters |
| `GET` | `/api/admin/mentor-profiles/<id>/` | Full profile detail |
| `PATCH` | `/api/admin/mentor-profiles/<id>/` | Edit editorial fields |
| `PATCH` | `/api/admin/mentor-profiles/<id>/visibility/` | Toggle discovery |
| `PATCH` | `/api/admin/mentor-profiles/<id>/booking-access/` | Toggle booking |

### Sessions
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/sessions/` | List with filters |
| `GET` | `/api/admin/sessions/<id>/` | Detail with payment and review |
| `POST` | `/api/admin/sessions/<id>/cancel/` | Cancel a session |

### Reviews
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/reviews/` | List with filters |
| `GET` | `/api/admin/reviews/<id>/` | Review detail |
| `POST` | `/api/admin/reviews/<id>/hide/` | Hide from public |
| `POST` | `/api/admin/reviews/<id>/unhide/` | Restore to published |
| `POST` | `/api/admin/reviews/<id>/remove/` | Soft remove |
| `POST` | `/api/admin/reviews/<id>/restore/` | Restore removed |

### Categories
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/categories/` | List (supports archived) |
| `POST` | `/api/admin/categories/` | Create |
| `PATCH` | `/api/admin/categories/<id>/` | Edit |
| `POST` | `/api/admin/categories/<id>/archive/` | Archive |
| `POST` | `/api/admin/categories/<id>/restore/` | Restore |

### Expertise
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/expertise/` | List (supports archived) |
| `POST` | `/api/admin/expertise/` | Create |
| `PATCH` | `/api/admin/expertise/<id>/` | Edit |
| `POST` | `/api/admin/expertise/<id>/archive/` | Archive |
| `POST` | `/api/admin/expertise/<id>/restore/` | Restore |

---

## Important Notes for the Flutter Dev

**1. All admin mutations require `reason`**  
Status changes, visibility toggles, booking-access toggles, session cancellations, and review moderation all require a non-empty `reason` string. Build a confirmation dialog with a required text field before submitting any of these actions.

**2. Use `is_discoverable` and `is_bookable`, not individual flags**  
The mentor profile detail returns both raw flags (`is_discovery_enabled`, `is_verified`, etc.) and computed eligibility booleans (`is_discoverable`, `is_bookable`). Always use the computed booleans for displaying eligibility status — don't re-implement the logic in the frontend.

**3. Review moderation is not the same as deletion**  
`removed` reviews are soft-deleted and can be restored. Do not show removed reviews in any public view. The visibility state machine only allows transitions listed in the table in section 8.

**4. Session cancellation ≠ refund**  
Cancelling a session via `POST /api/admin/sessions/<id>/cancel/` only changes the session status. Payment refunds are a separate operation (Phase 2 — not yet implemented). Show a warning in the UI that the mentor/mentee will need to be refunded separately.

**5. `account_status` vs `is_active`**  
The API returns both. `is_active` is the Django auth field that controls login access. `account_status` is the admin-facing label (`active`, `disabled`, `suspended`). When you `PATCH /api/admin/users/<id>/status/` with `disabled` or `suspended`, both are set. Use `account_status` for displaying status in the admin UI.

**6. Category/Expertise archive ≠ delete**  
Archiving sets `is_active = false` but the record is never deleted. Archived categories still appear in existing mentor profile associations and historical application data. The `mentor_count` in the category list only counts active verified profiles.
