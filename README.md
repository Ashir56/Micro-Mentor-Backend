# Micro-Mentor Django Backend Blueprint

This is a lightweight Django backend scaffold derived from `mentorship.html`. It intentionally models only the features shown in the prototype:

- Email/password registration and login with mentee or mentor role selection
- Home feed with categories, featured mentors, and upcoming session
- Mentor discovery, search, profile detail, expertise, pricing, reviews, and availability
- Booking flow with session goals, package duration, payment confirmation, and video room URL placeholder
- Post-session review submission
- Conversations and chat messages
- Profile stats for mentees
- Mentor dashboard stats, today's sessions, availability, Stripe Connect status placeholder, and profile completion

## Files

- `mentorship/models.py` contains the core data model.
- `mentorship/views.py` contains JSON views for each prototype screen/action.
- `mentorship/urls.py` maps API routes to those views.
- `micro_mentor/urls.py` mounts the API at `/api/`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```

## API surface

```text
POST /api/auth/register/
POST /api/auth/login/
POST /api/auth/logout/
GET  /api/home/
GET  /api/mentors/?q=&category=
GET  /api/mentors/<mentor_id>/
GET  /api/mentors/<mentor_id>/availability/
POST /api/bookings/
GET  /api/sessions/<session_id>/
POST /api/sessions/<session_id>/payment/confirm/
POST /api/sessions/<session_id>/complete/
POST /api/sessions/<session_id>/review/
GET  /api/conversations/
GET  /api/conversations/<conversation_id>/
POST /api/conversations/<conversation_id>/messages/
GET  /api/profile/
GET  /api/mentor-dashboard/
```

Payment and video-session behavior are placeholders. In a production build, `confirm_payment` should be driven by Stripe webhooks, and `video_room_url` should come from your video provider.
