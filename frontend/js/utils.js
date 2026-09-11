/* ==========================================================================
   shared utilities — formatting, dates, DOM helpers, events, debounce.
   ========================================================================== */

const JONE = (() => {
  "use strict";

  /* ----------------------------- Currency ---------------------------------- */
  function formatNaira(amount, opts = {}) {
    if (amount == null || isNaN(amount)) return "--";
    const n = Number(amount);
    const abs = Math.abs(n);
    const s = abs.toLocaleString("en-NG", { maximumFractionDigits: 0 });
    return `${n < 0 ? "-" : ""}₦${s}`;
  }

  /* ------------------------------- Dates ----------------------------------- */
  // Format ISO date (YYYY-MM-DD) into friendly text. e.g. "10 September 2026"
  function parseISO(str) {
    if (!str || typeof str !== "string") return null;
    const m = str.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return null;
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function formatDate(str, mode = "long") {
    const d = typeof str === "string" ? parseISO(str) : str;
    if (!d) return "--";
    const long = { day: "numeric", month: "long", year: "numeric" };
    const mid = { day: "numeric", month: "short", year: "numeric" };
    const short = { day: "2-digit", month: "2-digit", year: "numeric" };
    const opts = mode === "short" ? short : mode === "mid" ? mid : long;
    return new Intl.DateTimeFormat("en-GB", opts).format(d);
  }

  function formatDateTime(str) {
    if (!str) return "--";
    const d = parseISO(str);
    if (!d) return "--";
    return new Intl.DateTimeFormat("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    }).format(d);
  }

  // Local date string YYYY-MM-DD for input[type=date]
  function todayISO(offsetDays = 0) {
    const d = new Date();
    d.setDate(d.getDate() + offsetDays);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  // "Today" in the HOTEL's timezone (exposed by /api/hotel/ as settings.timezone).
  // The booking API judges dates by the hotel's business day; a browser in a
  // different timezone would otherwise offer check-in dates the API rejects.
  function hotelTodayISO(offsetDays = 0) {
    const tz = (window.JONE && JONE.hotelTimezone) || null;
    let iso;
    if (tz) {
      try {
        iso = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
      } catch (_) { iso = null; }
    }
    if (!iso) return todayISO(offsetDays);
    if (!offsetDays) return iso;
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + offsetDays);
    return dt.toISOString().slice(0, 10);
  }

  function nightsBetween(checkIn, checkOut) {
    const a = parseISO(checkIn), b = parseISO(checkOut);
    if (!a || !b || b <= a) return 0;
    return Math.round((b - a) / 86400000);
  }

  /* ----------------------------- DOM helpers ------------------------------- */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k === "innerHTML" || k === "textContent") node[k] = v;   // content properties, not attributes
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v != null && v !== false) node.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null) continue;
      node.appendChild(c instanceof Node ? c : document.createTextNode(c));
    }
    return node;
  }

  // Escape HTML to prevent injection when rendering API/user content.
  function esc(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ------------------------- Event handling helpers ------------------------ */
  function debounce(fn, wait = 300) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function throttle(fn, limit = 300) {
    let last;
    return function (...args) {
      const now = Date.now();
      if (last && now < last + limit) return;
      last = now;
      fn.apply(this, args);
    };
  }

  /* ------------------------------ Storage ---------------------------------- */
  const storage = {
    get(key, fallback = null) {
      try {
        const raw = localStorage.getItem(key);
        return raw == null ? fallback : JSON.parse(raw);
      } catch (_) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
    },
    remove(key) { try { localStorage.removeItem(key); } catch (_) {} }
  };

  /* -------------------------- Data attribute binding ----------------------- */
  // Set text/innerHTML of elements matching [data-bind] or [data-html].
  function bindData(mapping) {
    for (const [key, value] of Object.entries(mapping)) {
      const $text = $(`[data-bind="${key}"]`);
      if ($text) $text.textContent = value;
      const $html = $(`[data-html="${key}"]`);
      if ($html) $html.innerHTML = esc(value);
    }
  }

  /* ------------------------------ List / grid ------------------------------ */
  function paginate(items, page, perPage) {
    const total = items.length;
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    const p = Math.min(Math.max(1, page || 1), totalPages);
    const start = (p - 1) * perPage;
    return { page: p, totalPages, total, items: items.slice(start, start + perPage), start };
  }

  /* ------------------------------- Misc ------------------------------------ */
  function initials(name) {
    return String(name || "?").trim().split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
  }

  function scrollTop() {
    window.scrollTo({ top: 0, behavior: "auto" });
  }

  /* ------------------------ Reusable action guard -------------------------- */
  // prevent double submit on buttons marked [data-submit-guard]
  function guardSubmit(btn) {
    if (btn.dataset.busy === "true") return false;
    btn.dataset.busy = "true";
    btn.setAttribute("aria-busy", "true");
    btn.classList.add("is-loading");
    return true;
  }
  function releaseGuard(btn) {
    btn.dataset.busy = "false";
    btn.removeAttribute("aria-busy");
    btn.classList.remove("is-loading");
  }

  return {
    formatNaira, formatDate, formatDateTime, parseISO, todayISO, hotelTodayISO, nightsBetween,
    $, $$, el, esc, debounce, throttle, storage, bindData, paginate, initials,
    scrollTop, guardSubmit, releaseGuard
  };
})();

window.JONE = JONE;
// Expose app config on JONE (config.js sets window.APP_CONFIG) so page code can
// read JONE.APP_CONFIG consistently. See js/config.js.
JONE.APP_CONFIG = (typeof window !== "undefined" && window.APP_CONFIG) || {};
window.JONE = JONE;
