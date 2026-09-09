/* ==========================================================================
   Centralized API layer.
   All HTTP to the Django REST backend flows through here. Pages never build
   their own fetch(). The backend remains the single source of truth.
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
    // Fallback to cookie-based session if the backend uses one.
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
    }
  }

  // Map HTTP status codes to human-friendly, non-technical messages.
  function friendlyMessage(status, data) {
    const dmsg = data && (data.detail || data.message || data.error);
    if (dmsg && typeof dmsg === "string" && !TOKEN_RE.test(dmsg)) return dmsg;
    switch (status) {
      case 400: return "We couldn't process that request. Please check your details and try again.";
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
        throw new APIError(res.status, friendlyMessage(res.status, data), data);
      }

      return { status: res.status, ok: true, data, response: res, headers: res.headers };
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
      if (err instanceof APIError && err.status === 401 && !_retry && refreshProvider) {
        const refreshed = await refreshProvider();
        if (refreshed) {
          return request(path, opts, true);
        }
        // Refresh failed -> clear session and redirect to login, preserving the
        // original destination for post-login return.
        if (window.Auth && typeof window.Auth.onUnauthorized === "function") {
          window.Auth.onUnauthorized();
        }
      }
      throw err;
    }
    // 204 / empty
    return response;
  }

  /* ------------------------------ Verbs ------------------------------------ */
  const get = (path, opts = {}) => request(path, { ...opts, method: "GET" });
  const post = (path, body, opts = {}) => request(path, { ...opts, method: "POST", body });
  const put = (path, body, opts = {}) => request(path, { ...opts, method: "PUT", body });
  const patch = (path, body, opts = {}) => request(path, { ...opts, method: "PATCH", body });
  const del = (path, opts = {}) => request(path, { ...opts, method: "DELETE" });

  /* ------------------------- Authoritative helpers ------------------------- */

  /* Normalize a DRF paginated or bare array list response.
     Returns { items, count, next, previous, page, pageSize }. */
  function normalizeList(data, defaultPageSize = 10) {
    if (Array.isArray(data)) {
      return { items: data, count: data.length, next: null, previous: null, page: 1, pageSize: defaultPageSize };
    }
    if (data && typeof data === "object") {
      const results = Array.isArray(data.results) ? data.results : [];
      return {
        items: results,
        count: data.count != null ? data.count : results.length,
        next: data.next || null,
        previous: data.previous || null,
        page: data.page || (data.pagination && data.pagination.page) || 1,
        pageSize: data.page_size || (data.pagination && data.pagination.page_size) || defaultPageSize
      };
    }
    return { items: [], count: 0, next: null, previous: null, page: 1, pageSize: defaultPageSize };
  }

  /* Assert a raw value is safe to render (never undefined/null/NaN). */
  function safe(value, fallback = "") {
    if (value === undefined || value === null) return fallback;
    if (typeof value === "number" && Number.isNaN(value)) return fallback;
    return value;
  }

  /* Rooms */
  function getRooms(params, opts = {}) { return get("/api/rooms/", { params, ...opts }); }
  function getRoom(slug, opts = {}) { return get(`/api/rooms/${slug}/`, opts); }

  /* Availability — always consult backend. Never compute locally. */
  function checkAvailability(params, opts = {}) {
    return get("/api/availability/", { params, auth: false, ...opts });
  }

  /* Offers / facilities / gallery */
  function getOffers(params, opts = {}) { return get("/api/offers/", { params, auth: false, ...opts }); }
  function getFacilities(params, opts = {}) { return get("/api/facilities/", { params, auth: false, ...opts }); }
  function getGallery(params, opts = {}) { return get("/api/gallery/", { params, auth: false, ...opts }); }

  /* Hotel info / settings (public-safe subset) */
  function getHotelInfo(opts = {}) { return get("/api/hotel/", { auth: false, ...opts }); }
  function getSettings(opts = {}) { return get("/api/settings/", { auth: false, ...opts }); }

  /* Public bookings */
  function initBooking(payload, opts = {}) { return post("/api/bookings/", payload, { auth: false, ...opts }); }
  function getBookingByRef(ref, opts = {}) { return get(`/api/bookings/ref/${ref}/`, { auth: false, ...opts }); }

  /* Payments — Initiate. Frontend never holds a Paystack secret. */
  function initPayment(bookingRef, payload = {}, opts = {}) {
    return post(`/api/bookings/${bookingRef}/pay/`, payload, { auth: false, ...opts });
  }
  function checkPaymentStatus(bookingRef, opts = {}) {
    return get(`/api/bookings/${bookingRef}/payment-status/`, { auth: false, ...opts });
  }

  /* Enquiries / contact */
  function submitEnquiry(payload, opts = {}) { return post("/api/enquiries/", payload, { auth: false, ...opts }); }

  /* ======================================================================
     Staff/dashboard resources — resolved from APP_CONFIG.API_ENDPOINTS.
     These are a SINGLE integration point: the paths are contract-dependent
     and set in config.js. We never guess a path here. Until configured, the
     call fails with a clear APIError so the page shows a real error state.
     ====================================================================== */
  const EPS = (window.APP_CONFIG && window.APP_CONFIG.API_ENDPOINTS) || {};
  function resourceEp(name) {
    const p = EPS[name];
    return p ? p.replace(/\/$/, "") : "";
  }

  // List a staff resource. Throws an APIError(0) if not configured.
  async function list(name, params, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw new APIError(0, "This module isn't configured yet. Please contact the administrator.");
    return get(base, { params, ...opts });
  }
  // Get a single staff resource by id/slug.
  async function getOne(name, id, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw new APIError(0, "This module isn't configured yet. Please contact the administrator.");
    return get(`${base}/${encodeURIComponent(id)}/`, opts);
  }
  // Create a staff resource. Returns backend-created record; success only on ok.
  async function create(name, payload, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw new APIError(0, "This module isn't configured yet. Please contact the administrator.");
    return post(`${base}/`, payload, opts);
  }
  async function update(name, id, payload, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw new APIError(0, "This module isn't configured yet. Please contact the administrator.");
    return patch(`${base}/${encodeURIComponent(id)}/`, payload, opts);
  }
  async function remove(name, id, opts = {}) {
    const base = resourceEp(name);
    if (!base) throw new APIError(0, "This module isn't configured yet. Please contact the administrator.");
    return del(`${base}/${encodeURIComponent(id)}/`, opts);
  }

  return {
    get, post, put, patch, del, request,
    getRooms, getRoom, checkAvailability,
    getOffers, getFacilities, getGallery,
    getHotelInfo, getSettings,
    initBooking, getBookingByRef,
    initPayment, checkPaymentStatus,
    submitEnquiry,
    // Auth endpoints (wired by auth.js)
    login: (payload, opts = {}) => post("/api/auth/login/", payload, { auth: false, ...opts }),
    logout: (opts = {}) => post("/api/auth/logout/", {}, opts),
    me: (opts = {}) => get("/api/auth/me/", opts),
    setTokenProvider, setRefreshProvider, APIError, BASE,
    normalizeList, safe,
    // Staff resource helpers (resolved from API_ENDPOINTS integration point)
    list, getOne, create, update, remove
  };
})();

window.API = API;
