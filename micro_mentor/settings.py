import os
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local .env when available for local development.
DOTENV_PATH = BASE_DIR / ".env"
if DOTENV_PATH.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(DOTENV_PATH)
    except ImportError:
        pass

SECRET_KEY = os.environ.get("SECRET_KEY", "micro-mentor-development-secret-key-change-me")
DEBUG = os.environ.get("DEBUG", "False").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "https://*.railway.app").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "mentorship",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",          # must be before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if find_spec("whitenoise"):
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "micro_mentor.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "micro_mentor.wsgi.application"


def _build_database_config():
    database_url = os.environ.get("DATABASE_URL")
    if isinstance(database_url, bytes):
        database_url = database_url.decode()

    database_url = (database_url or "").strip().strip('"').strip("'")
    if not database_url:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }

    parsed_database_url = urlparse(database_url)
    options = dict(parse_qsl(parsed_database_url.query, keep_blank_values=True))
    options.pop("pgbouncer", None)

    if parsed_database_url.hostname and "supabase" in parsed_database_url.hostname.lower():
        options.setdefault("sslmode", "require")

    if parsed_database_url.scheme in {"postgres", "postgresql"} and "sslmode" not in options:
        options.setdefault("sslmode", "require")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed_database_url.path.lstrip("/"),
        "USER": parsed_database_url.username or "",
        "PASSWORD": parsed_database_url.password or "",
        "HOST": parsed_database_url.hostname or "",
        "PORT": str(parsed_database_url.port or 5432),
        "CONN_MAX_AGE": 600,
        "OPTIONS": options,
    }


DATABASES = {"default": _build_database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if find_spec("whitenoise"):
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "mentorship.parsers.ApplicationJSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
        "mentorship.parsers.AnyContentTypeJSONParser",
    ),
}

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "30"))),
    "ROTATE_REFRESH_TOKENS": True,         # rotate on each refresh so refresh tokens are single-use
    "BLACKLIST_AFTER_ROTATION": True,      # blacklist old refresh token after rotation
    "AUTH_HEADER_TYPES": ("Bearer",),
    "TOKEN_OBTAIN_SERIALIZER": "rest_framework_simplejwt.serializers.TokenObtainPairSerializer",
}

# ---------------------------------------------------------------------------
# CORS — browser cross-origin access
# ---------------------------------------------------------------------------
# Exact origins that may send credentialed requests.
# Set CORS_ALLOWED_ORIGINS in the environment for production.
# Example: CORS_ALLOWED_ORIGINS=https://admin.micro-mentor.app,https://app.micro-mentor.app
_cors_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in _cors_origins_env.split(",") if o.strip()
]

# In local development fall back to allowing all origins when no list is configured.
CORS_ALLOW_ALL_ORIGINS = not CORS_ALLOWED_ORIGINS and DEBUG

CORS_ALLOW_CREDENTIALS = True  # required for Authorization header to be forwarded

CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "if-match",
    "idempotency-key",
    "x-request-id",
    "x-csrftoken",
]

# ---------------------------------------------------------------------------
# S3 bucket CORS configuration (apply this in the AWS console or via CLI)
# ---------------------------------------------------------------------------
# Run once after bucket creation (replace BUCKET_NAME):
#
#   aws s3api put-bucket-cors --bucket BUCKET_NAME --cors-configuration '{
#     "CORSRules": [{
#       "AllowedOrigins": ["https://admin.micro-mentor.app", "https://app.micro-mentor.app"],
#       "AllowedMethods": ["PUT"],
#       "AllowedHeaders": ["Content-Type"],
#       "ExposeHeaders": ["ETag"],
#       "MaxAgeSeconds": 3000
#     }]
#   }'
#
# This allows the Flutter web app to PUT files directly to S3 using the
# presigned URL returned by /api/mentor-onboarding/documents/upload-request/.
# Without this, browser preflight OPTIONS requests to S3 will fail.

# ---------------------------------------------------------------------------
# Document storage — AWS S3 private bucket
# ---------------------------------------------------------------------------
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "us-east-1")
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None       # Keep bucket private; access via presigned URLs only.
AWS_QUERYSTRING_AUTH = True  # Presigned URLs required for all object access.

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",  # Prints to stdout in dev.
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() in {"1", "true", "yes"}
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@micro-mentor.app")

# ---------------------------------------------------------------------------
# Current accepted mentor terms version
# ---------------------------------------------------------------------------
MENTOR_TERMS_VERSION = os.environ.get("MENTOR_TERMS_VERSION", "mentor-terms-2026-08")

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
# Set to True once S3 is configured and document uploads are working end-to-end.
REQUIRE_DOCUMENTS_FOR_SUBMISSION = os.environ.get("REQUIRE_DOCUMENTS_FOR_SUBMISSION", "False").lower() in {"1", "true", "yes"}
