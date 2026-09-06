"""
Shared API response helpers.

Use these everywhere so the contract is consistent across onboarding,
admin, and any future endpoint groups.

Standard shapes
---------------
success single resource:
    {"data": {...}, "meta": {"request_id": "..."}}

success list:
    {"data": [...], "pagination": {...}, "meta": {"request_id": "..."}}

error:
    {"error": {"code": "...", "message": "...", "fields": {...}, "request_id": "..."}}
"""

import uuid
from rest_framework import status
from rest_framework.response import Response


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------

def get_request_id(request=None):
    """Return the request ID from the incoming header or generate a new one."""
    if request is not None:
        rid = request.META.get("HTTP_X_REQUEST_ID") or request.META.get("HTTP_X_CORRELATION_ID")
        if rid:
            return rid
    return f"req_{uuid.uuid4().hex[:20]}"


# ---------------------------------------------------------------------------
# Success helpers
# ---------------------------------------------------------------------------

def data_response(data, request=None, status_code=status.HTTP_200_OK, pagination=None):
    """Wrap a dict or list in the standard {data, meta} envelope."""
    body = {"data": data, "meta": {"request_id": get_request_id(request)}}
    if pagination is not None:
        body["pagination"] = pagination
    return Response(body, status=status_code)


def created_response(data, request=None):
    return data_response(data, request=request, status_code=status.HTTP_201_CREATED)


def no_content_response():
    return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def error_response(
    code,
    message,
    fields=None,
    details=None,
    request=None,
    status_code=status.HTTP_400_BAD_REQUEST,
):
    body = {
        "error": {
            "code": code,
            "message": message,
            "fields": fields or {},
            "details": details or {},
            "request_id": get_request_id(request),
        }
    }
    return Response(body, status=status_code)


def validation_error(fields, message="Please correct the highlighted fields.", request=None):
    return error_response(
        code="validation_error",
        message=message,
        fields=fields,
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


def forbidden_error(message="You do not have permission to perform this action.", request=None):
    return error_response(
        code="forbidden",
        message=message,
        request=request,
        status_code=status.HTTP_403_FORBIDDEN,
    )


def not_found_error(message="The requested resource was not found.", request=None):
    return error_response(
        code="not_found",
        message=message,
        request=request,
        status_code=status.HTTP_404_NOT_FOUND,
    )


def conflict_error(code, message, details=None, request=None):
    return error_response(
        code=code,
        message=message,
        details=details or {},
        request=request,
        status_code=status.HTTP_409_CONFLICT,
    )


def stale_version_error(current_version, request=None):
    return error_response(
        code="version_conflict",
        message="This resource was updated by another request. Reload and retry.",
        details={"current_version": current_version},
        request=request,
        status_code=status.HTTP_409_CONFLICT,
    )
