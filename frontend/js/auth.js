/* ==========================================================================
   Auth — staff login, session persistence, role-aware UI, guards.
   Frontend role checks are UX-only; the backend is authoritative.
   ========================================================================== */

(function () {
  "use strict";

  const KEY = (window.APP_CONFIG && window.APP_CONFIG.STORAGE.AUTH) || "jone.auth";
  const SESSION_KEY = (window.APP_CONFIG && window.APP_CONFIG.STORAGE.SESSION) || "jone.session";

  const state = {
    user: null,
    role: null,
    permissions: []
  };

  const ROLES = { ADMIN: "admin", MANAGER: "manager", RECEPTIONIST: "receptionist", STAFF: "staff" };

  /* Normalize whatever role shape the backend sends into our lowercase set.
     Django superusers may carry is_superuser without an explicit role. */
  function normalizeRole(user, role) {
    const u = user || {};
    if (u.is_superuser) return "admin";
    const raw = u.role || role || null;
    return raw ? String(raw).toLowerCase() : null;
  }

  function storeSession(data) {
    // Keep tokens in sessionStorage (cleared on tab close) and profile in localStorage.
    const { access, refresh, token, ...rest } = data || {};
    const cred = { access: access || token || null, refresh: refresh || null };
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(cred)); } catch (_) {}
    JONE.storage.set(KEY, rest.user || rest);
    Object.assign(state, rest.user || rest);
    state.user = rest.user || rest;
    state.role = normalizeRole(rest.user, rest.role);
    state.permissions = (rest.user && rest.user.permissions) || rest.permissions || [];
  }

  function clearSession() {
    try { sessionStorage.removeItem(SESSION_KEY); } catch (_) {}
    JONE.storage.remove(KEY);
    state.user = null; state.role = null; state.permissions = [];
  }

  function isAuthenticated() {
    try { return !!sessionStorage.getItem(SESSION_KEY); } catch (_) { return !!JONE.storage.get(KEY, null); }
  }

  function hasRole(minRole) {
    // Receptionist < Manager < Admin
    if (!state.role) return false;
    const order = { receptionist: 1, staff: 1, manager: 2, admin: 3 };
    const role = String(state.role).toLowerCase();
    const needed = String(minRole || "").toLowerCase();
    return (order[role] || 0) >= (order[needed] || 99);
  }

  function can(perm) {
    if (!perm) return true;
    if (state.permissions.includes("*")) return true;
    return state.permissions.includes(perm);
  }

  /* Wire API token provider + one-time refresh provider. */
  function setAPITokenProvider() {
    window.API.setTokenProvider(() => {
      try {
        const raw = sessionStorage.getItem(SESSION_KEY);
        return raw ? (JSON.parse(raw).access || JSON.parse(raw).token) : null;
      } catch (_) { return null; }
    });
    if (window.API.setRefreshProvider) window.API.setRefreshProvider(refreshAccess);
  }
  setAPITokenProvider();

  /* One-time refresh: called by the API layer on a 401. Returns true when a new
     access token was obtained so the original request is retried once. Never
     loops (the API layer only retries a single time). */
  let refreshing = false;
  async function refreshAccess() {
    if (refreshing) return false;      // guard against concurrent refresh storms
    refreshing = true;
    try {
      let refreshToken = null;
      try { refreshToken = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "{}").refresh; } catch (_) {}
      if (!refreshToken) return false;
      // Contract-presumed refresh endpoint; the backend must expose it for
      // JWT-based auth. If the backend uses HttpOnly cookies, set
      // API.setRefreshProvider(null) instead.
      const res = await window.API.post("/api/auth/refresh/", { refresh: refreshToken }, { auth: false });
      const data = res.data || {};
      const access = data.access || data.token;
      if (!access) return false;
      try {
        const cur = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "{}");
        cur.access = access;
        if (data.refresh) cur.refresh = data.refresh;
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(cur));
      } catch (_) {}
      return true;
    } catch (_) {
      return false;
    } finally {
      refreshing = false;
    }
  }

  function onUnauthorized() {
    // Called by the API layer only AFTER a refresh attempt failed (or when no
    // refresh provider is configured). Clear session and redirect to login,
    // preserving the original destination for post-login return.
    clearSession();
    const here = location.pathname;
    const inDashboard = here.includes("/dashboard/");
    if (inDashboard) {
      const next = encodeURIComponent(here + location.search);
      try { JONE.ui.toast("Your session has expired. Please sign in again.", "warning"); } catch (_) {}
      location.replace("/login.html?next=" + next);
    }
  }

  /* Restore profile on load so header can render user state without a round-trip. */
  function restore() {
    if (window.API && !window.API.APIError) setAPITokenProvider();
    setAPITokenProvider();
    if (isAuthenticated()) {
      const profile = JONE.storage.get(KEY, null);
      if (profile) {
        state.user = profile.user || profile;
        state.role = normalizeRole(state.user, profile.role);
        state.permissions = state.user.permissions || profile.permissions || [];
      }
    }
  }

  async function login(username, password) {
    const res = await window.API.login({ username, password });
    storeSession(res.data);
    setAPITokenProvider();
    return res.data;
  }

  async function logout() {
    try { await window.API.logout(); } catch (_) {}
    clearSession();
    location.href = "/login.html";
  }

  async function refreshProfile() {
    const res = await window.API.me();
    storeSession(res.data);
    return state.user;
  }

  /* Guards for dashboard pages. Call Auth.guard() on page load. */
  function guard(minRole) {
    restore();
    if (!isAuthenticated()) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.replace("/login.html?next=" + next);
      return false;
    }
    if (minRole && !hasRole(minRole)) {
      // Not enough permission (frontend only; backend enforces too). Show 403.
      location.replace("/403.html");
      return false;
    }
    return true;
  }

  function bindLoginForm(formSel, opts = {}) {
    const form = document.querySelector(formSel);
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = form.querySelector("[type=submit]");
      if (!JONE.guardSubmit(btn)) return;
      const fd = new FormData(form);
      const username = (fd.get("username") || "").trim();
      const password = fd.get("password") || "";
      try {
        await login(username, password);
        JONE.ui.toast("Welcome back.", "success");
        const next = new URLSearchParams(location.search).get("next") || "/dashboard/";
        location.href = next;
      } catch (err) {
        JONE.releaseGuard(btn);
        const msg = err.status === 401 ? "Incorrect username or password." : err.message;
        JONE.ui.toast(msg, "error");
        const errBox = form.querySelector("[data-form-error]");
        if (errBox) { errBox.textContent = msg; errBox.style.display = "block"; }
      }
    });
  }

  window.Auth = {
    ROLES, state, login, logout, guard, hasRole, can,
    isAuthenticated, restore, refreshProfile, onUnauthorized,
    bindLoginForm, clearSession, refreshAccess
  };
  window.JONE = window.JONE || {};
})();