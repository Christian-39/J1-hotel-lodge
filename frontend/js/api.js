/* ==========================================================================
   Centralized API layer.
   All HTTP to the Django REST backend flows through here. Pages never build
   their own fetch(). The backend remains the single source of truth.

   Endpoint paths below are taken VERBATIM from the verified backend contract
   (backend/docs/FRONTEND_CONTRACT.md + live API inspection). Every response
   uses the envelope { success, message, data, pagination? } — errors use
   { success: false, code, message, errors? }. Money values are STRINGS
   ("25000.00") and are formatted for display only, never recomputed.
   ========================================================================== */

const API = (() => {
  "use strict";

  const BASE = (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL || "").replace(/\/$/, "");
  const DEFAULT_TIMEOUT = 20000;

  const AUTH_KEY = (window.APP_CONFIG && window.APP_CONFIG.STORAGE.AUTH) || "jone.auth";
  const SESSION_KEY = (window.APP_CONFIG && window.APP_CONFIG.STORAGE.SESSION) || "jone.session";

  const TOKEN_RE = /token|jwt|authorization|bearer/i;

  /* Grab the stored access token (kept outside localStorage entirely if possible). */
  function getToken() {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        return parsed.access || parsed.token || null;
      }
    } catch (_) {}
    return null;
  }

  /* Refresh-before-use: hook for auth.js to wire re-auth. */
  let tokenProvider = getToken;
  function setTokenProvider(fn) { tokenProvider = fn; }

  /* One-time refresh hook (wired by auth.js). Returns true if a new access
     token was obtained. Set to null to disable refresh (HttpOnly cookies). */
  let refreshProvider = null;
  function setRefreshProvider(fn) { refreshProvider = fn || null; }

  /* ------------------------------ Errors ----------------------------------- */
  class APIError extends Error {
    constructor(status, message, data) {
      super(message);
      this.name = "APIError";
      this.status = status;
      this.data = data;
      // Contract error code (e.g. ROOM_UNAVAILABLE) when present.
      this.code = (data && data.code) || null;
    }
  }

  // Map HTTP status codes to human-friendly, non-technical messages.
  // Backend-provided messages (envelope `message`) win when they are
  // user-safe; technical/token messages are replaced.
  function friendlyMessage(status, data) {
    const dmsg = data && (data.message || data.detail || data.error);
    if (dmsg && typeof dmsg === "string" && !TOKEN_RE.test(dmsg)) return dmsg;
    switch (status) {
      case 400: {
        // Field-level errors from the contract: { errors: { field: [msgs] } }
        const errs = data && data.errors;
        if (errs && typeof errs === "object") {
          const first = Object.values(errs).flat()[0];
          if (first && typeof first === "string") return first;
        }
        return "We couldn't process that request. Please check your details and try again.";
      }
      case 401: return "Your session has expired. Please sign in again.";
      case 403: return "You don't have permission to perform this action.";
      case 404: return "The requested item could not be found.";
      case 409: return "The selected room is no longer available. Please choose another room.";
      case 422: return "Some of the information provided is invalid. Please review and try again.";
      case 429: return "Too many requests. Please wait a moment and try again.";
      case 500: return "We're having trouble completing this request. Please try again.";
      case 502:
      case 503:
      case 504: return "Our services are temporarily unavailable. Please try again shortly.";
      default: return "Something went wrong. Please try again.";
    }
  }

  /* ----------------------------- Core request (single pass) ---------------- */
  async function requestOnce(path, opts = {}) {
    const {
      method = "GET",
      body,
      params,
      headers = {},
      auth = true,
      timeout = DEFAULT_TIMEOUT,
      signal
    } = opts;

    let url = BASE + path;
    if (params) {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v != null && v !== "") qs.append(k, v);
      }
      const q = qs.toString();
      if (q) url += (url.includes("?") ? "&" : "?") + q;
    }

    const out = { method, headers: { Accept: "application/json", ...headers } };
    if (body !== undefined) {
      out.body = body instanceof FormData ? body : JSON.stringify(body);
      if (!(body instanceof FormData)) out.headers["Content-Type"] = "application/json";
    }

    const token = tokenProvider();
    if (auth && token) out.headers.Authorization = `Bearer ${token}`;

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    const onAbort = () => ctrl.abort();
    if (signal) signal.addEventListener("abort", onAbort);

    try {
      const res = await fetch(url, { ...out, signal: ctrl.signal });
      clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);

      // 204 / empty
      if (res.status === 204) return {
        status: 204,
        ok: true,
        data: null,
        pagination: null,
        response: res,
        headers: res.headers
      };

      const contentType = res.headers.get("content-type") || "";
      let data = null;
      if (contentType.includes("application/json")) {
        data = await res.json().catch(() => null);
      } else {
        data = await res.text().catch(() => null);
      }

      if (!res.ok) {
        // Error path keeps the FULL envelope (it carries {errors} for forms).
        throw new APIError(res.status, friendlyMessage(res.status, data), data);
      }

      /* The backend wraps every response as {success, message?, data, pagination?}.
         Unwrap it ONCE here so every caller receives the actual payload at
         res.data (and pagination at res.pagination) — the documented contract
         of normalizeList(res.data, res.pagination). */
      let pagination = (data && typeof data === "object" && !Array.isArray(data) && data.pagination) || null;
      if (data && typeof data === "object" && !Array.isArray(data) && data.success !== undefined && "data" in data) {
        data = data.data !== undefined ? data.data : null;
      }

      return {
        status: res.status,
        ok: true,
        data,
        pagination,
        response: res,
        headers: res.headers
      };
    } catch (err) {
      clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
      if (err.name === "AbortError") {
        throw new APIError(0, "The request timed out. Please check your connection and try again.");
      }
      if (err instanceof APIError) throw err;
      throw new APIError(0, "Unable to reach our servers. Please check your connection and try again.");
    }
  }

  /* ------------------------------ Core request ----------------------------- */
  // `_retry` guards a single refresh-and-retry pass to avoid loops.
  async function request(path, opts = {}, _retry = false) {
    let response;
    try {
      response = await requestOnce(path, opts);
    } catch (err) {
      // On a 401 (expired access token) attempt exactly one refresh, then retry
      // the original request once. Prevents infinite refresh loops.
      // IMPORTANT: only for requests that actually carried a token. A 401 from
      // a public request (e.g. wrong password on /auth/login/) is a real,
      // expected failure and must surface to the caller as-is.
      const wasAuthenticated = opts.auth !== false && !!tokenProvider();
      if (err instanceof APIError && err.status === 401 && !_retry && wasAuthenticated && refreshProvider) {
        const refreshed = await refreshProvider();
        if (refreshed) {
          return request(path, opts, true);
        }
        // Refresh failed -> clear session and notify, preserving the original
        // destination for post-login return.
        if (window.Auth && typeof window.Auth.onUnauthorized === "function") {
          window.Auth.onUnauthorized();
        }
      }
      throw err;
    }
    return response;
  }

  /* ------------------------------ Verbs ------------------------------------ */
  const get = (path, opts = {}) => request(path, { ...opts, method: "GET" });
  const post = (path, body, opts = {}) => request(path, { ...opts, method: "POST", body });
  const put = (path, body, opts = {}) => request(path, { ...opts, method: "PUT", body });
  const patch = (path, body, opts = {}) => request(path, { ...opts, method: "PATCH", body });
  const del = (path, opts = {}) => request(path, { ...opts, method: "DELETE" });

  /* ------------------------- Response helpers ------------------------------ */

  /* Normalize a list response to { items, count, next, previous, page, pageSize }.
     Accepts the verified contract envelope (data array + pagination object),
     a bare array, or a legacy {results} shape — all without ever inventing rows. */
  function normalizeList(payload, pagination, defaultPageSize = 20) {
    // Contract shape: API layer passes (res.data, res.pagination).
    if (Array.isArray(payload)) {
      const pg = pagination || {};
      return {
        items: payload,
        count: pg.count != null ? pg.count : payload.length,
        next: pg.next || null,
        previous: pg.previous || null,
        page: pg.page || 1,
        pageSize: pg.page_size || defaultPageSize
      };
    }
    if (payload && typeof payload === "object") {
      // Legacy/defensive: {results, count} or response object with .data
      if (Array.isArray(payload.results)) {
        return {
          items: payload.results,
          count: payload.count != null ? payload.count : payload.results.length,
          next: payload.next || null,
          previous: payload.previous || null,
          page: 1,
          pageSize: defaultPageSize
        };
      }
      if (payload.data !== undefined) return normalizeList(payload.data, payload.pagination, defaultPageSize);
    }
    return { items: [], count: 0, next: null, previous: null, page: 1, pageSize: defaultPageSize };
  }

  /* Unwrap helper: contract responses are { success, message, data } — return data. */
  function unwrap(res) {
    // res.data is already the unwrapped payload (envelope is stripped in
    // requestOnce). Returns the payload, or the raw value for bare inputs.
    return res && res.data !== undefined ? res.data : res;
  }

  /* Assert a raw value is safe to render (never undefined/null/NaN). */
  function safe(value, fallback = "") {
    if (value === undefined || value === null) return fallback;
    if (typeof value === "number" && Number.isNaN(value)) return fallback;
    return value;
  }

  /* --------------------------- PUBLIC ENDPOINTS ----------------------------
     Paths verified against the live backend (see config.js for base URL). */

  /* Hotel info & policies */
  function getHotelInfo(opts = {}) { return get("/api/hotel/", { auth: false, ...opts }); }
  function getPolicies(opts = {}) { return get("/api/hotel/policies/", { auth: false, ...opts }); }

  /* Rooms catalog (room types) */
  function getRooms(params, opts = {}) { return get("/api/rooms/", { params, auth: false, ...opts }); }
  function getRoom(slugOrId, opts = {}) { return get(`/api/rooms/${encodeURIComponent(slugOrId)}/`, { auth: false, ...opts }); }

  /* Availability — the AUTHORITATIVE search (backend computes everything). */
  function checkAvailability(params, opts = {}) {
    return get("/api/rooms/availability/", { params, auth: false, ...opts });
  }

  /* Offers / facilities / gallery */
  function getOffers(params, opts = {}) { return get("/api/offers/", { params, auth: false, ...opts }); }
  function getFacilities(params, opts = {}) { return get("/api/facilities/", { params, auth: false, ...opts }); }
  function getGallery(params, opts = {}) { return get("/api/gallery/", { params, auth: false, ...opts }); }

  /* Enquiries / contact (honeypot `website` field must stay blank). */
  function submitEnquiry(payload, opts = {}) { return post("/api/enquiries/", payload, { auth: false, ...opts }); }

  /* ------------------------ BOOKING FLOW (guest) ---------------------------
     Quote & availability are public. Creating, viewing, paying for and
     cancelling a booking REQUIRES AUTHENTICATION (verified: IsAuthenticated). */

  /* Quote — authoritative price preview. Nothing is persisted. */
  function quoteBooking(payload, opts = {}) { return post("/api/bookings/quote/", payload, { auth: false, ...opts }); }

  /* Create booking (auth required). The backend validates availability and
     computes every amount; the response is the authoritative booking detail. */
  function createBooking(payload, opts = {}) { return post("/api/bookings/", payload, opts); }

  /* My bookings (auth required, paginated, ?status= filter supported). */
  function myBookings(params, opts = {}) { return get("/api/bookings/", { params, ...opts }); }

  /* Booking detail by id or booking_reference (auth + owner). */
  function getBooking(lookup, opts = {}) { return get(`/api/bookings/${encodeURIComponent(lookup)}/`, opts); }

  /* Cancel a booking (auth + owner). Body: { reason? }. */
  function cancelBooking(lookup, reason, opts = {}) {
    return post(`/api/bookings/${encodeURIComponent(lookup)}/cancel/`, reason ? { reason } : {}, opts);
  }

  /* Receipt for a booking (auth + owner) — renders the confirmation page. */
  function getBookingReceipt(lookup, opts = {}) {
    return get(`/api/bookings/${encodeURIComponent(lookup)}/receipt/`, opts);
  }

  /* --------------------------- PAYMENTS (Paystack) -------------------------
     The frontend never holds a Paystack secret. Initialize returns the
     backend-generated payment reference + authorization_url; success is ONLY
     ever confirmed by verifyPayment (or the server-side webhook). */

  function initPayment(bookingReference, opts = {}) {
    return post("/api/payments/initialize/", { booking_reference: bookingReference }, opts);
  }
  function verifyPayment(paymentReference, opts = {}) {
    return get(`/api/payments/verify/${encodeURIComponent(paymentReference)}/`, opts);
  }

  /* ------------------------------ AUTH ------------------------------------- */

  function login(payload, opts = {}) { return post("/api/auth/login/", payload, { auth: false, ...opts }); }
  function register(payload, opts = {}) { return post("/api/auth/register/", payload, { auth: false, ...opts }); }
  function logout(refreshToken, opts = {}) {
    return post("/api/auth/logout/", refreshToken ? { refresh: refreshToken } : {}, { auth: false, ...opts });
  }
  function me(opts = {}) { return get("/api/auth/profile/", opts); }
  function refreshTokenCall(refresh, opts = {}) {
    return post("/api/auth/token/refresh/", { refresh }, { auth: false, ...opts });
  }

  /* --------------------- NOTIFICATIONS (authenticated) --------------------- */

  function getNotifications(params, opts = {}) { return get("/api/notifications/", { params, ...opts }); }
  function getUnreadCount(opts = {}) { return get("/api/notifications/unread-count/", opts); }
  function markNotificationRead(id, opts = {}) { return post(`/api/notifications/${encodeURIComponent(id)}/read/`, {}, opts); }
  function markAllNotificationsRead(opts = {}) { return post("/api/notifications/read-all/", {}, opts); }

  /* ======================================================================
     STAFF/DASHBOARD RESOURCES — resolved from APP_CONFIG.API_ENDPOINTS
     (the single place staff paths are declared; verified against the real
     backend). A resource that is not configured fails with a clear
     APIError so the page shows an honest error state.
     ====================================================================== */
  const EPS = (window.APP_CONFIG && window.APP_CONFIG.API_ENDPOINTS) || {};
  function resourceEp(name) {
    const p = EPS[name];
    return p ? p.replace(/\/$/, "") : "";
  }

  function notConfigured(name) {
    return new APIError(0, `The "${name}" module isn't configured. Please contact the administrator.`);
  }

  // List a staff resource. Throws an APIError(0) if not configured.
  async function list(name, params, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw notConfigured(name);
    return get(base + "/", { params, ...opts });
  }
  // Get a single staff resource by id/slug/reference.
  async function getOne(name, id, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw notConfigured(name);
    return get(`${base}/${encodeURIComponent(id)}/`, opts);
  }
  // Create a staff resource. Returns backend-created record; success only on ok.
  async function create(name, payload, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw notConfigured(name);
    return post(base + "/", payload, opts);
  }
  async function update(name, id, payload, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw notConfigured(name);
    return patch(`${base}/${encodeURIComponent(id)}/`, payload, opts);
  }
  async function remove(name, id, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw notConfigured(name);
    return del(`${base}/${encodeURIComponent(id)}/`, opts);
  }

  /* -------------------- STAFF BOOKING ACTIONS (verified) -------------------
     All are POST /api/admin/bookings/{lookup}/<action>/ — lookup is the
     booking id or booking_reference. Bodies: {} or { reason? }; check-out
     also accepts { allow_balance_due? }. */

  const BOOKINGS_EP = () => resourceEp("bookings");
  function bookingAction(action, lookup, payload, opts = {}) {
    const base = BOOKINGS_EP();
    if (!base) throw notConfigured("bookings");
    return post(`${base}/${encodeURIComponent(lookup)}/${action}/`, payload || {}, opts);
  }
  const confirmBooking   = (lookup, opts = {}) => bookingAction("confirm", lookup, {}, opts);
  const staffCancelBooking = (lookup, reason, opts = {}) => bookingAction("cancel", lookup, reason ? { reason } : {}, opts);
  const checkInBooking   = (lookup, opts = {}) => bookingAction("check-in", lookup, {}, opts);
  const checkOutBooking  = (lookup, payload, opts = {}) => bookingAction("check-out", lookup, payload || {}, opts);
  const noShowBooking    = (lookup, opts = {}) => bookingAction("no-show", lookup, {}, opts);
  const assignRoom       = (lookup, roomId, opts = {}) => bookingAction("assign-room", lookup, { room: roomId }, opts);

  /* Record an offline payment (CASH / POS / BANK_TRANSFER). */
  function recordPayment(payload, opts = {}) {
    const base = resourceEp("payments");
    if (!base) throw notConfigured("payments");
    return post(base + "/record/", payload, opts);
  }

  return {
    get, post, put, patch, del, request,
    // Public site
    getHotelInfo, getPolicies, getRooms, getRoom, checkAvailability,
    getOffers, getFacilities, getGallery, submitEnquiry,
    // Booking flow (guest)
    quoteBooking, createBooking, myBookings, getBooking, cancelBooking, getBookingReceipt,
    // Payments
    initPayment, verifyPayment,
    // Auth
    login, register, logout, me, refreshTokenCall,
    // Notifications
    getNotifications, getUnreadCount, markNotificationRead, markAllNotificationsRead,
    // Staff resources + actions
    list, getOne, create, update, remove,
    confirmBooking, staffCancelBooking, checkInBooking, checkOutBooking,
    noShowBooking, assignRoom, recordPayment,
    // Helpers
    setTokenProvider, setRefreshProvider, APIError, BASE,
    normalizeList, unwrap, safe
  };
})();

window.API = API;
