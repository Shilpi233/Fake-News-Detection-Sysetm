# Fake News Detection System

Comprehensive fake-news and content-verification stack with a Django REST API, heuristic/ML analyzers for text and images, domain reputation checks, and a static frontend.

## Features
- Text analysis endpoint combining heuristics for authority, bias, evidence, sentiment, and recency to label content as real/fake with confidence scores.
- Image check endpoint with basic OCR, advertisement heuristics, and resolution/sharpness scoring for quick authenticity hints.
- Source verification via Google Fact Check Tools API and domain reputation lists (trusted, fake, satire), plus Google Custom Search–based search-and-verify.
- Article and prediction history persisted in the database with read-only listing; per-request throttling configured.
- User registration endpoint with stronger password rules; JWT auth enabled (SimpleJWT) and session auth supported.
- Frontend static pages served from the `frontend/` directory; CORS and CSRF protections are configurable.

## Tech Stack
- Django 5, Django REST Framework, SimpleJWT, django-cors-headers, social-auth-app-django (Google OAuth optional).
- SQLite by default; Postgres/MySQL supported via env switches in [backend/settings.py](backend/backend/settings.py).
- NLP and heuristics: langdetect/langid, TextBlob, VADER Sentiment; Pillow + pytesseract for image OCR (optional).

## Repository Layout
- [backend/](backend/) — Django project and API (`manage.py`, settings, apps).
- [backend/api/](backend/api/) — Article/prediction models, serializers, and REST endpoints.
- [frontend/](frontend/) — Static HTML/CSS/JS for the UI.
- [tools/verify_urls.ps1](tools/verify_urls.ps1) — Helper script for URL verification checks.

## Setup
1) Requirements: Python 3.11+, pip, and (optional) Tesseract OCR installed locally.
2) From `backend/`, create a virtual environment and install dependencies:
	```bash
	python -m venv .venv
	.venv\Scripts\activate
	pip install -r requirements.txt
	```
3) Create `backend/.env` (sample below) and run migrations:
	```bash
	python manage.py migrate
	python manage.py runserver
	```

### Env Sample (`backend/.env`)
```
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Database (choose one engine)
DB_ENGINE=django.db.backends.sqlite3
# DB_NAME=postgres
# DB_USER=postgres
# DB_PASSWORD=postgres
# DB_HOST=localhost
# DB_PORT=5432

# CORS/CSRF
CORS_ALLOWED_ORIGINS=http://localhost:3000
CSRF_TRUSTED_ORIGINS=http://localhost:3000

# JWT lifetimes (minutes/days)
JWT_ACCESS_MINUTES=10
JWT_REFRESH_DAYS=1

# Google integrations (optional)
GOOGLE_FACTCHECK_API_KEY=
GOOGLE_CSE_API_KEY=
GOOGLE_CSE_CX=
GOOGLE_OAUTH2_KEY=
GOOGLE_OAUTH2_SECRET=

# OCR
TESSERACT_PATH=C:\\Program Files\\Tesseract-OCR\\tesseract.exe
```

## API Quickstart
Base path defaults to `/api/` (see [backend/api/urls.py](backend/api/urls.py)). Key endpoints:
- `POST /api/predict/` — Analyze text; body: `title` (optional), `content`, `source_url` (optional). Returns article, prediction, and analysis details.
- `POST /api/predict-image/` — Multipart upload `image`; optional `title`. Returns heuristic label and analysis.
- `POST /api/verify-source/` — Body: `headline` or `url`, optional `languageCode`. Uses Fact Check API and domain reputation lists.
- `GET /api/verify-source/` — Query params `headline` or `url` (same logic).
- `GET /api/search-and-verify/?q=term&languageCode=en` — Google Custom Search + domain reputation scoring for each result.
- `POST /api/register/` — Username, email, password, confirm; strong password rules enforced.
- `GET /api/articles/` — List stored articles (paginated); `POST` requires auth.
- `GET /api/predictions/` — List stored predictions with article context.

Authentication: SimpleJWT is enabled; include `Authorization: Bearer <token>` once you implement token issuance (session auth also allowed in DRF settings).

## Frontend
Static pages live in [frontend/](frontend/) and are served via Django `STATICFILES_DIRS`; main UI at `frontend/fake_news_detector.html` and supporting auth/dashboard pages.

## Security & Ops Notes
- CORS allowlist, CSRF trusted origins, secure cookies, and HSTS are configurable in [backend/settings.py](backend/backend/settings.py).
- Rate limits set via DRF throttling (anon/user/register/predict buckets).
- Use strong `DJANGO_SECRET_KEY` and set `DJANGO_DEBUG=false` plus `DJANGO_ALLOWED_HOSTS` in production.
- Serve over HTTPS; set proper `STATIC_ROOT`/`MEDIA_ROOT` and run `collectstatic` for deployments.

## Testing
From `backend/`: `python manage.py test`. Add more API tests under [backend/api/tests.py](backend/api/tests.py).