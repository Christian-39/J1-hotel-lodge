# Setup

How to install, configure and deploy J-ONE Hotel & Lodge. For day-to-day
operation see [USAGE.md](USAGE.md).

## 1. Requirements

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11+ | backend, and the frontend's dev server / build script |
| Node.js | 18+ | frontend unit tests (`node --test`) |
| MySQL | 8.0+ | production only (development uses SQLite) |
| Redis | 5+ | production only (cache + Celery broker for scheduled jobs) |

No frontend package manager is required. There is no npm install.

## 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`mysqlclient` is only needed in production. If it fails to build locally,
either install the headers (`sudo apt install pkg-config
default-libmysqlclient-dev build-essential python3-dev`) or skip it — SQLite is
the development default.

Create the schema and a login:

```bash
python manage.py migrate
python manage.py seed_demo          # hotel identity + clearly-labelled DEMO rooms
python manage.py createsuperuser    # your admin account
python manage.py runserver
```

- API index: <http://localhost:8000/api/>
- Swagger: <http://localhost:8000/api/docs/> · ReDoc: `/api/redoc/`
- Health check: `/api/health/`

`seed_demo` loads placeholder prices, images and room counts. Replace them with
real hotel content through the staff console before launch.

### Settings modules

| Module | Used for |
|---|---|
| `config.settings.development` | SQLite, console email, eager tasks, permissive CORS |
| `config.settings.production` | MySQL (required), Redis, S3/B2 media, strict security headers |

`manage.py` defaults to development; `config/wsgi.py` (Gunicorn) defaults to
production. Override with `DJANGO_SETTINGS_MODULE`.

Production refuses to boot on SQLite, and validates that the selected email
provider actually has credentials — misconfiguration fails loudly at startup
rather than silently dropping mail.

## 3. Frontend

```bash
cd frontend
python3 dev_server.py 5500 http://127.0.0.1:8000
```

`dev_server.py` serves the static site and proxies `/api/` and `/media/` to the
backend, so the site runs same-origin exactly as it does in production. Open
<http://127.0.0.1:5500>; the staff console is at `/login.html`.

If you host the frontend on a different origin than the API, set
`API_BASE_URL` in `js/config.js` and add that origin to `CORS_ALLOWED_ORIGINS`
on the backend.

After editing anything in `components/` (header, footer, mobile nav), re-inline
it into the pages and re-check the result:

```bash
python3 build.py
python3 validate.py
```

## 4. Configuration

Every setting is an environment variable read from `.env`
(see [`backend/.env.example`](../backend/.env.example) for the annotated list).
No secret belongs in code.

### Core

| Variable | Notes |
|---|---|
| `DJANGO_SECRET_KEY` | Generate one per environment. |
| `DJANGO_DEBUG` | `True` locally, `False` everywhere else. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated, no spaces. |
| `FRONTEND_URL` | Public URL of the site. Used for links in emails and the default email logo. |

### Database (production)

Provide either `DATABASE_URL=mysql://user:pass@host:3306/jone_hotel` or the
individual `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT`.

```sql
CREATE DATABASE jone_hotel CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### Paystack

1. Get keys from the Paystack dashboard → Settings → API Keys & Webhooks.
2. Set `PAYSTACK_SECRET_KEY` and `PAYSTACK_PUBLIC_KEY`. The secret never
   leaves the server.
3. Set the webhook URL to `https://<api-host>/api/payments/webhook/`. The
   endpoint verifies the `x-paystack-signature` HMAC before doing anything.
4. Enable the events `charge.success`, `refund.pending`, `refund.processing`,
   `refund.processed` and `refund.failed`.
5. `PAYMENT_CALLBACK_URL` should point at the frontend verify page (defaults to
   `{FRONTEND_URL}/payment-verify.html`).

With no keys configured the API returns `503 PAYMENT_NOT_CONFIGURED`. There is
deliberately no fake success path.

### Email

Email is delivered synchronously — no queue, no worker, no retry. Pick a
transport with `EMAIL_PROVIDER`:

| Value | Transport | Inline `cid:` images |
|---|---|---|
| `smtp` / `django` | Django's `EMAIL_BACKEND` — any SMTP vendor | yes |
| `brevo` | Brevo HTTPS API | no |
| `sendgrid` | SendGrid HTTPS API | yes |
| `mailgun` | Mailgun HTTPS API (also set `EMAIL_API_DOMAIN`) | yes |
| `postmark` | Postmark HTTPS API | yes |
| `resend` | Resend HTTPS API | no |

HTTPS providers read `EMAIL_API_KEY`; SMTP uses `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_USE_TLS`, `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`.

Use an HTTPS API provider on hosts that block outbound SMTP — Render's free
tier blocks ports 25, 465 and 587 entirely.

`DEFAULT_FROM_EMAIL` **must** be an address verified with the chosen provider,
and must not be wrapped in quotes in a hosting dashboard:

```
DEFAULT_FROM_EMAIL=J-one hotel & lodge <sender@example.com>
```

Providers that cannot deliver inline images fall back to a hosted logo. It
defaults to `{FRONTEND_URL}/assets/icons/logo-official.png`; override with
`EMAIL_LOGO_URL` if the logo lives elsewhere.

Verify the whole chain before launch — credentials are never printed:

```bash
python manage.py email_check                    # configuration only
python manage.py email_check --send you@x.com   # + one real delivery
```

### Media storage (production)

Set `BACKBLAZE_KEY_ID`, `BACKBLAZE_APPLICATION_KEY`, `BACKBLAZE_BUCKET_NAME`
and `BACKBLAZE_ENDPOINT` to store uploads on Backblaze B2 (or any
S3-compatible service) via django-storages. Make the bucket public, or set
`MEDIA_CUSTOM_DOMAIN`, so image URLs render in browsers. Uploads are validated
for extension, size (`MAX_UPLOAD_MB`) and real image content.

Check it with `python manage.py check_media_storage`.

### Redis and scheduled jobs

Redis is production-only. It backs the cache, throttling, and the Celery broker
for the two scheduled jobs: expiring abandoned PENDING bookings and automatic
checkout. **Email never touches Celery or Redis.**

Development needs none of it — tasks run eagerly in-process with an in-memory
broker.

## 5. Deployment

The repository ships a Render blueprint at
[`backend/render.yaml`](../backend/render.yaml): one web service, one Celery
worker and one beat process, plus managed MySQL and Redis.

- Build command: `./build.sh` (installs dependencies, collects static, migrates)
- Start command: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`
- Health check path: `/api/health/`
- Set every production variable from `.env.example` in the dashboard

The frontend is a static bundle — deploy `frontend/` to any static host
(Vercel, Netlify, Nginx). Make sure `/api/` reaches the backend on the same
origin, or configure `API_BASE_URL` plus CORS.

Before deploying a frontend change, stamp a new version so returning visitors
are prompted to refresh — see [USAGE.md](USAGE.md#releasing-a-frontend-update).

## 6. Troubleshooting

**Images 404 in development** — media is only served by `runserver` when
`DEBUG=True`.

**429 responses while testing** — sensitive endpoints are rate limited. Wait a
minute, or restart the dev server to clear the in-memory cache.

**Emails don't arrive in development** — by design they print to the terminal
via the console backend. Set `EMAIL_PROVIDER` and real credentials to send.

**Emails send but the logo is broken** — the provider cannot inline images.
Confirm `email_check` reports an HTTPS logo reference and that the URL is
publicly reachable.

**The site can't reach the API** — check the browser console for a CORS error
and confirm `API_BASE_URL` in `js/config.js` matches where the backend runs.
