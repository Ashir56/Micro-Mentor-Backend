# Frontend Update Note — Mentor Onboarding API Fix

**Date:** 6 September 2026  
**Affects:** Mentor onboarding screens only  
**Urgency:** Required — without this the submit button will always return a validation error

---

## What Was Wrong

The backend had a routing bug. The PATCH save endpoint was registered at `/api/mentor-onboarding/update/` instead of `/api/mentor-onboarding/`. This meant every time the Flutter app sent `PATCH /api/mentor-onboarding/` to save the draft, the backend was silently returning the empty draft instead of saving anything.

The result: the draft always stayed empty, and submit returned 422 with every field missing.

**This is now fixed on the backend.** `PATCH /api/mentor-onboarding/` works correctly.

---

## What You Need to Change

### One thing only — confirm the PATCH path

Every draft save (all 5 onboarding screens) must use:

```
PATCH /api/mentor-onboarding/
```

Not `/api/mentor-onboarding/update/`. If you were already using `/api/mentor-onboarding/` for PATCH — you were right, no change needed. If you had switched to `/update/` based on the earlier guide, switch it back.

---

## Complete Correct Endpoint Paths

```
GET    /api/mentor-onboarding/                              Load draft
PATCH  /api/mentor-onboarding/                              Save draft  ← this was the fix
POST   /api/mentor-onboarding/submit/                       Submit
GET    /api/mentor-onboarding/status/                       Poll status
POST   /api/mentor-onboarding/documents/upload-request/     Request upload URL
POST   /api/mentor-onboarding/documents/<id>/confirm/       Confirm upload
DELETE /api/mentor-onboarding/documents/<id>/               Delete document
```

Everything else is unchanged — registration, request bodies, response shapes, auth, submit payload, error format.

---

## How to Test End-to-End

1. Register a new mentor account → `POST /api/auth/register/` with `role: mentor`
2. Save professional profile → `PATCH /api/mentor-onboarding/` with `professional_profile` block
3. Save expertise → `PATCH /api/mentor-onboarding/` with `category_ids` and `expertise_ids`
4. Save packages → `PATCH /api/mentor-onboarding/` with `packages` and `accepts_inquiries`
5. Save availability → `PATCH /api/mentor-onboarding/` with `timezone` and `availability_windows`
6. Submit → `POST /api/mentor-onboarding/submit/` with the body below

```json
{
  "confirm_information_accurate": true,
  "terms_version": "mentor-terms-2026-08"
}
```

Expected response:

```json
{
  "application_id": 18,
  "status": "pending_review",
  "submitted_at": "2026-09-06T12:10:00Z",
  "estimated_review_days": 3
}
```

**Note on documents:** Document upload is not required to submit right now — the backend document requirement is turned off until S3 is configured. You can test the full flow (profile → expertise → packages → availability → submit) without uploading any files. The document upload screens can be built and tested independently.

---

## Quick Reference — PATCH Request Bodies

All saves go to `PATCH /api/mentor-onboarding/` with `Authorization: Bearer <token>`.

**Screen 1 — Professional Profile**
```json
{
  "current_step": "expertise",
  "professional_profile": {
    "profession": "software_engineering",
    "headline": "Senior Flutter Engineer at Acme",
    "company": "Acme",
    "years_experience": 8,
    "bio": "I help mobile engineers build reliable and maintainable Flutter applications.",
    "linkedin_url": "https://linkedin.com/in/sarah-chen",
    "portfolio_url": "https://sarah.example.com"
  }
}
```

**Screen 2 — Expertise**
```json
{
  "current_step": "verification",
  "category_ids": [1, 3],
  "expertise_ids": [2, 5, 9]
}
```

**Screen 4 — Services**
```json
{
  "current_step": "availability",
  "accepts_inquiries": true,
  "packages": [
    {
      "client_id": "mobile-15",
      "duration_minutes": 15,
      "price_usd": "20.00",
      "is_popular": false,
      "is_active": true
    },
    {
      "client_id": "mobile-30",
      "duration_minutes": 30,
      "price_usd": "35.00",
      "is_popular": true,
      "is_active": true
    }
  ]
}
```

**Screen 5 — Availability**
```json
{
  "current_step": "review",
  "timezone": "Asia/Karachi",
  "availability_windows": [
    {
      "client_id": "day-1-090000",
      "weekday": 1,
      "starts_at": "09:00:00",
      "ends_at": "17:00:00",
      "slot_interval_minutes": 30,
      "is_active": true
    }
  ]
}
```

Each save returns the full updated draft with a new `version` and updated `completion_percent`. Always store the `ETag` from the response header and send it as `If-Match` on the next save.
