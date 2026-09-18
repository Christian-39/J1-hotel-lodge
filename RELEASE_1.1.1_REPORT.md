# J-ONE HOTEL & LODGE — Release 1.1.1 Technical Report

Production fixes for: pending-booking window enforcement, dashboard table layout,
walk-in/manual receipt truthfulness, and the stale-frontend/update system.
No migrations, no API contract changes, no frameworks added, no tests removed.

---

## 1. Root causes

| Issue | Root cause |
|---|---|
| Pending window not enforced | The setting itself worked (`get_settings()` sets `expires_at` at creation; `HotelSettings.save()` already invalidated `SETTINGS_CACHE_KEY`). The real gaps: expiry was **lazy-only and racy** — no lock around the `EXPIRED` flip, and Paystack verification could confirm a booking *after* its hold expired (webhook/verify checked status, not `expires_at` vs. the provider's `paid_at`). Also `pending_booking_minutes=0` was accepted, creating instantly-dead holds. |
| Ugly dashboard tables | Long atomic values (UUIDs, references, emails) had no `white-space:nowrap`, so cells wrapped to 3–4 lines; audit-log summaries were unbounded. A latent second bug surfaced during testing: absolutely-positioned `.sr-only` spans inside tables escaped `.table-wrap` (which was not a containing block) and widened the **document**, causing page-level horizontal scroll at ≤768px. |
| Manual receipts wrong | Both renderers (JS `receipt.js` and PDF `receipt_pdf.py`) assumed Paystack: they printed a "Session Id" (invented transaction identity) and Paystack-flavored payment-type strings like "CASH / CASH" and "POS TERMINAL / POS" for offline payments, and omitted the staff attribution the backend already stored (`recorded_by`, `notes`). |
| Users stuck on stale frontend (up to 7 days) | Chain of three: (a) `sw.js` intercepted `/version.json` with stale-while-revalidate, so the update checker compared the *cached* manifest against itself; (b) no CDN `no-store` header on `/version.json` (Vercel default caching); (c) update-checker suppressed the modal on **all** dashboard pages, and its "refresh" was a plain `location.reload()` that never activated the waiting service worker — the old worker's caches served the old assets right back. |

## 2. Files modified and why

### Backend (5)
- `apps/bookings/services/booking_service.py` — `expire_pending_booking` takes a row
  lock and re-checks `is_expired_pending` inside it (idempotent; backs off if
  concurrently confirmed); throttled lazy sweep via
  `cache.add("bookings:lazy-expiry-sweep", 60s)`; `register_successful_payment`
  clears `expires_at`.
- `apps/bookings/views_admin.py` — admin bookings list triggers the sweep so
  staff always see truthful statuses.
- `apps/payments/services/payment_service.py` — `process_verification` compares
  provider `paid_at` against `booking.expires_at` under the booking lock:
  charged within the hold → confirm (even if verification arrives late);
  charged after expiry → rejected, never SUCCESS. `record_offline_payment`
  made atomic.
- `apps/bookings/services/receipt_pdf.py` — `_is_paystack` gate
  (transaction/session row only for Paystack); "Recorded By"/"Notes" rows for
  offline payments; payment-type dedupe drops the channel when its normalized
  form is a substring of the provider ("POS TERMINAL / POS" → "POS TERMINAL").
- `apps/hotel/serializers.py` — `validate_pending_booking_minutes` rejects
  values < 1 (validation, not schema — no migration).

### Frontend (production)
- `js/update-checker.js` — dashboard pages now get the update modal; only
  genuinely critical states (active Paystack flow, dirty form) defer, with a
  30-second retry; "Refresh now" routes through `JONE.pwa.refreshToLatest`.
- `js/pwa.js` — new exported `refreshToLatest(cb)`: posts SKIP_WAITING to a
  waiting SW, reloads on `controllerchange`, plain-reload fallback.
- `sw.js` — never intercepts `/version.json`; cache name `jone-v1.1.1`
  (stamped by build.py).
- `vercel.json` — `Cache-Control: no-store` (+ `CDN-Cache-Control`) for
  `/version.json`.
- `css/dashboard.css` — `.cell-nowrap`; `.cell-clamp` (34ch/22ch, full value in
  `title` + details link); `.table-wrap { position: relative }` so positioned
  children cannot widen the page.
- `dashboard/{bookings,payments,audit-logs,receipts}.html` — row builders apply
  the new cell classes.
- `js/receipt.js` — mirror of the PDF changes: `isPaystack` gate, gated
  Session Id, Recorded By/Notes rows, identical payment-type dedupe.
- All 52 HTML pages restamped `?v=1.1.1` by `frontend/build.py --bump patch`
  (no manual edits; also fixed previously-unstamped `site-images.js`).

### Tests (extended; none removed)
- `backend/tests/test_pending_window.py` — new, 11 tests.
- `backend/tests/test_manual_receipts.py` — new, 5 tests.
- `frontend/tests-js/test-update-checker.js` — extended 17 → 19 tests.
- `frontend/tests-pwa/test_tables_and_update.py` — new Playwright suite,
  62 checks (tables at 1280/768/390/320 px with extreme data + update flow).

## 3. Pending-window behavior

`HotelSettings.pending_booking_minutes` is read at booking creation (server
time) to set `Booking.expires_at` — the **single** inventory-hold source of
truth; there is no separate payment timer. A PATCH takes effect immediately
(model `save()` deletes the settings cache) and applies only to bookings
created afterwards; existing holds are never moved. Expiry is lazy +
throttled-sweep, lock-protected and idempotent: an unpaid pending booking past
`expires_at` flips to `EXPIRED` (hold released; existing state preserved). The
race with Paystack is settled by the provider's charge timestamp: paid within
the hold ⇒ confirms even if verification arrives late; charged after expiry ⇒
verification rejects it. An expired booking can never confirm; an
authoritatively-paid booking can never expire.

## 4. Receipt unification

Walk-in/manual receipts already flowed through the same `ReceiptSerializer` +
shared `JONE.receipts` renderer; the fix was truthfulness, in exact lockstep
between `receipt.js` and `receipt_pdf.py`: Paystack-only fields (Session Id /
transaction ref) are gated behind an explicit provider check; offline receipts
instead show "Recorded By" (staff email) and "Notes"; payment-type labels
deduplicate provider/channel. Same branding, structure, and export paths
(print / PDF / image / share / email) for every payment method; all totals,
nights, and balances remain backend-computed.

## 5. Cache / update mechanism

HTML is network-first; static assets stay aggressively cached under versioned
`?v=` stamps and the versioned SW cache (`jone-v1.1.1`) — caching was **not**
disabled. `/version.json` is triple-protected against staleness (SW never
intercepts it, CDN `no-store`, page fetch `cache:"no-store"`). The
update-checker compares deployed vs. loaded version and shows the existing
modal — now on dashboards too; Paystack/dirty-form states defer with a 30 s
retry, never a forced reload. "Refresh now" activates the waiting SW
(SKIP_WAITING → `controllerchange`) *before* reloading; old caches are purged
on activate, so the click genuinely lands on the new release — including
installed PWAs. Storage (tokens, session, drafts, theme) is untouched. Update
failures degrade silently; API responses remain network-only. Releases are cut
with `frontend/build.py --bump`, which stamps all 52 pages, `sw.js`,
`version.json` and `js/version.js` in one command.

## 6. Tests run + results (all passing)

| Suite | Result |
|---|---|
| Full backend `manage.py test tests` | **422 OK / 1 skip** (baseline 406; +16 new, zero regressions) |
| `test_pending_window.py` (new) | 11/11 |
| `test_manual_receipts.py` (new) | 5/5 |
| `node --test tests-js/` | 19/19 |
| `frontend/validate.py` | ALL OK (52 HTML, 22 JS) |
| Playwright `test_update.py` (SW lifecycle) | 6/6 |
| Playwright `test_pwa` / `test_regression` / `test_sticky` / `test_stickyhdr` | 153/153, 85/85, 21/21, 64/64 |
| Playwright `test_tables_and_update.py` (new) | **62/62** — no page hscroll on bookings/payments/audit-logs at 1280/768/390/320 px with extreme data; scroll confined to `.table-wrap`; public + dashboard update modal; real reload on "Refresh now"; storage intact after refresh; dirty-form deferral |

## 7. Regression confirmation

The 406 baseline backend tests, all 17 original JS tests, and all 329
pre-existing Playwright checks pass unchanged. Paystack config, email,
calendar/availability, auth/JWT, notifications, check-in/out, refunds,
permissions, gallery, offers, reports, and audit logging were not touched.
No migrations, no API contract changes, no framework additions, no test
removals, no placeholders/TODOs/debug logging in shipped code. One latent
pre-existing bug was fixed only because it was inside scope (table layout):
the `.sr-only`-escapes-`.table-wrap` document-overflow issue.
