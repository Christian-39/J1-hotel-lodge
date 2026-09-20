# J1 Hotel & Lodge — 30-task implementation report

Every change extends the systems that were already in the repo. No model,
endpoint, page or helper was duplicated, no frontend framework was added, and
multi-room booking, Paystack verification, receipts, email and authentication
were left working exactly as they were.

**Verification at time of writing**

| Suite | Result |
|---|---|
| Backend `python manage.py test` (whole suite, not just new tests) | **552 passed**, 1 skipped |
| Frontend `node --test tests-js/` | **43 passed** |
| `frontend/validate.py` | ALL OK — 54 HTML files, 22 JS files |
| `makemigrations --check` | No changes detected |
| Browser pass (Chromium, desktop 1280/1440 + mobile 390) | 0 page errors, 0 console errors, no horizontal overflow |

---

## The money rule (read this first)

The backend is the only thing that decides an amount. `apps/bookings/services/pricing.py`
`calculate_quote()` computes one discount and the frontend only ever displays it.

**A public offer and a personal guest discount are never added together — the
larger of the two is applied.** A tie goes to the public offer. Verified live:

| Scenario (subtotal ₦135,000, offer = ₦12,000 fixed) | Discount applied | Source |
|---|---|---|
| No guest discount | ₦12,000 | `OFFER` |
| Guest discount ₦5,000 (smaller) | ₦12,000 | `OFFER` |
| Guest discount 40% = ₦54,000 (larger) | ₦54,000 | `GUEST_DISCOUNT` |

Stacking the last row would have produced ₦66,000; it produces ₦54,000.

The amount sent to Paystack derives from this same quote, so the gateway can
never be asked for a figure the backend did not authorise.

---

## Tasks

### 1–3 · Offers

* **Root cause of the broken public offers page:** `Offer.code` is
  `unique=True, null=True`. The form submitted an empty string, so a *second*
  code-less offer collided on `""` and creation died with a 500. `Offer.save()`
  now coerces a blank code to `NULL` and the serializer validates it. The
  public endpoint and its permissions were never broken.
* The homepage shows the **latest** current offer above the rooms section,
  chosen by newest `start_date`.
* **Start dates are now shown everywhere** — `offerPeriod()` / `offerStatusNote()`
  in `js/utils.js` render "Valid 19 Sept 2026 – 19 Dec 2026" on the homepage,
  the public offers page and the staff offers table.

### 4 · Individual guest discounts

Two new models in the existing offers app:

* `GuestDiscount` — the reusable rule (percentage or fixed, validity window,
  reason, active flag).
* `GuestDiscountApplication` — an **immutable per-booking snapshot** of what was
  actually applied, so editing or withdrawing a discount never rewrites the
  amount on a booking that already happened.

Managed from the Guests page (per-row **Discount** button → add / withdraw),
the API at `/api/admin/guest-discounts/`, and Django admin. `DELETE`
deactivates rather than destroys, preserving history.

### 5 · Occupancy calendar (`dashboard/occupancy.html`)

Month grid built from the authoritative `BookingRoom` assignment rows, so a
multi-room booking contributes every one of its rooms. Each date shows compact
room-number chips colour-coded Confirmed / In house / Departed with an
"N rooms" footer; selecting a date opens a modal listing guest, booking
reference, stay dates and status per room. On a phone the grid becomes a day
list that carries its own weekday label.

### 6 + 13 · Missed / no-show bookings (`dashboard/missed-bookings.html`)

A booking appears once its arrival day has passed with no check-in. Each row
offers **mark no-show**, **refund** and **reschedule**. Refund routes into the
existing cancellation workflow (so the fee and the Paystack refund record stay
in one place) and shows the real figures — e.g. paid ₦45,000, fee ₦4,500,
refundable ₦40,500. Reschedule re-checks availability and re-prices through the
booking system, keeping the same booking and its payments, and is
manager/admin only.

### 7–8 · Pagination, 10 per page

`StandardPagination.page_size` 20 → 10, `PAGE_SIZE: 10` in `js/config.js`, and
the ten hardcoded `page_size: 20` call sites across nine dashboard pages now
read from config. The mobile bug was a real rule —
`@media (max-width:640px){ .pagination .page-nums{display:none} }` — which
deleted the page numbers on phones. Page numbers are now shown on mobile, with
a scrolling strip below 380px.

### 9–10 · Guests table

Rebuilt as labelled cards on mobile (no squeezed columns, no clipped email) and
each guest shows a **booking count** annotated in SQL. Counts exclude
`CANCELLED` and `EXPIRED`.

### 11 · Cancellation fee actually deducted

`initiate_cancellation_refund` recomputes the policy at submission time so the
fee cannot be bypassed by a stale figure. Fee = `amount_paid ×
cancellation_fee_percent / 100`; refund = `amount_paid − fee`. A second refund
attempt returns 400 `PAYMENT_FAILED`. Covered by `tests/test_refund_cancellation_fee.py`.

### 12 · Availability search on mobile

The filter row became a real `<form>` with a submit handler, so the on-screen
keyboard's Go key works and the fields stack legibly. Results keep all six
columns and scroll inside their own wrapper.

### 14–16 · Payments

* Table scrolls sideways **inside its own region** (`role="region"`, focusable
  for keyboard users) — never the whole page.
* The **guest name** is shown under the payment reference, which is what was
  missing on mobile.
* A **View** button opens a full payment detail panel (amount, method, channel,
  status, transaction id, who recorded it, gateway response, notes).

### 17 · No "Record Payment" on a settled payment

The button is hidden for `PAID` / `REFUNDED` bookings and when nothing is due —
and, because the UI is not a security boundary, `record_offline_payment()` now
**rejects** a payment against a booking whose payment record is `PAID`,
`REFUNDED` or `PARTIALLY_REFUNDED` with 409 `PAYMENT_ALREADY_COMPLETED`. This
also closes the case where a refund leaves a balance technically "due" again.

### 22 · Audit logging

Reschedules and all three guest-discount operations are written to the existing
`AuditLog` (`BOOKING_RESCHEDULED`, `GUEST_DISCOUNT_CREATED` / `_UPDATED` /
`_DEACTIVATED`) with actor, IP and a human summary.

The dashboard's action filter was a hand-maintained `<option>` list that had
already gone stale: it offered three actions the backend never logs and was
missing twenty it does. It is now populated from
`GET /api/admin/audit-logs/actions/` (admin only), which returns the distinct
actions actually recorded — so it can never drift again.

### 23 · Role permissions

Pinned in `tests/test_role_permissions_matrix.py`:

| Surface | Receptionist | Manager | Admin | Guest |
|---|---|---|---|---|
| Guest discounts — read | ✅ | ✅ | ✅ | ❌ |
| Guest discounts — write | ❌ | ✅ | ✅ | ❌ |
| Reschedule | ❌ | ✅ | ✅ | ❌ |
| Occupancy / missed bookings | ✅ | ✅ | ✅ | ❌ |
| Audit log | ❌ | ❌ | ✅ | ❌ |

### 24 · Query efficiency

`tests/test_query_efficiency.py` asserts the query count is **identical with 2
rows and with 10** for the guests list, occupancy calendar, missed bookings and
guest discounts — the only way to actually catch an N+1. All four are flat
(booking counts are annotated; the calendar is one `select_related` query
fanned out in memory).

### 25 · Migrations

One migration,
`offers/0002_guestdiscount_guestdiscountapplication_and_more.py`, additive only.
`makemigrations --check` is clean.

### 26 · Error handling

`tests/test_error_contract.py` pins the envelope
(`success:false` + stable `code` + per-field `errors`) for bad months and years
on the calendar, missing/reversed/malformed reschedule dates, unknown bookings,
percentages over 100, zero and negative discounts, reversed discount windows,
unknown guests, invalid types, a missing reason, and out-of-range pages. No
input produced a 500.

### 27–30 · Tests and docs

New backend files: `test_guest_discounts.py`, `test_occupancy_and_missed.py`,
`test_refund_cancellation_fee.py`, `test_audit_actions.py`,
`test_query_efficiency.py`, `test_role_permissions_matrix.py`,
`test_error_contract.py`, plus additions to `test_payments.py` and
`test_admin_list_pagination.py`. New frontend file:
`tests-js/test-offers-and-payments-ui.js`. The **entire** existing suite was run
after every change, not just the new tests.

---

## Layout defects found by looking at the running app

Screenshots at 1280, 1440 and 390 px surfaced four problems the tests could not:

1. Occupancy month navigation wrapped onto three lines → `.cal-nav` is now
   `nowrap` with a fixed-width month input.
2. The missed-bookings table overflowed its wrapper (1294px inside 966px),
   stacking the action buttons vertically. Fixed by sizing the Actions column,
   keeping guest/status on one line, letting stay dates wrap below 1300px, and
   showing button labels only at ≥1400px (icon-only below, with `title` and
   `aria-label` on every button). Now 968px in a 966px wrap.
3. Mobile card rows were `width:100%` *and* had side margins, so every card
   table overflowed by exactly the margin — a phantom sideways scroll on
   guests, missed bookings and staff. Cards are now auto-width.
4. Icon `<span>`s inside flex row-action buttons collapsed to 0px wide, so
   mobile action buttons showed no icons. Fixed with `flex: 0 0 auto`.

No blanket `overflow-x: hidden` was used anywhere, and no emoji icons were
introduced — icons come from the existing `js/icons.js` SVG set.

---

## Running it locally

```bash
# backend
cd backend && python manage.py migrate --settings=config.settings.development
python manage.py runserver 0.0.0.0:8000 --settings=config.settings.development

# frontend (proxies /api/ and /media/ to :8000)
cd frontend && python dev_server.py 5500 http://127.0.0.1:8000
```
