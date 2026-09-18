# Fix report — multi-room quantity, payment auto-continue, mobile room cards

Scope: three reported issues, fixed with the smallest production-quality changes.
No redesign, no new architecture, no removed tests or security mechanisms.

**4 files changed (85 insertions), 2 test files added.** Baseline 444 backend tests still pass.

---

## Issue 1 — multi-room quantity inconsistency

### Root cause (proven, not inferred)

**The backend was already completely correct.** A pre-fix end-to-end run sent
`rooms: 2` and produced this row:

```
J1-20260918-39CA4C91 | PENDING | number_of_rooms: 2 | total: 120000.00 | assignments: ['101','102']
```

So the defect was display-only, in two frontend layers:

1. **Wrong key path against the quote API.** `booking.html` read
   `data.pricing.total`, but `POST /api/bookings/quote/` returns its fields
   **flat on `data`** (`total`, `rooms`, `nights`, …) and has **no `pricing`
   key**. `total` was therefore `undefined`, and `refreshEstimate` hit an early
   `if (!total) return;` — silently leaving the stale **1-room ₦60,000** on
   screen while the backend charged the correct ₦120,000.
   (`GET /api/rooms/availability/` *does* carry a nested `pricing`, but always
   for `rooms: 1` — the two shapes had been conflated.)

2. **The card `<label>` stole the click.** `.room-option` is a `<label>` with no
   `for` attribute, so its *labelled control* is the **first labelable
   descendant** — the quantity **“−” button**, not the radio. Every click on the
   card fired a phantom “one fewer room”, resetting a 2-room pick back to 1.
   This is what broke refresh and back-navigation: the deep-link auto-select
   re-clicked the card and immediately decremented the restored quantity.

A third, latent bug was found while tracing: `booking-confirmation.html`'s
resume guard compared `Number(prior.rooms || 1)`, but `prior` is the stored
backend booking whose field is `number_of_rooms`. Every saved multi-room booking
looked like a 1-room one, the guard never matched, and a **second booking
(double inventory hold)** was created on resume.

### Changes

- `frontend/booking.html`
  - read the **flat** `data.total`; drop a late reply whose `data.rooms` no
    longer matches the requested quantity;
  - quote **per card** (`scheduleQuote(opt, qty)` / `refreshEstimate(opt, qty)`)
    and update that card's own total line (`data-total-line`, `setCardTotal`),
    so a 2-room card never keeps showing the 1-room search price;
  - bind each card label to its own radio (`for` / `id="room-choice-N"`) so
    selecting a room no longer decrements its quantity;
  - honest error text (“Not available for these dates” / “Total confirmed at
    next step”) instead of a stale single-room price.
- `frontend/booking-confirmation.html` — resume guard reads `number_of_rooms`.

No client-side price maths was introduced: every total shown is a backend quote.

---

## Issue 2 — Paystack success now auto-continues to Step 6

`frontend/payment-verify.html`, inside the **already backend-verified**
`transaction_status === "success"` branch only: `location.replace(...)` to the
existing `booking-confirmation.html?ref=…`, reusing the existing route, stepper
and guest-access-token convention. `replace` keeps the spent verification URL
out of history. The success panel stays as a fallback.

Untouched: reference/amount validation, idempotency, webhook protection, and
every failure/pending path. A `?reference=` URL parameter is still never treated
as proof of payment, and the receipt still works (verified on Step 6 with both
room numbers rendered).

---

## Issue 3 — mobile room-card overflow

### Root cause

At 390px the card measured **435.8px**. `.room-option` used
`grid-template-columns: 1fr`, and `1fr` means `minmax(auto, 1fr)` — the track
floor is the content's **min-content** width. The price/actions row
(`.room-option-price`, min-content 378.6–401.8px with `flex-wrap: nowrap`:
price 89.7 + caption 66.2 + stepper 133.2 + Select 72.8) could not shrink, so it
forced the whole card past the viewport.

### Change

`frontend/css/booking.css`, **inside the existing `@media (max-width: 640px)`
block only**: `minmax(0, 1fr)` track, `min-width: 0` on the shrinkable children,
`flex-wrap: wrap` + `overflow-wrap: anywhere` for long room names.

No `body { overflow-x: hidden }`, no global/header/footer/dashboard CSS touched.
A candidate using `flex-wrap` alone was rejected: it passed only with short copy
and failed at every width against a long unbreakable room name.

---

## Verification

| Suite | Result |
| --- | --- |
| `backend: manage.py test tests` | **454 passed** (444 baseline + 10 new), 1 skipped |
| `frontend/tests-pwa/test_multi_room_ui.py` (new) | **46/46 passed** |
| `frontend: node --test tests-js/` | 32/32 passed |
| `frontend/tests-pwa/test_regression.py` | 85/85 passed |
| `frontend/tests-pwa/test_paystack.py` | 5/5 passed |
| `frontend/validate.py` | 52 HTML + 22 JS — ALL OK |

Live end-to-end (real backend, 390px): card **₦120,000**, review “2 × Superior
Room” ₦120,000, payload `rooms: 2` → `J1-20260918-37FAEA71 | number_of_rooms: 2
| total: 120000.00 | assignments: ['101','102']`, availability then correctly
`0`. Mobile 320/360/375/390/393/414/430 → zero overflow, all controls visible.
Desktop 768/1024/1280/1440 → unchanged (`190px <flex> 136.5px`).

`tests-pwa/test_stickyhdr.py` errors, but **identically on the unmodified
baseline** (verified via `git stash`) — pre-existing and unrelated.

### New tests

- `backend/tests/test_multi_room_quantity_regression.py` — 10 tests: the flat
  quote contract (and the absence of `data.pricing`), quantity scaling, 2 rooms
  recorded/priced/exposed, partial inventory 3→1, full consumption →0,
  insufficient inventory 409 `ROOM_UNAVAILABLE` with no downgrade, server-derived
  payment amount (hostile client amount ignored), verification across all rooms +
  receipt, and the unchanged single-room/default-quantity flows.
- `frontend/tests-pwa/test_multi_room_ui.py` — 46 checks across quantity
  persistence (incl. refresh + back navigation + the label regression), payment
  redirect (success vs failed/pending/abandoned/reversed/404/500), and mobile +
  desktop layout.
