/* ==========================================================================
   J-ONE HOTEL & LODGE — global app configuration.
   Centralized so API endpoints are never scattered across files.
   ========================================================================== */

(function () {
  // Same machine (dev) vs the deployed frontend (prod).
  var isLocal = ["localhost", "127.0.0.1", ""].indexOf(window.location.hostname) !== -1;

  var API_BASE_URL = isLocal
    ? "http://127.0.0.1:8000"          // Django dev server (Live Server on :5500)
    : "https://j1-hotel-lodge-backend.onrender.com";    // production backend URL (set at deploy time)

  window.APP_CONFIG = {
    API_BASE_URL: API_BASE_URL,
    HOTEL_SLUG: "j-one-hotel-lodge",
    PAGE_DEFAULT: 1,
    PAGE_SIZE: 10,

  /* Booking flow defaults (backed by hotel settings from the API at runtime) */
  DEFAULT_ADULTS: 2,
  DEFAULT_CHILDREN: 0,
  MIN_STAY_NIGHTS: 1,
  CURRENCY: "NGN",

  /* Storage keys */
  STORAGE: {
    THEME: "jone.theme",
    AUTH: "jone.auth",
    BOOKING: "jone.booking.draft",
    SESSION: "jone.session"
  },

  /* ========================================================================
     BACKEND CONTRACT — staff/dashboard resource base paths.
     VERIFIED against the actual Django backend (live run + its test suite +
     docs/FRONTEND_CONTRACT.md). Keep in sync with config/urls.py on the
     backend. All lists are paginated with the shared envelope; detail paths
     are derived as {base}/{id}/ by js/api.js.

     Guest-facing endpoints (auth, rooms, availability, quote, bookings,
     payments, notifications, enquiries) are wired directly in js/api.js —
     they are part of the public contract, not deploy-time configuration.
     ======================================================================== */
  API_ENDPOINTS: {
    /* Hotel operations (staff, /api/admin/ namespace) */
    bookings:      "/api/admin/bookings/",        // list/create; detail {id|ref}; actions via API.checkInBooking() etc.
    booking:       "/api/admin/bookings/",        // detail view alias (booking-details page)
    guests:        "/api/admin/guests/",
    rooms:         "/api/admin/rooms/",           // physical rooms (status/housekeeping)
    roomTypes:     "/api/admin/room-types/",      // catalog CRUD + images upload
    roomImages:    "/api/admin/room-images/",      // room-type image detail (PATCH/DELETE)
    amenities:     "/api/admin/amenities/",
    payments:      "/api/admin/payments/",        // list; detail {id|ref}; record via API.recordPayment()
    receipts:      "/api/admin/payments/",        // receipts view = payment records
    enquiries:     "/api/admin/enquiries/",
    auditLogs:     "/api/admin/audit-logs/",      // ADMIN, read-only
    users:         "/api/admin/users/",           // ADMIN
    settings:      "/api/admin/settings/",        // GET manager+, PATCH admin-only
    stats:         "/api/admin/dashboard/",       // dashboard KPIs
    facilities:    "/api/admin/facilities/",
    policies:      "/api/admin/policies/",
    offers:        "/api/admin/offers/",
    gallery:       "/api/admin/gallery/",

    /* Reports (MANAGER+) — three concrete endpoints */
    reportsRevenue:    "/api/admin/reports/revenue/",
    reportsOccupancy:  "/api/admin/reports/occupancy/",
    reportsBookings:   "/api/admin/reports/bookings/",

    /* Authoritative availability search (public; used by staff too) */
    availability:  "/api/rooms/availability/",

    /* Notifications (authenticated user, not admin-namespaced) */
    notifications: "/api/notifications/"
  }
};
})();

/* Runtime configuration injection (overrides) — set server-side before load if needed. */
if (window.__APP_CONFIG__) {
  Object.assign(window.APP_CONFIG, window.__APP_CONFIG__);
  if (window.__APP_CONFIG__.API_ENDPOINTS) {
    Object.assign(window.APP_CONFIG.API_ENDPOINTS, window.__APP_CONFIG__.API_ENDPOINTS);
  }
}
