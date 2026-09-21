# J-ONE HOTEL & LODGE

Booking website, guest-facing Progressive Web App and staff management
dashboard for J-ONE Hotel & Lodge.

- Hotel: **J-ONE HOTEL & LODGE**, Plot 566 Mgbowo Street, off Ezike Street
- Phone: **+234 803 211 2874** · Email: **jonathanonu76@gmail.com**
- Currency: **NGN** · Timezone: **Africa/Lagos**

---

## What is in this repository

| Directory | What it is |
|---|---|
| [`backend/`](backend/) | Django + Django REST Framework JSON API. Bookings, rooms, offers, payments, receipts, email, staff roles, reports. |
| [`frontend/`](frontend/) | Static HTML/CSS/vanilla-JS public site and staff dashboard, packaged as an installable PWA. No build step beyond `build.py`. |
| [`docs/`](docs/) | [Setup](docs/SETUP.md) and [usage](docs/USAGE.md) guides. |
| [`backend/docs/`](backend/docs/) | API reference, architecture notes, booking-flow spec and the OpenAPI 3 schema. |

The two halves deploy independently — the API on Render, the frontend on
Vercel — and talk to each other only over HTTP.

## How it fits together

Django is used **strictly as a JSON API**. The frontend never touches Django
templates, template context or the database; the backend never renders a page
the guest sees (its only HTML is transactional email).

The service worker is deliberately conservative and **never caches any `/api/`
response**. Availability, quotes, bookings, payments and authentication always
go straight to the backend, which stays the single source of truth. Offer
pricing in particular is always re-quoted server-side — the browser never
computes a discount it then trusts.

```
   Guest browser                Staff browser
        │                            │
        ▼                            ▼
  frontend/  (static PWA, Vercel)  frontend/dashboard/
        │                            │
        └──────────► HTTPS JSON ◄────┘
                         │
                  backend/  (Django REST, Render)
                         │
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
     MySQL          Paystack         Email provider
                                  (SMTP or HTTPS API)
```

## Quick start

Full instructions — prerequisites, environment variables, seed data,
deployment — are in **[docs/SETUP.md](docs/SETUP.md)**. The short version:

```bash
# API  → http://127.0.0.1:8000
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in the values you need
python manage.py migrate
python manage.py runserver

# Site → http://127.0.0.1:5500
cd frontend
python dev_server.py
```

Development defaults are safe: SQLite, console email (nothing leaves the
machine), Paystack test keys, no Redis required.

## Day-to-day operation

Taking bookings, handling payments and refunds, checking guests in (including
late and missed first-night arrivals), managing offers and reading the reports
are all covered in **[docs/USAGE.md](docs/USAGE.md)**.

## Testing

```bash
cd backend  && python manage.py test        # Django test suite
cd backend  && python manage.py check
cd frontend && python validate.py           # HTML + JS syntax across all pages
cd frontend && node --test tests-js/        # frontend unit tests
```

## Releasing the frontend

`frontend/build.py` stamps the version into `version.json`, `js/version.js` and
the service-worker cache name, then rewrites every page. Bump it on every
deploy, or returning visitors keep the old cached shell:

```bash
cd frontend && python build.py --bump patch
```

## License

Proprietary. All rights reserved by J-ONE Hotel & Lodge.
