# J-ONE HOTEL & LODGE — Update Report

Three targeted updates to the working system: (1) real server-side pagination
for the growable dashboard lists, (2) multi-room booking of the same room
type, (3) a collapsible desktop dashboard sidebar. Nothing else was touched;
all 444 backend tests and 33 frontend tests pass.

---

## 1. Files modified / added

**Modified**

| File | Why |
|---|---|
| `backend/apps/notifications/views.py` | `EmailLogListView`: explicit `pagination_class = StandardPagination` (was relying on the global default for an unbounded, staff-filterable log list). |
| `frontend/booking.html` | Multi-room: renders `available_rooms` per room-type card, per-card quantity stepper (1…available_rooms, disabled at bounds), quantity persisted in the booking draft + URL to review, availability search kept at the 1-room baseline on purpose (documented inline). |
| `frontend/css/components.css` | `.pagination` control styles extended (range text `aria-live`, `.page-ellipsis`, disabled/current states, dark-mode + mobile compact). |
| `frontend/css/dashboard.css` | Desktop collapse block — **all rules gated behind `@media (min-width: 1025px)`**: `body[data-sidebar="collapsed"]` grid → 76px, icon-only nav, hidden group labels. |
| `frontend/css/booking.css` | Multi-room quantity stepper / availability-line styles (`.room-qty*`, `.room-option-avail*`). |
| `frontend/js/booking-stepper.js` | `rooms` included in back-navigation criteria URLs so the quantity survives stepper round-trips. |
| `frontend/js/dashboard.js` | `renderPagination` / `paginationHTML` (one shared component) + `setupSidebarCollapse` injected from the existing `setupSidebar` (single manager, one delegated listener, no per-page edits). |
| `frontend/dashboard/*.html` | List pages adopt the shared pager: bookings, guests, payments, receipts, audit-logs, staff, enquiries, notifications, reviews — all request `page/page_size: 20`, render via `JONE.dashboard.renderPagination`, and reset `page=1` whenever a filter/search/sort changes (sort/page changes preserve filters). |
| `frontend/booking-review.html` / `booking-confirmation.html` | Multi-room hand-off complete: `rooms` parsed from URL/draft, shown as `N × Room Type`, quote + createBooking send the actual quantity; exact-room deep links (`?room_id=` / `?room_no=`) force `rooms=1`. |

**Added (tests)**

| File | Contents |
|---|---|
| `backend/tests/test_multi_room_booking.py` | 6 tests — the five 5-room scenarios + threaded race (below). |
| `backend/tests/test_admin_list_pagination.py` | 16 tests — pagination contract for admin Bookings / Payments / Audit Logs / Guests. |
| `frontend/tests-js/test-sidebar-collapse.js` | 5 tests — sidebar collapse state mappers (pref parse, toggle, a11y copy). |
| `frontend/tests-js/test-pagination.js` | 8 tests — pager contract (`paginationHTML` empty on single page, range text, `aria-current`, envelope + normalizeList shapes). |

Schema: **no migration needed** — `Booking.number_of_rooms` / `BookingRoom`
already model multi-room bookings; only frontend tests and wiring changed.

---

## 2. Pagination details

- **One backend paginator, reused**: the existing
  `backend/apps/core/pagination.py::StandardPagination` (default `page_size=20`,
  `?page_size=` param honoured up to max 100) unchanged. Envelope contract
  `{success, message, data, pagination:{count,page,page_size,total_pages,next,previous}}`.
  Out-of-range pages return a clean 404 JSON, not a 500.
- **One frontend component, reused**: `JONE.dashboard.paginationHTML(meta)` /
  `renderPagination(el, meta, cb)` in `js/dashboard.js` — Prev/Next + compact
  page numbers (`1 … 5 6 7 … 20`, `.page-ellipsis`), "Showing 21–40 of 137"
  (`aria-live="polite"`), disabled/current (`aria-current="page"`), keyboard-/
  touch-friendly buttons, dark-mode- and mobile-safe CSS.
- **Server-side everywhere** — each list fetches `{page, page_size:20}` from the
  API; no page downloads 500 rows and hides 20. `normalizeList(payload,
  pagination)` in `js/api.js` returns `{items, count, next, previous, page,
  pageSize, totalPages}` and copes with both envelope and DRF-list shapes.
- **State rules**: any filter/search/sort change resets `page=1`; page changes
  carry the current filters/search/sort. Server-side operational searching is
  preserved (query params, not client filters).
- **Coverage**:
  - Paginated: Bookings, Guests, Payments, Receipts (paginates the underlying
    `status=SUCCESS` payments query — no duplicate receipt store), Audit Logs,
    Staff, Enquiries, Notifications, Reviews, Email Logs (explicit class).
  - Intentionally **not** paginated (small catalogs — `pagination_class = None`
    stays, documented): Room Types, Room-type physical rooms, Facilities,
    Gallery, Offers.
  - Check-in / Check-out remain date-scoped operational queues (search-style,
    server-limited 25 rows) — re-judged *not warranted* as paged lists.
- `page_size: 200` scams were removed from the dashboard list pages; the two
  remaining `page_size: 100`/`: 25` sites are the room-type **dropdown** loads
  and the check-out **operational queue**, not growable lists.

---

## 3. Multi-room booking details

- **Backend was already authoritative** — `Booking.number_of_rooms`,
  `BookingRoom` assignment rows, `create_booking(rooms=N)` with
  `select_for_update` row locking and `RoomUnavailableError` → HTTP 409
  `ROOM_UNAVAILABLE`. **No silently downgraded quantities**: asking for more
  rooms than remain fails loudly ("Only N room(s) of this type remain…").
- **Frontend now exposes it**:
  - Availability search still queries at the 1-room baseline (so every type
    with ≥1 room shows *how many* are free), and each card prints the
    backend's `available_rooms` ("7 rooms available / Only 2 left / Sold out").
  - Per-card quantity stepper `1 … available_rooms`, both buttons disabled at
    their bounds; `available_rooms=0`/not-bookable cards are unselectable.
  - Quantity is a first-class field in the booking draft
    (`JONE.APP_CONFIG.STORAGE.BOOKING`) and the hand-off URLs
    (booking.html → booking-review.html → booking-confirmation.html), and is
    sent to `quoteBooking` and `createBooking`; the availability estimate and
    the review/payment totals are always backend-quoted (`N × room type` in
    the review UI).
  - Exact-room deep links `?room_id=` / `?room_no=` keep their semantics and
    force `rooms=1` (a specific physical room can only ever be booked once).
- **Prices stay server-side**: the step-2 estimate and the review/payment
  totals come from `POST /api/bookings/quote/`; no client-side price math.

**Tests (`backend/tests/test_multi_room_booking.py`, all green)**

| Case | Scenario | Result |
|---|---|---|
| 1 | book 2 of 5 | succeeds, consumes exactly 2 distinct physical rooms of the type, total = 8000 × 3n × 2 = ₦48,000 |
| 2 | 3 pre-blocked, ask 2 of 2 left | succeeds on exactly the two free rooms |
| 3 | 4 blocked, ask 2 | **409** `ROOM_UNAVAILABLE`, "Only 1 room…", zero rows created |
| 4 | book all 5 | succeeds (₦120,000), next request 409s |
| 5 | ask 6 of 5 | **409**, never downgraded, zero rows |
| 6 | 2 threads race 1 room | ≤ 1 winner, `Booking` count ≤ 1, no physical room double-booked; afterwards the stay provably 409s |

Race test is engine-aware: on row-locking MySQL the loser gets the clean
409/ROOM_UNAVAILABLE; the sqlite test DB serialises writers itself (a loser
may show lock contention as a 5xx instead), so the *absolute* invariant
asserted on every engine is **no overbooking, ≤ 1 winner** — precisely what
PENDING-expiry cleanup and the atomic assignment transaction guarantee.

---

## 4. Collapsible sidebar details

- **Breakpoint**: the app already switches to the mobile drawer at
  `max-width: 1024px`, so the whole collapse is scoped to
  `@media (min-width: 1025px)` — the saved preference can never leak onto
  mobile.
- **Widths**: expanded = existing 264px; collapsed = 76px icon-only rail;
  content area reflows via the dashboard grid.
- **Implementation**: `setupSidebarCollapse` lives inside the existing
  `setupSidebar` in `js/dashboard.js` (one manager, a single delegated click
  listener). Shells are legacy/unchecked-in (build_dash.py disabled), so the
  control is injected at runtime — **zero per-page HTML edits**, one shared
  button for every dashboard page.
- **Persistence**: plain localStorage key `jone.dashboard.sidebar`
  (nothing touched in `config.js`; never auth/booking storage), survives
  refresh and window resizes in both directions.
- **Mobile hamburger drawer left alone** (`.dash-menu-toggle`, `.open`, the
  backdrop and Escape handling in `setupSidebar` are separate, unchanged
  state).
- **Accessibility**: the collapse button has `aria-expanded` /
  `aria-controls="dash-sidebar"` and live labels ("Collapse/Expand sidebar +
  tooltip"); icon-only nav links keep their text as `aria-label`/title;
  nav-group labels hide when collapsed; the profile and Sign-out remain
  usable; nav icons unchanged (existing `chevronLeft`/Right Lucide glyphs);
  role-based filtering untouched.

---

## 5. Tests run

| Suite | Command | Result |
|---|---|---|
| Multi-room booking (6) | `manage.py test tests.test_multi_room_booking` | **OK** |
| Admin list pagination (16) | `manage.py test tests.test_admin_list_pagination` | **OK** |
| Full backend suite (**444**) | `manage.py test` | **OK** (1 pre-existing skip) |
| Frontend JS tests (**33**) | `node --test tests-js/*.js` | **0 fail** (8 pager + 5 sidebar + 20 existing) |
| HTML/JS validation | `frontend/validate.py` (52 HTML, 22 JS) | **ALL OK** |

Repo-wide search checks: `rooms: 1` → only the documented availability
baseline in `booking.html` (by design, so `available_rooms` is shown per
type); `page_size: 50/100` → only small-catalog dropdown loads; every
`pagination_class = None` judged intentional (small catalogs, documented
above); Playwright PWA tests were not run (no playwright module in the sandbox
— they mock `pagination: null`, which `normalizeList` handles gracefully).

**Note on versioning/caching**: existing pages load `js/*.js` and `css/*.css`
with a global `?v=` query pinned around `1.1.0/1.1.1`; it was intentionally
**not** globally bumped (would churn every HTML file). On deploy, the cached
`dashboard.js`/`dashboard.css` references should be cache-busted (e.g. the
usual deploy-time `version.js` bump) so browsers pick up the new sidebar
control and pager styles.
