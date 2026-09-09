# FRONTEND ↔ BACKEND CONTRACT — J-ONE HOTEL & LODGE

**This document is the binding agreement between the separated frontend
(HTML/CSS/Vanilla JS) and this API.** Field names, types, envelopes, error
codes, and state values below are contractual. Any intentional change must
update this file in the same commit (spec §137/§144).

Quick rules for the frontend (Vanilla `fetch`):

```js
const res = await fetch(url, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  },
  body: JSON.stringify(payload),
});
const body = await res.json();          // ALWAYS the same envelope
if (body.success) { /* body.data */ }
else { /* body.code, body.message, body.errors? */ }
```

* No special-case parsing per endpoint. HTTP status + `success` decide.
* **Types:** ids `int` · dates `"YYYY-MM-DD"` · datetimes ISO-8601 · **money strings `"25000.00"`** (never floats) · booleans JSON booleans.
* **Never send:** prices, totals, roles, availability claims — the server ignores/rejects them.
* Base URL is injected by the frontend (env var), e.g. `https://api.example.com/api/`.
* Media URLs are absolute and render directly in `<img src>`.

## Error codes the frontend must handle

`VALIDATION_ERROR` (400) · `UNAUTHORIZED` (401 — refresh & retry, else login) ·
`FORBIDDEN` (403) · `RESOURCE_NOT_FOUND` (404) · `RATE_LIMITED` (429 — show retry timer) ·
`SERVER_ERROR` (500) · and domain codes: `INVALID_DATES`, `CAPACITY_EXCEEDED`,
`ROOM_UNAVAILABLE`, `BOOKING_EXPIRED`, `INVALID_BOOKING_STATE`,
`CANCELLATION_NOT_ALLOWED`, `OFFER_NOT_APPLICABLE`, `OUTSTANDING_BALANCE`,
`PAYMENT_NOT_CONFIGURED`, `PAYMENT_FAILED`, `PAYMENT_ALREADY_COMPLETED`,
`PAYMENT_AMOUNT_MISMATCH`, `PAYMENT_GATEWAY_ERROR`.

`errors` (when present) maps field → message list:

```json
{ "success": false, "code": "VALIDATION_ERROR", "message": "Validation failed.",
  "errors": { "check_in": ["Check-in date cannot be in the past."] } }
```

## Pagination envelope (all lists)

```json
{ "success": true, "message": "Success", "data": [ ... ],
  "pagination": { "count": 100, "page": 1, "page_size": 20,
                  "total_pages": 5, "next": "…/page=2", "previous": null } }
```

Request params: `?page=1&page_size=20` (max 100). Counts/ids only — `next`/`previous` may be URLs.

---

# PUBLIC WEBSITE

## 1. Hotel info — `GET /api/hotel/`

Renders: header/footer identity, contact block, map, times.

```jsonc
{ "success": true, "message": "Success",
  "data": {
    "hotel_name": "J-ONE HOTEL & LODGE", "tagline": "", "description": "",
    "address": "Plot 566 Mgbowo Street, off Ezike Street",
    "city": "", "state": "", "country": "Nigeria",
    "phone": "+234803 211 2874", "email": "jonathanonu76@gmail.com",
    "google_maps_url": "",                      // embed on contact page when non-empty
    "social_links": [{ "platform": "facebook", "url": "https://…" }],
    "check_in_time": "14:00:00", "check_out_time": "12:00:00",
    "currency": "NGN", "min_stay_nights": 1, "max_stay_nights": 30 } }
```

## 2. Policies — `GET /api/hotel/policies/`

`data`: `[{ "id": 1, "key": "cancellation", "title": "…", "content": "…", "is_active": true, "display_order": 2, "updated_at": "…" }]` (plain text — render safely, never `innerHTML`).

## 3. Facilities — `GET /api/facilities/`

`data`: `[{ "id", "name", "slug", "description", "icon": "wifi", "image_url": "https://…" | null, "is_active", "display_order" }]`
→ map `icon` to the frontend icon set; fall back gracefully when empty.

## 4. Gallery — `GET /api/gallery/?category=ROOMS`

Categories: `HOTEL` `ROOMS` `RESTAURANT` `FACILITIES` `EVENTS` `EXTERIOR` `OTHER`.

```jsonc
"data": { "categories": ["HOTEL", "ROOMS", …],
  "items": [ { "id", "title", "description", "category", "alt_text",
               "image_url", "display_order", "is_active", "created_at" } ] },
"pagination": { … }
```

## 5. Offers — `GET /api/offers/`

```jsonc
"data": [ { "id", "title", "slug", "short_description", "description",
  "discount_type": "PERCENTAGE" | "FIXED_AMOUNT", "discount_value": "10.00",
  "start_date", "end_date", "min_nights": 1, "max_nights": 5 | null,
  "applicable_room_types": [{ "id", "name", "slug" }] | [],   // [] = applies to all
  "is_featured": false, "image_url": null, "terms": "" } ]
```

Validity is display-only info — the **booking/quote endpoints decide** application.

## 6. Room catalog — `GET /api/rooms/`

```jsonc
"data": [ { "id": 2, "name": "Deluxe Room", "slug": "deluxe-room",
  "short_description": "…", "base_price": "25000.00", "max_guests": 2,
  "bed_type": "King Bed", "bed_count": 1, "room_size": "28 m²", "view": "Courtyard View",
  "is_featured": true, "primary_image_url": "https://…" | null,
  "amenities": [{ "name": "Wi-Fi", "icon": "wifi" }] } ]
```

## 7. Room detail — `GET /api/rooms/{slug or id}/`

All list fields **plus**:

```jsonc
{ "description": "…", "smoking_policy": "NON_SMOKING", "children_allowed": true,
  "extra_guest_allowed": true, "extra_guest_fee": "5000.00",
  "images": [ { "id", "image_url", "alt_text", "caption", "display_order", "is_primary" } ],
  "offers": [ { "id", "slug", "title", "short_description", "discount_type", "discount_value", "end_date" } ] }
```

## 8. Availability — `GET /api/rooms/availability/`

Params: `check_in*`, `check_out*` (YYYY-MM-DD), `guests`≥1, `rooms`≥1, `room_type` (slug or id).

```jsonc
"data": { "check_in": "2026-10-15", "check_out": "2026-10-18", "nights": 3,
  "guests": 2, "rooms": 1,
  "results": [ {
    "room_type": { …same shape as catalog row… },
    "available_rooms": 3, "requested_rooms": 1,
    "max_guests_per_room": 2, "extra_guest_allowed": false,
    "bookable": true,
    "message": "Not enough rooms available for these dates." | null,
    "pricing": {                                // null when unsellable (see message)
      "nights": 3, "rooms": 1, "adults": 2, "children": 0, "guests": 2,
      "currency": "NGN", "price_per_night": "25000.00", "subtotal": "75000.00",
      "discount": "7500.00",
      "offer": { "id", "title", "code": "DEMO10", "discount_type", "discount_value" } | null,
      "extra_guests": 0, "extra_guest_fee": "0.00",
      "tax": "0.00", "service_fee": "0.00",
      "total": "67500.00", "required_payment": "67500.00", "amount_due_online": "67500.00" } } ] }
```

**No availability** ⇒ `200` with `results: []` or rows whose `bookable` is false.
Treat these as *preview* prices — the final word is `/api/bookings/quote/`.

## 9. Enquiries — `POST /api/enquiries/`

Body: `{ "name": "…", "email": "…", "phone": "…", "subject": "…", "message": "…" }`
(optional hidden field `"website"`: leave blank — it's a spam honeypot).
→ `201 { success, message }` (no data payload). Throttled; HTML stripped server-side.

## 10. Auth endpoints

| Endpoint | Body | `data` on success |
|---|---|---|
| `POST /api/auth/register/` | email*, first_name*, last_name*, phone, password*, password_confirm* | `{ user, tokens }` |
| `POST /api/auth/login/` | email*, password* | `{ user, tokens }` |
| `POST /api/auth/token/refresh/` | refresh* | `{ tokens: { access, refresh? } }` |
| `POST /api/auth/logout/` | refresh* | — |
| `GET /api/auth/profile/` | — | user |
| `PATCH /api/auth/profile/` | any of first_name/last_name/phone | user |
| `POST /api/auth/password/change/` | current/new/new_confirm passwords | — |
| `POST /api/auth/password/reset/` | email | generic message (always same) |
| `POST /api/auth/password/reset/confirm/` | uid, token, new passwords | — |

`user`:

```jsonc
{ "id": 7, "email": "…", "first_name": "…", "last_name": "…", "full_name": "…",
  "phone": "…", "role": "GUEST" | "RECEPTIONIST" | "MANAGER" | "ADMIN",
  "email_verified": false, "profile_image_url": null,
  "date_joined": "…", "last_login": "…" }
```

`tokens`: `{ "access": "jwt…", "refresh": "jwt…" }` — store access in memory
(preferred) or sessionStorage; refresh per your policy.
Frontend role UI checks: show staff screens when `role != "GUEST"` — the API
still enforces everything server-side.

---

# BOOKING FLOW (guest)

## 11. Quote — `POST /api/bookings/quote/`

Body:
```jsonc
{ "room_type": "deluxe-room",     // slug or id (string)
  "check_in": "2026-10-15", "check_out": "2026-10-18",
  "rooms": 1, "adults": 2, "children": 0, "offer_code": "SAVE10" }
```

`data` = the `pricing` object shown in §8 **plus**:

```jsonc
{ "room_type": { "id", "name", "slug" }, "check_in": "…", "check_out": "…",
  "policies": { "check_in_time": "14:00", "check_out_time": "12:00",
    "cancellation_deadline_hours": 48, "cancellation_fee_percent": "0.00" },
  "hold_info": { "pending_booking_minutes": 15,
    "note": "Inventory is held for this many minutes once the booking is created." } }
```

Errors: `INVALID_DATES`, `CAPACITY_EXCEEDED`, `OFFER_NOT_APPLICABLE` (bad code). Nothing is persisted.

## 12. Create booking — `POST /api/bookings/` 🔑

Body = quote fields **plus**:

```jsonc
{ "special_requests": "High floor",
  "guest": {                     // optional overrides for the contact record
    "first_name": "…", "last_name": "…", "email": "…", "phone": "*preferred*",
    "address": "", "city": "", "state": "", "country": "Nigeria",
    "identification_type": "NATIONAL_ID", "identification_number": "" } }
```

201 → full **booking detail**:

```jsonc
"data": {
  "id": 15, "booking_reference": "J1-20261015-3F9A2C1D",
  "guest": { "id", "first_name", "last_name", "full_name", "email", "phone",
             "address", "city", "state", "country", "identification_type", "created_at" },
  "room_type_name": "Deluxe Room", "room_type_slug": "deluxe-room",
  "room_assignments": [ { "id", "room_number": "201", "floor": 2, "check_in", "check_out" } ],
  "check_in": "2026-10-15", "check_out": "2026-10-18", "nights": 3,
  "number_of_rooms": 1, "adults": 2, "children": 0, "number_of_guests": 2,
  "price_per_night": "25000.00", "subtotal": "75000.00", "discount_amount": "7500.00",
  "extra_guest_fee_amount": "0.00", "tax_amount": "0.00", "fee_amount": "0.00",
  "total_amount": "67500.00", "required_payment": "67500.00",
  "amount_paid": "0.00", "amount_due": "67500.00", "refund_amount": "0.00",
  "currency": "NGN", "offer_title": "Demo Offer — 10% Off (development only)",
  "status": "PENDING", "payment_status": "UNPAID", "source": "WEBSITE",
  "special_requests": "High floor", "cancellation_reason": "",
  "expires_at": "2026-10-12T14:31:00+01:00",      // pay before this
  "checked_in_at": null, "checked_out_at": null, "cancelled_at": null,
  "created_at": "…", "can_pay": true, "can_cancel": true }
```

`status` ∈ `PENDING` `CONFIRMED` `CHECKED_IN` `CHECKED_OUT` `CANCELLED` `EXPIRED` `NO_SHOW` ·
`payment_status` ∈ `UNPAID` `PARTIALLY_PAID` `PAID` `PARTIALLY_REFUNDED` `REFUNDED` `FAILED`.

Frontend rule of thumb: show **Pay** when `can_pay`, show **Cancel** when
`can_cancel`, show **Expired** state when `status == "EXPIRED"` (even mid-session).

## 13. My bookings — `GET /api/bookings/` 🔑

Rows:
```jsonc
{ "id", "booking_reference", "room_type_name", "room_type_slug",
  "check_in", "check_out", "nights", "number_of_rooms", "number_of_guests",
  "total_amount", "amount_paid", "amount_due", "currency",
  "status", "payment_status", "created_at", "expires_at" }
```
(`?status=CONFIRMED` filter supported, paginated, empty list = `200 []`.)

## 14. Booking detail — `GET /api/bookings/{id or reference}/` 🔑

Same payload as §12. 404 if unknown; 403 if it belongs to someone else.

## 15. Cancel — `POST /api/bookings/{id or reference}/cancel/` 🔑

Body `{ "reason": "optional" }` → 200 with the updated booking (§12 shape) →
`status: "CANCELLED"`. Errors: `CANCELLATION_NOT_ALLOWED`, `INVALID_BOOKING_STATE`.

## 16. Payments

**Initialize** — `POST /api/payments/initialize/` 🔑
`{ "booking_reference": "J1-…" }` → 201:

```jsonc
"data": { "reference": "J1P-20261012-9A1B2C3D4E",
  "booking_reference": "J1-…",
  "authorization_url": "https://checkout.paystack.com/…",   // redirect the guest here
  "access_code": "…", "amount": "67500.00", "currency": "NGN",
  "public_key": "pk_live_…" | null }
```

Then either redirect to `authorization_url` **or** use Paystack Inline/Popup
with `public_key` + `reference` + `amount` (server-verified anyway).

**Verify** — `GET /api/payments/verify/{reference}/` 🔑 (call when Paystack
redirects back to `PAYMENT_CALLBACK_URL`; safe to call repeatedly):

```jsonc
"data": { "payment_reference": "J1P-…", "booking_reference": "J1-…",
  "booking_status": "CONFIRMED", "payment_status": "PAID",
  "amount_paid_this_transaction": "67500.00",
  "booking_amount_paid": "67500.00", "booking_amount_due": "0.00",
  "booking_total": "67500.00", "currency": "NGN", "paid_at": "…" }
```

Failed payment → 400 `PAYMENT_FAILED` with gateway message. **Never trust the
popup's own success hint; only this endpoint (or the webhook) confirms.**

## 17. Receipt — `GET /api/bookings/{id or reference}/receipt/` 🔑

```jsonc
"data": { "hotel": { "name", "address", "phone", "email" },
  "booking_reference", "booking_status", "payment_status",
  "guest": { "name", "email", "phone" },
  "room_type", "rooms", "check_in", "check_out", "nights",
  "subtotal", "discount", "tax", "fees", "total",
  "amount_paid", "amount_due", "currency",
  "payments": [ { "reference", "amount", "status", "provider",
                  "channel", "paid_at" } ] }
```
Render as the confirmation/receipt page.

## 18. Notifications — `GET /api/notifications/` 🔑

```jsonc
"data": { "unread_count": 2,
  "notifications": [ { "id", "type": "BOOKING_CREATED" | "BOOKING_CONFIRMED" |
    "BOOKING_CANCELLED" | "BOOKING_MODIFIED" | "PAYMENT_SUCCESS" | "PAYMENT_FAILED" |
    "CHECK_IN" | "CHECK_OUT" | "ENQUIRY_NEW" | "SYSTEM",
    "title", "message", "link": "/my-booking.html?ref=J1-…",
    "is_read": false, "created_at" } ] }, "pagination": { … }
```

`GET /unread-count/` → `{ unread_count }` (cheap polling) ·
`POST /{id}/read/` and `POST /read-all/` → `{ unread_count }`.
`link` is a frontend-relative path you may route to.

---

# STAFF DASHBOARD (`/api/admin/`)

Requires `role` of RECEPTIONIST/MANAGER/ADMIN. All lists are paginated and
support `search` where it makes sense. Receptionists get identical structures;
manager/admin-only blocks are simply absent (see §19).

## 19. Dashboard — `GET /api/admin/dashboard/`

```jsonc
"data": {
  "today": { "date": "2026-10-12", "arrivals": 4, "departures": 2, "in_house": 8, "no_shows": 0 },
  "rooms": { "total": 9, "occupied": 4, "available": 5, "out_of_order": 0,
             "occupancy_rate_percent": 44.4 },
  "bookings": { "created_today": 3, "pending": 2, "confirmed_upcoming": 11, "cancelled_today": 1 },
  "recent_bookings": [ { "booking_reference", "guest_name", "room_type_name",
      "check_in", "check_out", "status", "payment_status", "total_amount",
      "currency", "created_at" } ],
  "notifications": { "unread_count": 3 },
  // —— only when role is MANAGER or ADMIN ——
  "revenue": { "today": "150000.00", "this_month": "2125000.00",
               "outstanding_total": "90000.00", "outstanding_bookings": 2 },
  "recent_payments": [ { "reference", "booking_reference", "amount", "currency",
      "provider", "channel", "paid_at" } ],
  "alerts": [ { "type": "OVERDUE_CHECKIN" | "LATE_CHECKOUT" | "HOUSEKEEPING",
                "message": "…" } ] }
```

Do not assume `revenue` exists — check.

## 20. Bookings table — `GET /api/admin/bookings/`

Filters: `status`, `payment_status`, `source`, `room_type`, `date_from`,
`date_to`, `check_in`, `check_out` (exact date), `search`, `ordering`
(`created_at`, `check_in`, `check_out`, `total_amount` — prefix `-` desc).

Row (everything the table needs — no per-row requests):

```jsonc
{ "id", "booking_reference", "guest_name", "guest_phone", "guest_email",
  "room_type_name", "room_numbers": ["201"], "check_in", "check_out", "nights",
  "number_of_rooms", "number_of_guests", "total_amount", "amount_paid",
  "amount_due", "currency", "status", "payment_status", "source", "created_at" }
```

**Detail** `GET …/bookings/{id|ref}/` adds: full `guest` object,
`room_assignments`, `adults/children`, price-breakdown fields,
`required_payment`, `refund_amount`, `offer_title`, `special_requests`,
`internal_notes`, lifecycle timestamps.

**Create manual booking** `POST …/bookings/`:

```jsonc
{ "room_type": "deluxe-room", "check_in": "…", "check_out": "…", "rooms": 1,
  "adults": 2, "children": 0, "source": "WALK_IN" | "PHONE",
  "status": "CONFIRMED" | "PENDING", "offer_code": "", "special_requests": "",
  "internal_notes": "", "guest": { "first_name": "*", "last_name": "*",
  "email": "*", "phone": "*", …optional fields… } }
```

**Modify** `PATCH …/bookings/{id|ref}/` — any of `check_in, check_out,
number_of_rooms, adults, children, special_requests, internal_notes`
(re-availability + re-priced automatically; returns updated detail).

**Actions** (POST, body `{}` or `{ "reason": "…" }`, checkout also accepts
`{ "allow_balance_due": false }`):

| Endpoint | Result state | Guards |
|---|---|---|
| `…/confirm/` | CONFIRMED | only PENDING |
| `…/cancel/` | CANCELLED | audited |
| `…/check-in/` | CHECKED_IN, rooms OCCUPIED | CONFIRMED + date reached |
| `…/check-out/` | CHECKED_OUT, rooms AVAILABLE+DIRTY | balance settled or override |
| `…/no-show/` | NO_SHOW | past check-in date |
| `…/assign-room/` | `{ assignment_id, room_number }` | type match, no overlap |

## 21. Guests — `GET /api/admin/guests/` · `GET/PATCH /api/admin/guests/{id}/`

List rows: `{ id, first_name, last_name, full_name, email, phone, city, state,
country, bookings_count, last_booking_at, created_at }` (`?search=`).
Detail adds address and `bookings[]` (last 15 stays). PATCH accepts contact +
identification fields.

## 22. Payments — `GET /api/admin/payments/` · `GET …/payments/{id|ref}/` · `POST …/payments/record/`

Row: `{ id, reference, booking_reference, guest_name, staff_email, provider:
PAYSTACK|CASH|POS|BANK_TRANSFER, amount, currency, status: PENDING|SUCCESS|
FAILED|REFUNDED, channel, gateway_response, transaction_id, paid_at, notes,
created_at }` — filters `status, provider, date, date_from, date_to, paid_on, search`.

Record offline payment:

```jsonc
POST { "booking_reference": "J1-…", "amount": "15000.00",
       "provider": "CASH" | "POS" | "BANK_TRANSFER", "notes": "…" }
→ 201 payment row. (Over-balance → 400; confirms booking when deposit covered.)
```

## 23. Rooms & room types (staff)

* `GET/POST /api/admin/rooms/` · `GET/PATCH/DELETE /api/admin/rooms/{id}/`
  Row: `{ id, room_number, room_type, room_type_name, room_type_slug, floor,
  status, housekeeping_status, notes, is_active, created_at, updated_at }`
  (`status`: AVAILABLE/OCCUPIED/RESERVED/MAINTENANCE/OUT_OF_SERVICE ·
  `housekeeping_status`: CLEAN/DIRTY/CLEANING). Filters: `status`,
  `housekeeping_status`, `room_type`, `is_active`, `search`. **DELETE
  deactivates** (soft). Writes need MANAGER/ADMIN.
* `GET/POST /api/admin/room-types/` · `GET/PATCH/DELETE …/{id}/` — full type
  incl. pricing/capacity/policies + `amenity_ids[]` + `images[]` + `room_count`.
  DELETE deactivates.
* `POST /api/admin/room-types/{id}/images/` — **multipart/form-data**:
  `image*` (jpg/png/webp ≤5MB), `alt_text`, `caption`, `display_order`,
  `is_primary` → 201 image row. `PATCH/DELETE /api/admin/room-images/{id}/`.
* `GET/POST/PATCH/DELETE /api/admin/amenities/…` — `{ id, name, slug, icon, is_active }`.

## 24. Content management

* `GET/POST /api/admin/facilities/…` `{ id, name, slug, description, icon, image_url, is_active, display_order }`
* `GET/POST /api/admin/policies/…` `{ id, key, title, content, is_active, display_order }`
* `GET/POST /api/admin/offers/…` `{ id, title, slug, description, short_description, code, discount_type, discount_value, start_date, end_date, min_nights, max_nights, room_type_ids[], is_active, is_featured, image/image_url, terms }` — dates/percent/stay rules validated with `VALIDATION_ERROR`.
* `GET/POST /api/admin/gallery/…` (`POST` multipart with `image`) `{ id, title, description, category, alt_text, image/image_url, display_order, is_active }` · filter `category`, `is_active`.
* `GET/PATCH /api/admin/settings/` — GET manager+, PATCH **ADMIN-only**:
  ```jsonc
  { "hotel_name", "tagline", "description", "address", "city", "state",
    "country", "phone", "email", "google_maps_url", "social_links",
    "check_in_time", "check_out_time", "min_stay_nights", "max_stay_nights",
    "currency", "tax_rate_percent", "service_fee", "deposit_percent",
    "pending_booking_minutes", "cancellation_deadline_hours",
    "cancellation_fee_percent", "updated_at" }
  ```

## 25. Enquiries — `GET /api/admin/enquiries/` · `GET/PATCH …/{id}/`

`{ id, name, email, phone, subject, message, status: NEW|IN_PROGRESS|RESOLVED|CLOSED, internal_notes, created_at, updated_at }` — PATCH only `status`/`internal_notes`. Filters `status`, `search`.

## 26. Reports (MANAGER+) — `?start_date&end_date` (YYYY-MM-DD, ≤ 366 days)

**Revenue** `GET /api/admin/reports/revenue/`:
```jsonc
{ "start_date", "end_date", "currency": "NGN", "grand_total": "2125000.00",
  "transactions": 41, "refunds": { "total": "15000.00", "count": 1 },
  "by_day": [ { "date", "total", "transactions" } ],
  "by_provider": [ { "provider", "total", "transactions" } ] }
```

**Occupancy** `GET /api/admin/reports/occupancy/`:
```jsonc
{ "start_date", "end_date", "days": 7, "active_rooms": 9,
  "occupied_room_nights": 38, "available_room_nights": 63,
  "average_occupancy_percent": 60.3,
  "by_day": [ { "date", "occupied_rooms": 6, "occupancy_rate_percent": 66.7 } ] }
```

**Bookings** `GET /api/admin/reports/bookings/`:
```jsonc
{ "total_bookings": 25, "cancelled": 3, "no_shows": 1,
  "cancellation_rate_percent": 12.0,
  "by_status": [ { "status", "count" } ],
  "by_payment_status": [ { "payment_status", "count" } ],
  "by_room_type": [ { "room_type", "bookings", "revenue" } ] }
```

## 27. User administration (ADMIN only) — `GET/POST /api/admin/users/` · `GET/PATCH …/{id}/`

List rows: `{ id, email, first_name, last_name, full_name, phone, role,
is_active, email_verified, bookings_count, date_joined, last_login }`
(filters `role`, `is_active`, `search`, `ordering`).
Create: `{ email, first_name, last_name, phone, role, password, is_active }`.
Patch: any of `first_name, last_name, phone, role, is_active, email_verified`
(self-lockout/demotion refused; role changes are audited).

## 28. Audit logs (ADMIN, read-only) — `GET /api/admin/audit-logs/` · `.../{id}/`

`{ id, actor_email, actor_name, action, object_type, object_id, summary,
changes: { field: [old, new] }, metadata: {…}, ip_address, created_at }` —
filters `action`, `object_type`, `actor`, `date_from`, `date_to`.
Actions emitted today: `USER_CREATED` `USER_UPDATED` `USER_ROLE_CHANGED`
`SETTINGS_CHANGED` `BOOKING_CREATED` `BOOKING_MODIFIED` `BOOKING_CONFIRMED`
`BOOKING_CANCELLED` `BOOKING_EXPIRED` `CHECK_IN` `CHECK_OUT` `NO_SHOW`
`ROOM_ASSIGNED` `PAYMENT_INITIALIZED` `PAYMENT_VERIFIED` `PAYMENT_RECORDED`
`ROOM_CREATED/UPDATED/DEACTIVATED` `ROOMTYPE_* (CREATED/UPDATED/DEACTIVATED/IMAGE_ADDED/IMAGE_REMOVED)`
`AMENITY_*` `FACILITY_*` `HOTELPOLICY_*` `GALLERYITEM_*` `OFFER_CREATED/UPDATED`
`ENQUIRY_STATUS_CHANGED` `GUEST_UPDATED`.

---

# Contract change control

* Additive changes (new fields/endpoints) may ship after a note here;
  frontend must tolerate unknown fields.
* Renames/removals/meaning changes require a coordinated frontend deploy and a version note here.
* The single source of truth for machine-readable structure is `/api/schema/`;
  for human behavior, this file.
