# Document Upload Integration Guide

**Date:** 6 September 2026  
**Feature:** Mentor verification document upload (Screen 3 — Verification)  
**Status:** S3 backend fully configured and tested — ready to connect

---

## Overview

Documents are **not** sent through the backend API server. The flow is:

1. App asks the backend for a signed upload URL
2. App uploads the file **directly to S3** using that URL
3. App tells the backend the upload is done (with a checksum)
4. Backend verifies the file exists in S3 and marks it ready

This keeps large files off your server and is the standard mobile-to-cloud upload pattern.

---

## The Three-Step Flow

### Step 1 — Request a signed upload URL

```http
POST /api/mentor-onboarding/documents/upload-request/
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "document_type": "employment",
  "file_name": "employment-letter.pdf",
  "content_type": "application/pdf",
  "size_bytes": 482103
}
```

**Valid `document_type` values:**
- `identity`
- `employment`
- `certificate`
- `education`
- `portfolio`
- `other`

**Valid `content_type` values:**
- `application/pdf`
- `image/jpeg`
- `image/png`

**`size_bytes`:** integer, maximum `10485760` (10 MB). Larger files return `413`.  
Unsupported `content_type` returns `415`.

**Response `201`:**
```json
{
  "document_id": 71,
  "upload_url": "https://micro-mentor-docs.s3.amazonaws.com/mentor-docs/18/a3f5.../employment-letter.pdf?X-Amz-...",
  "upload_method": "PUT",
  "upload_headers": {
    "Content-Type": "application/pdf"
  },
  "expires_at": "2026-09-06T18:15:00Z"
}
```

Store the `document_id`. The `upload_url` expires in **10 minutes** — upload immediately after receiving it.

---

### Step 2 — Upload directly to S3

Use the `upload_url` exactly as returned. Send a `PUT` request with:
- The raw binary file bytes as the body
- The `Content-Type` header from `upload_headers`
- **No** `Authorization` header from your app — the URL is already signed

```
PUT <upload_url>
Content-Type: application/pdf

<binary file bytes>
```

This request goes directly to S3, not to your backend URL. A `200` response from S3 means the upload succeeded.

**Flutter example using `http` package:**
```dart
final uploadResponse = await http.put(
  Uri.parse(uploadUrl),
  headers: {'Content-Type': contentType},
  body: fileBytes,
);
// expect uploadResponse.statusCode == 200
```

---

### Step 3 — Confirm the upload

Compute the SHA-256 hash of the file bytes **before uploading** (or immediately after reading the file). Send the lowercase hex digest to the backend.

```http
POST /api/mentor-onboarding/documents/71/confirm/
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "checksum_sha256": "a3f5e9810d8f3e482a55d640e80c48b23537a822755b16773c8476453e76bace"
}
```

The checksum must be exactly 64 lowercase hex characters (SHA-256 output).

**Flutter SHA-256 example using `crypto` package:**
```dart
import 'package:crypto/crypto.dart';

final digest = sha256.convert(fileBytes);
final checksumHex = digest.toString(); // 64-char hex string
```

**Response `200`:**
```json
{
  "id": 71,
  "document_type": "employment",
  "file_name": "employment-letter.pdf",
  "status": "scanning",
  "uploaded_at": "2026-09-06T18:04:10Z"
}
```

The backend verifies the file exists in S3 and the size matches, then marks it `scanning`. It is then immediately promoted to `ready` (async malware scanning will be added later — for now it goes straight to ready).

---

## Document Statuses

| Status | Meaning |
|--------|---------|
| `requested` | Upload URL created, file not yet uploaded |
| `scanning` | File uploaded and confirmed, backend processing |
| `ready` | File verified — counts toward submission requirements |
| `unsafe` | Scan failed — prompt user to re-upload |
| `rejected` | Reviewer rejected this document |
| `deleted` | User deleted it |

After confirming, poll `GET /api/mentor-onboarding/` and check the `documents` array for the updated status. A document must be `ready` before the application can be submitted.

---

## Delete a Document

Only allowed while the application is editable (`draft` or `changes_requested`).

```http
DELETE /api/mentor-onboarding/documents/71/
Authorization: Bearer <access_token>
```

Response: `204 No Content`

---

## What the Draft Returns for Documents

After any save or GET of the draft, the `documents` array looks like this:

```json
{
  "documents": [
    {
      "id": 71,
      "document_type": "employment",
      "file_name": "employment-letter.pdf",
      "status": "ready",
      "uploaded_at": "2026-09-06T18:04:10Z",
      "created_at": "2026-09-06T18:00:00Z"
    }
  ]
}
```

The `storage_key` and S3 URL are **never** returned to the client. The backend handles all storage access.

---

## Submission Requirement

At least one document with `status: ready` and a `document_type` of `employment`, `certificate`, `education`, or `portfolio` is required before `POST /api/mentor-onboarding/submit/` will succeed.

If the requirement is not met, submit returns:
```json
{
  "code": "validation_error",
  "errors": {
    "documents.employment": [
      "Add at least one ready professional proof document (employment, certificate, education, or portfolio)."
    ]
  }
}
```

`identity` documents alone do not satisfy this requirement — a professional proof document is needed.

---

## Complete Flutter Implementation Checklist

- [ ] Read file bytes from device storage
- [ ] Compute SHA-256 hex digest of file bytes
- [ ] Get file size in bytes
- [ ] Call `POST /api/mentor-onboarding/documents/upload-request/` with document metadata
- [ ] PUT file bytes to the returned `upload_url` with correct `Content-Type` header (no auth header)
- [ ] Call `POST /api/mentor-onboarding/documents/<id>/confirm/` with the SHA-256 hex digest
- [ ] Poll `GET /api/mentor-onboarding/` or reload draft to show updated document status
- [ ] Show document as ready when `status == "ready"`
- [ ] Allow user to delete a document before submission (`DELETE /api/mentor-onboarding/documents/<id>/`)
- [ ] Block submit if no ready professional document exists (backend also enforces this)

---

## Error Reference for This Flow

| HTTP | `code` | Meaning |
|:----:|--------|---------|
| `415` | `validation_error` | Unsupported `content_type` — only PDF, JPEG, PNG |
| `413` | — | File too large (>10 MB) |
| `422` | `validation_error` | Missing field, invalid checksum format, or document already confirmed |
| `409` | `application_not_editable` | Application is not in `draft` or `changes_requested` status |
| `404` | `not_found` | Document ID not found or not owned by this user |
