# J-ONE — Targeted Update Plan (working notes)

Baseline: 422 backend tests pass (1 skipped) — recorded 2026-09-18 before changes.

## Task 1 — Pagination (API-level via existing StandardPagination)
- [x] Backend: all admin list endpoints already DRF-paginated (page/page_size + max 100).
- [ ] api.js: extend normalizeList with totalPages (additive).
- [ ] dashboard.js: reusable JONE.dashboard.renderPagination (+ testable paginationHTML).
- [ ] components.css: pagination component styles (compact, accessible, dark-mode safe).
- [ ] Pages paginated at page_size 20: bookings, guests, payments, refunds, receipts,
      audit-logs, staff, enquiries, notifications, reviews (migrate to shared helper).
- [ ] Not paginated (justified): availability search (per room type), check-in/out
      (date-scoped ops lists bounded by inventory), dashboard index (today's ops),
      rooms/room-details (bounded inventory catalog), facilities/offers/gallery
      (small static catalogs, backends intentionally pagination_class=None).
- [ ] Every page: filter/search change → page=1; page change preserves filters.

## Task 2 — Multiple rooms of same type (backend already supports `rooms`)
- [ ] booking.html: per-card available count + quantity stepper (min 1, max
      available_rooms), sold-out state; selRoom.rooms; draft rooms; quote estimate
      via API.quoteBooking(rooms=N); continue URL carries rooms; exact-room (room_id)
      flow stays qty=1.
- [ ] booking-stepper.js: carry rooms in back-nav criteria.
- [ ] booking-review.html: data.rooms, "2 × Superior" display, Rooms row, quote(N),
      persists rooms, passes rooms to payment step.
- [ ] booking-confirmation.html: criteria.rooms; quote + create payload rooms=N;
      idempotency signature includes rooms; payment summary shows quantity.

## Task 3 — Collapsible desktop sidebar (mobile drawer untouched)
- [ ] dashboard.js: single collapse manager inside existing setupSidebar path;
      injects control once; body[data-sidebar] state; localStorage
      jone.dashboard.sidebar; logout label wrapped for icon-only mode.
- [ ] dashboard.css: @media (min-width:1025px) collapsed styles (76px vs 264px),
      accessible CSS tooltips (focus + hover), group label handling.
- [ ] shell.py: emit the collapse control + wrapped logout label for future shells.

## Tests
- [x] Baseline suite green.
- [ ] backend/tests/test_admin_list_pagination.py (payments/audit/bookings/guests).
- [ ] backend/tests/test_multi_room_booking.py (cases 1–6 incl. race).
- [ ] frontend/tests-js/test-pagination.js (paginationHTML + normalizeList).
- [ ] Full suite re-run + report.
