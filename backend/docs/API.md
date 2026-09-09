# J-ONE HOTEL & LODGE — API Reference

Base URL: `https://<host>/api/` · Format: JSON · Auth: `Authorization: Bearer <access_token>`

Live interactive version: **`/api/docs/`** (Swagger UI, generated from code — it can never drift).

**User-facing request/response exactness lives in [`FRONTEND_CONTRACT.md`](FRONTEND_CONTRACT.md).**
This file is the complete endpoint inventory with permissions and behaviors.

Legend — 🔓 public · 🔑 any authenticated user · 🛎 staff (any role) · 🧰 manager+admin · 👑 admin only

## Response envelope (every endpoint)

```jsonc
// success (object)
{ "success": true, "message": "...", "data": { } }

// success (paginated list)
{ "success": true, "message": "...", "data": [ ],
  "pagination": { "count": 100, "page": 1, "page_size": 20,
                  "total_pages": 5, "next": "...", "previous": null } }

// error
{ "success": false, "code": "MACHINE_CODE", "message": "Human message.",
  "errors": { "field": ["problem"] } }
```

Standard codes: `VALIDATION_ERROR` (400) · `UNAUTHORIZED` (401) · `FORBIDDEN` (403) ·
`RESOURCE_NOT_FOUND` (404) · `RATE_LIMITED` (429) · `SERVER_ERROR` (500) plus
domain codes: `INVALID_DATES`, `CAPACITY_EXCEEDED`, `ROOM_UNAVAILABLE` (409),
`BOOKING_EXPIRED` (409), `INVALID_BOOKING_STATE` (409), `CANCELLATION_NOT_ALLOWED`,
`OFFER_NOT_APPLICABLE`, `OUTSTANDING_BALANCE`, `PAYMENT_NOT_CONFIGURED` (503),
`PAYMENT_FAILED`, `PAYMENT_ALREADY_COMPLETED` (409), `PAYMENT_AMOUNT_MISMATCH`,
`PAYMENT_GATEWAY_ERROR` (502).

Conventions: dates `YYYY-MM-DD` · datetimes ISO 8601 · money as strings
(`"25000.00"`) · IDs are integers · references are strings
(`J1-YYYYMMDD-XXXXXXXX`, payments `J1P-…`). Pagination params everywhere:
`page`, `page_size` (max 100).

---

## Meta

| Method & path | Auth | Description |
|---|---|---|
| `GET /api/` | 🔓 | API index |
| `GET /api/health/` | 🔓 | `{ "status": "ok", "database": "up" }` |
| `GET /api/schema/` | 🔓 | OpenAPI 3 schema |
| `GET /api/docs/` | 🔓 | Swagger UI |

## Auth (`/api/auth/`)

| Method & path | Auth | Body → Returns | Notes |
|---|---|---|---|
| `POST /register/` | 🔓 | email, first_name, last_name, phone?, password, password_confirm → `{user, tokens}` | Role is always `GUEST`. Throttled. |
| `POST /login/` | 🔓 | email, password → `{user, tokens}` | `UNAUTHORIZED` on bad credentials. 5/min/IP. |
| `POST /token/refresh/` | 🔓 | refresh → `{tokens.access(, refresh)}` | Rotation: old refresh is blacklisted. |
| `POST /logout/` | 🔑 | refresh | Blacklists the refresh token. |
| `GET /profile/` | 🔑 | → user | |
| `PATCH /profile/` | 🔑 | first_name?, last_name?, phone?, profile_image? → user | Role/active flags NOT editable. |
| `POST /password/change/` | 🔑 | current_password, new_password, new_password_confirm | |
| `POST /password/reset/` | 🔓 | email | Generic response (no account-existence leak). |
| `POST /password/reset/confirm/` | 🔓 | uid, token, new_password, new_password_confirm | Throttled. |

## Public content

| Method & path | Auth | Query/Notes |
|---|---|---|
| `GET /api/hotel/` | 🔓 | Hotel identity, contact, times, currency, stay rules, maps URL, social links |
| `GET /api/hotel/policies/` | 🔓 | Active policies (array) |
| `GET /api/facilities/` | 🔓 | Active facilities (array, `icon` identifiers) |
| `GET /api/gallery/` | 🔓 | `?category=HOTEL\|ROOMS\|RESTAURANT\|FACILITIES\|EVENTS\|EXTERIOR\|OTHER` — paginated `{categories, items}` |
| `GET /api/offers/` | 🔓 | Currently-running offers |
| `GET /api/rooms/` | 🔓 | Room-type catalog (lightweight rows) |
| `GET /api/rooms/<slug or id>/` | 🔓 | Room-type detail: images, amenities, applicable offers |
| `GET /api/rooms/availability/?check_in&check_out&guests&rooms&room_type` | 🔓 | **Authoritative availability + live pricing**. Throttled 240/h. |
| `POST /api/enquiries/` | 🔓 | name, email, phone?, subject, message (`website` = honeypot). Throttled 10/h. |

## Guest bookings (`/api/bookings/`)

| Method & path | Auth | Body → Returns |
|---|---|---|
| `POST /quote/` | 🔓 | room_type, check_in, check_out, rooms?, adults?, children?, offer_code? → full price breakdown + policies + hold info (nothing persisted) |
| `GET /` | 🔑 | my bookings (paginated; `?status=`) |
| `POST /` | 🔑 | stay fields + `guest{}`? + special_requests? → 201 booking (PENDING, inventory held, `expires_at` set). Throttled. |
| `GET /<id or reference>/` | 🔑 (owner/staff) | full booking detail with `can_pay`, `can_cancel` |
| `POST /<id or ref>/cancel/` | 🔑 (owner/staff) | reason? → cancelled booking. Enforces deadline/fee rules. |
| `GET /<id or ref>/receipt/` | 🔑 (owner/staff) | hotel + guest + stay + payment lines receipt |

Ownership is enforced **object-level** — another guest's booking reference/id
returns `403 FORBIDDEN`.

## Payments (`/api/payments/`)

| Method & path | Auth | Notes |
|---|---|---|
| `POST /initialize/` | 🔑 (owner/staff) | `{booking_reference}` → `{reference, authorization_url, access_code, amount, currency, public_key}`. Amount is computed server-side. |
| `GET /verify/<reference>/` | 🔑 (owner/staff) | Server verifies directly with Paystack; **idempotent**; confirms booking on success. |
| `POST /webhook/` | 🔓 signed | Paystack → `x-paystack-signature` HMAC-SHA512 validated before anything else. Always 200 on accepted/ignored events. |

## Notifications (`/api/notifications/`)

| Method & path | Auth | Notes |
|---|---|---|
| `GET /` | 🔑 | `{unread_count, notifications[]}` paginated (`?unread=true`) |
| `GET /unread-count/` | 🔑 | `{unread_count}` |
| `POST /<id>/read/` · `POST /read-all/` | 🔑 | returns `{unread_count}` |

---

## Staff API (`/api/admin/`)

All staff endpoints require `role ∈ {ADMIN, MANAGER, RECEPTIONIST}` plus the
finer grants below.

| Method & path | | Description |
|---|---|---|
| `GET /dashboard/` | 🛎 | Aggregated dashboard (financial block only for managers/admins) |
| `GET/POST /bookings/` | 🛎 | List (filter: status, payment_status, source, room_type, date_from, date_to, check_in, check_out, search, ordering) · manual booking create |
| `GET/PATCH /bookings/<id\|ref>/` | 🛎 | Detail / modify (dates, rooms, guests, notes — re-validates availability & reprices) |
| `POST /bookings/<id\|ref>/confirm/` | 🛎 | Confirm without online payment (pay at hotel) |
| `POST /bookings/<id\|ref>/cancel/` | 🛎 | Staff cancel (audited) |
| `POST /bookings/<id\|ref>/check-in/` ↪ `check-out/` ↪ `no-show/` `assign-room/` | 🛎 | Front-desk actions (checkout guards `OUTSTANDING_BALANCE` unless `allow_balance_due`) |
| `GET /guests/` · `GET/PATCH /guests/<id>/` | 🛎 | Guest CRM + stay history |
| `GET /payments/` · `GET /payments/<id\|ref>/` | 🛎 | Payment records (sanitized) |
| `POST /payments/record/` | 🛎 | Record CASH/POS/BANK_TRANSFER payments |
| `GET/POST /rooms/` · `GET/PATCH/DELETE /rooms/<id>/` | 🛎 read · 🧰 write | DELETE = soft deactivation |
| `GET/POST /room-types/` · `GET/PATCH/DELETE /room-types/<id>/` | 🛎 read · 🧰 write | Pricing, capacity, amenities; DELETE = deactivate |
| `POST /room-types/<id>/images/` · `PATCH/DELETE /room-images/<id>/` | 🧰 | Multipart upload / reorder / primary |
| `GET/POST /amenities/` · `PATCH/DELETE /amenities/<id>/` | 🛎 read · 🧰 write | |
| `GET/POST /facilities/` · `PATCH/DELETE /facilities/<id>/` | 🛎 read · 🧰 write | |
| `GET/POST /policies/` · `PATCH/DELETE /policies/<id>/` | 🛎 read · 🧰 write | |
| `GET /settings/` · `PATCH /settings/` | 🧰 read · 👑 write | Business rules (tax, deposit %, deadlines…) — audited diffs |
| `GET/POST /offers/` · `GET/PATCH/DELETE /offers/<id>/` | 🛎 read · 🧰 write | Dates/discounts/scope validated |
| `GET/POST /gallery/` · `GET/PATCH/DELETE /gallery/<id>/` | 🛎 read · 🧰 write | |
| `GET /enquiries/` · `GET/PATCH /enquiries/<id>/` | 🛎 | Status workflow NEW→IN_PROGRESS→RESOLVED→CLOSED |
| `GET /reports/revenue/?start_date&end_date` | 🧰 | Totals, by-day, by-provider, refunds |
| `GET /reports/occupancy/?start_date&end_date` | 🧰 | Per-day occupied rooms + average % |
| `GET /reports/bookings/?start_date&end_date` | 🧰 | Counts by status/payment status + room-type revenue |
| `GET/POST /users/` · `GET/PATCH /users/<id>/` | 👑 | Staff accounts, roles, activation — audited |
| `GET /audit-logs/` · `GET /audit-logs/<id>/` | 👑 | Read-only immutable trail (filter: action, object_type, actor, date range) |

## Rate limits (429 + `RATE_LIMITED`)

login 5/min · register 20/h · password reset 10/h · enquiry 10/h ·
booking create 30/h · availability 240/h · payment init 20/h · payment verify 60/h ·
**paystack webhook 300/min** (per IP; deliberately generous so legitimate Paystack
retries/bursts are never dropped, while abuse floods are blunted)
(per user for authenticated scopes, per IP otherwise).
