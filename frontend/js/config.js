/* ==========================================================================
   J-ONE HOTEL & LODGE — global app configuration.
   Centralized so API endpoints are never scattered across files.
   ========================================================================== */

(function () {
  // Same machine (dev) vs the deployed frontend (prod).
  var isLocal = ["localhost", "127.0.0.1", ""].indexOf(window.location.hostname) !== -1;

  var API_BASE_URL = isLocal
    ? "http://127.0.0.1:8000"          // Django dev server (Live Server on :5500)
    : "https://api.j-onehotel.com";    // production backend URL (set at deploy time)

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
       BACKEND CONTRACT — staff/dashboard endpoints.
       The exact paths below MUST be confirmed against the real Django backend
       before go-live (do NOT assume they match the public endpoints — e.g.
       bookings ARE in the staff namespace but return authenticated records).
       Until an endpoint is filled in, the corresponding dashboard page shows an
       honest "not configured" error state instead of fake data or a guessed URL.
       ======================================================================== */
    API_ENDPOINTS: {
      bookings:      "",   // e.g. "/api/admin/bookings/"
      booking:       "",   // detail, e.g. "/api/admin/bookings/{id}/"
      guests:        "",   // e.g. "/api/admin/guests/"
      rooms:         "",   // e.g. "/api/admin/rooms/"
      availability:  "",   // e.g. "/api/rooms/availability/"
      checkIns:      "",   // e.g. "/api/admin/bookings/check-in/"
      checkOuts:     "",   // e.g. "/api/admin/bookings/check-out/"
      payments:      "",   // e.g. "/api/admin/payments/"
      receipts:      "",   // e.g. "/api/bookings/{ref}/receipt/"
      enquiries:     "",   // e.g. "/api/admin/enquiries/"
      notifications: "",   // e.g. "/api/notifications/"
      auditLogs:     "",   // e.g. "/api/admin/audit-logs/"
      reports:       "",   // e.g. "/api/admin/reports/"
      stats:         "",   // e.g. "/api/admin/dashboard/"
      settings:      "",   // e.g. "/api/admin/settings/"
      facilities:    "",   // e.g. "/api/admin/facilities/"
      offers:        "",   // e.g. "/api/admin/offers/"
      gallery:       ""    // e.g. "/api/admin/gallery/"
    }
  };
})();

/* Runtime configuration injection (overrides) — set server-side before load if needed.
   Wins over the auto-detection above. */
if (window.__APP_CONFIG__) {
  Object.assign(window.APP_CONFIG, window.__APP_CONFIG__);
}