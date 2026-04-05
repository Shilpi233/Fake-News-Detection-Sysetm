import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"

allowed_hosts_env = os.getenv("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(",") if host.strip()] if allowed_hosts_env else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "social_django",
    "api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.wsgi.application"


def _database_config():
    engine = os.getenv("DB_ENGINE", "django.db.backends.sqlite3")
    if "postgres" in engine:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "postgres"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    elif "mysql" in engine:
        return {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("DB_NAME", "fake_news"),
            "USER": os.getenv("DB_USER", "root"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


DATABASES = {"default": _database_config()}

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
"""
Serve frontend static files correctly.
BASE_DIR resolves to the outer 'backend' folder.
The frontend folder lives at <workspace>/frontend.
"""
STATICFILES_DIRS = [BASE_DIR.parent / "frontend"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.AllowAny",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "register": "5/hour",
        "predict": "50/hour",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# Social Auth Configuration
AUTHENTICATION_BACKENDS = (
    'social_core.backends.google.GoogleOAuth2',
    'django.contrib.auth.backends.ModelBackend',
)

# OAuth2 Keys (set in .env)
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.getenv("GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.getenv("GOOGLE_OAUTH2_SECRET")

# Redirect after OAuth login
SOCIAL_AUTH_LOGIN_REDIRECT_URL = '/static/fake_news_detector.html'
SOCIAL_AUTH_NEW_USER_REDIRECT_URL = '/static/fake_news_detector.html'

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "10"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "1"))),
}

cors_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5500,http://127.0.0.1:5500,http://localhost:5501,http://127.0.0.1:5501,http://localhost:8000,http://127.0.0.1:8000"
)
if cors_origins:
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
else:
    CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]

CORS_ALLOW_ALL_ORIGINS = False  # Never allow all origins
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["Content-Type", "X-CSRFToken"]

# CSRF Settings
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:3000").split(",")
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"

# Security Headers
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_SECURITY_POLICY = {
    "default-src": ("'self'",),
    "script-src": ("'self'", "'unsafe-inline'"),
    "style-src": ("'self'", "'unsafe-inline'"),
    "img-src": ("'self'", "data:", "https:"),
}

# Cookie Security
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"

# Email Configuration
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
