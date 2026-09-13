# Booking & Payment Flow

This is the end-to-end flow the frontend implements. The backend is the source
of truth at every step; the frontend only displays and submits.

```
 1  Guest picks dates                       (frontend form)
 2  GET  /api/rooms/availability/     ──▶   room types, available counts, live prices
 3  Guest picks room type + quantity
 4  POST /api/bookings/quote/         ──▶   authoritative review: nights, subtotal,
                                            offer/discount, tax, fees, total,
                                            required payment, policies, hold time
 5  Guest enters guest details (login/register anywhere before or during)
 6  POST /api/bookings/               ──▶   201 booking PENDING + inventory held
                                            (expires_at = now + pending_booking_minutes)
 7  POST /api/payments/initialize/    ──▶   Paystack authorization_url + reference
 8  Guest pays on Paystack checkout
 9  Paystack redirects to PAYMENT_CALLBACK_URL?reference=J1P-...
10  GET  /api/payments/verify/<ref>/  ──▶   server-verified result
      (independently, Paystack calls POST /api/payments/webhook/ — same code path)
11  Booking CONFIRMED once verified money covers required_payment
12  GET  /api/bookings/<ref>/receipt/ ──▶   receipt & confirmation screen data
```

## Happy-path status transitions

```
NO BOOKING
   │  POST /api/bookings/
   ▼
PENDING  ←── inventory HELD until expires_at (default 15 min — settings)
   │  payment verified (required_payment covered)
   ▼
CONFIRMED ──── staff terminal ───► CHECKED_IN ───► CHECKED_OUT
```

## Failure & edge states (and their machine codes)

| Situation | Result | Code | Where it appears |
|---|---|---|---|
| Bad/inverted/past dates | 400 | `INVALID_DATES` | availability, quote, book |
| Guests exceed capacity | 400 | `CAPACITY_EXCEEDED` | quote, book |
| Rooms sold out / race lost | 409 | `ROOM_UNAVAILABLE` | book, check-in, assign-room |
| Booking hold expired before paying | 409 | `BOOKING_EXPIRED` | payment initialize |
| Already fully paid | 409 | `PAYMENT_ALREADY_COMPLETED` | payment initialize |
| Paystack not configured | 503 | `PAYMENT_NOT_CONFIGURED` | payment initialize |
| Paystack says "failed"/declined | 400 | `PAYMENT_FAILED` | verify |
| Amount/currency mismatch (fraud guard) | 400 | `PAYMENT_AMOUNT_MISMATCH` | verify, webhook |
| Gateway unreachable | 502 | `PAYMENT_GATEWAY_ERROR` | initialize, verify |
| Too late to cancel (deadline passed) | 400 | `CANCELLATION_NOT_ALLOWED` | guest cancel |
| Balance due at checkout | 400 | `OUTSTANDING_BALANCE` | staff checkout (override flag exists) |
| Wrong state for an action | 409 | `INVALID_BOOKING_STATE` | confirm/cancel/check-in/out/no-show |
| Frontend retried after success | 200, same result | — | verify, check-in, check-out (idempotent) |

## Expiration lifecycle

```
PENDING created → holds rooms for pending_booking_minutes (default 15, settings)
   │ no payment in time
   ▼
EXPIRED (Celery beat every 5 min, plus lazy flip on any read/search)
   ▼
Held rooms AUTOMATICALLY become available again — no staff action needed.
```

Availability counting **always** ignores dead holds, so inventory is truthful
between beat runs as well.

## Deposits

`deposit_percent` (settings) decides how much must be paid online to confirm:

* `100` → full prepayment (default) → booking confirms on a single payment.
* `<100` → booking confirms once the deposit is verified; the balance is due
  at the hotel (front desk records CASH/POS/BANK_TRANSFER via
  `/api/admin/payments/record/`) — one code path for all money.

## Cancellations & refunds

* Guests cancel while (check-in − `cancellation_deadline_hours`) is still in
  the future; `cancellation_fee_percent` of the paid amount is retained and
  the remainder is marked as refund due (`payment_status` →
  `PARTIALLY_REFUNDED`/`REFUNDED`, `refund_amount` set, staff notified).
  Actual money is returned from the Paystack dashboard — the system tracks,
  staff executes (deliberate human control over refunds).
* Staff can cancel at any time pre-stay; every cancellation is audited and
  releases the held rooms immediately.

## Direct-booking (walk-in / phone)

Staff create bookings via `POST /api/admin/bookings/` with mandatory guest
fields. `status=CONFIRMED` skips the online-payment hold entirely (guest pays
at the hotel); `status=PENDING` keeps an expiry hold like a web booking.

## Account-free guest access

The public flow never redirects a guest to staff login. After checkout, the
backend returns a secure guest access token and emails a link containing it.
The token is stored only in the browser session for the payment redirect and
is required alongside the booking reference for later lookup. Receipts use
the official J-ONE watermark in both browser and print/PDF views.
