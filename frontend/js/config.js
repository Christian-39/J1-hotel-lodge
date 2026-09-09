/* ==========================================================================
   J-ONE HOTEL & LODGE — global app configuration.
   Centralized so API endpoints are never scattered across files.
   ========================================================================== */

window.APP_CONFIG = {
  API_BASE_URL: "",   // e.g. "https://api.j-onehotel.com" — set at deploy time
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
    bookings:      "",   // e.g. "/api/staff/bookings/"
    booking:       "",   // detail, e.g. "/api/staff/bookings/{id}/"
    guests:        "",   // e.g. "/api/staff/guests/"
    rooms:         "",   // e.g. "/api/staff/rooms/"
    availability:  "",   // e.g. "/api/staff/availability/"
    checkIns:      "",   // e.g. "/api/staff/check-ins/"
    checkOuts:     "",   // e.g. "/api/staff/check-outs/"
    payments:      "",   // e.g. "/api/staff/payments/"
    receipts:      "",   // e.g. "/api/staff/receipts/"
    enquiries:     "",   // e.g. "/api/staff/enquiries/"
    notifications: "",   // e.g. "/api/staff/notifications/"
    auditLogs:     "",   // e.g. "/api/staff/audit-logs/"
    reports:       "",   // e.g. "/api/staff/reports/"
    stats:         "",   // e.g. "/api/staff/stats/"
    settings:      "",   // e.g. "/api/settings/" (staff-writable hotel config)
    facilities:    "",   // e.g. "/api/staff/facilities/"
    offers:        "",   // e.g. "/api/staff/offers/"
    gallery:       ""    // e.g. "/api/staff/gallery/"
  }
};

/* Runtime configuration injection (overrides) — set server-side before load if needed. */
if (window.__APP_CONFIG__) {
  Object.assign(window.APP_CONFIG, window.__APP_CONFIG__);
}
