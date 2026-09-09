/* ==========================================================================
   dashboard.js — shared staff dashboard behaviours.
   Nav rendering, sidebar, role-aware menus, KPI/data rendering helpers,
   reusable list + table renderers for bookings/guests/rooms.
   ========================================================================== */

(function () {
  "use strict";

  /* --------------------------- Sidebar rendering --------------------------- */
  const NAV = [
    { group: "Overview", items: [
      { label: "Dashboard", href: "index.html", icon: "layout", view: "dashboard" },
    ]},
    { group: "Operations", items: [
      { label: "Bookings", href: "bookings.html", icon: "calendar", view: "bookings" },
      { label: "Availability", href: "availability.html", icon: "grid", view: "availability" },
      { label: "Check-in", href: "check-in.html", icon: "logOut", view: "check-in" },
      { label: "Check-out", href: "check-out.html", icon: "logOut", view: "check-out" },
      { label: "Guests", href: "guests.html", icon: "users", view: "guests" },
      { label: "Rooms", href: "rooms.html", icon: "bed", view: "rooms" },
    ]},
    { group: "Finance", items: [
      { label: "Payments", href: "payments.html", icon: "creditCard", view: "payments" },
      { label: "Receipts", href: "receipts.html", icon: "receipt", view: "receipts" },
      { label: "Reports", href: "reports.html", icon: "barChart", view: "reports" },
    ]},
    { group: "Content", items: [
      { label: "Facilities", href: "facilities.html", icon: "building", view: "facilities" },
      { label: "Gallery", href: "gallery.html", icon: "image", view: "gallery" },
      { label: "Offers", href: "offers.html", icon: "tag", view: "offers" },
    ]},
    { group: "Communication", items: [
      { label: "Enquiries", href: "enquiries.html", icon: "message", view: "enquiries" },
      { label: "Notifications", href: "notifications.html", icon: "bell", view: "notifications" },
    ]},
    { group: "Administration", items: [
      { label: "Audit Logs", href: "audit-logs.html", icon: "fileText", view: "audit-logs", role: "admin" },
      { label: "Settings", href: "settings.html", icon: "settings", view: "settings", role: "admin" },
    ]},
  ];

  function renderSidebar(containerSel) {
    const container = document.querySelector(containerSel);
    if (!container) return;
    const current = location.pathname;
    let html = "";
    NAV.forEach((g) => {
      const items = g.items.filter((it) => !it.role || (window.Auth && window.Auth.hasRole && window.Auth.hasRole(it.role)));
      if (!items.length) return;
      html += '<div class="dash-nav-group"><div class="dash-nav-label">' + JONE.esc(g.group).toUpperCase() + '</div>';
      items.forEach((it) => {
        let cls = "dash-nav-item";
        if (current.endsWith("/" + it.href)) cls += " is-active";
        html += '<a class="' + cls + '" href="' + it.href + '"><span data-icon="' + it.icon + '"></span>' + JONE.esc(it.label) + "</a>";
      });
      html += "</div>";
    });
    container.innerHTML = html;
    JONE.icons.inject(container);
  }

  /* ------------------------- Role / user header ---------------------------- */
  function renderUser(containerSel) {
    const c = document.querySelector(containerSel);
    if (!c) return;
    const user = (window.Auth && window.Auth.state && window.Auth.state.user) || {};
    const name = user.full_name || user.name || user.username || "Staff";
    const role = (user.role || "staff").replace(/_/g, " ");
    c.innerHTML =
      '<div class="dash-avatar">' + JONE.esc(JONE.initials(name)) + "</div>" +
      '<div><div class="dash-user-name">' + JONE.esc(name) + '</div><div class="dash-user-role">' + JONE.esc(role) + "</div></div>";
  }

  /* ------------------------ Data-state renderers -------------------------- */
  // Central loading / empty / error states so dashboard pages never show fake
  // records or blank space. States only appear for genuine API outcomes.
  // Detect whether a target is a table/tbody (row-based) or a generic container.
  function isTable(el) {
    return el && (el.tagName === "TBODY" || el.tagName === "TABLE" || el.tagName === "TR");
  }
  function stateBody(kind, icon, title, msg, extra) {
    const ic = icon ? '<span data-icon="' + JONE.esc(icon) + '" data-size="42"></span>' : '';
    const m = msg ? '<p>' + JONE.esc(msg) + '</p>' : '';
    return '<div class="' + (kind === "loading" ? "loading-block" : "empty-state") + '">' +
      (kind === "loading"
        ? '<div class="spinner" role="status"></div><p class="muted">' + JONE.esc(msg || "Loading&hellip;") + '</p>'
        : ic + '<h3>' + JONE.esc(title) + '</h3>' + m + (extra || '')) +
      '</div>';
  }

  const DATA = {
    apiBaseConfigured() {
      return !!(window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL);
    },
    loading(el, kind = "table") {
      if (!el) return;
      const tbl = isTable(el);
      const colspan = el.getAttribute ? (el.getAttribute("colspan") || 8) : 8;
      el.innerHTML = tbl
        ? '<tr><td colspan="8">' + stateBody("loading", "", "", "Loading&hellip;") + '</td></tr>'
        : stateBody("loading", "", "", "Loading&hellip;");
    },
    empty(el, icon, title, msg, colspan = 8) {
      if (!el) return;
      const tbl = isTable(el);
      el.innerHTML = tbl
        ? '<tr><td colspan="' + colspan + '">' + stateBody("", icon, title, msg) + '</td></tr>'
        : stateBody("", icon, title, msg);
      if (icon || title) JONE.icons.inject(el);
    },
    error(el, title, msg, colspan = 8, showRetry = true) {
      if (!el) return;
      const retry = showRetry ? '<button class="btn btn-sm btn-outline" data-retry style="margin-top:0.75rem;">Try again</button>' : '';
      const tbl = isTable(el);
      el.innerHTML = tbl
        ? '<tr><td colspan="' + colspan + '">' + stateBody("", "alertTriangle", title, msg, retry) + '</td></tr>'
        : stateBody("", "alertTriangle", title, msg, retry);
      if (showRetry) {
        const btn = el.querySelector("[data-retry]");
        if (btn) btn.addEventListener("click", () => { location.reload(); });
      }
    },
    // Wrap a list target: show loading, then either rows / empty / error.
    async loadList(container, cells, opts) {
      const { icon, emptyTitle, emptyMsg, errorTitle, errorMsg, loadFn, mapRow, colspan } = opts;
      DATA.loading(container, "table");
      try {
        const res = await loadFn();
        const list = (res && (res.results || (Array.isArray(res) ? res : res.items))) || [];
        if (!list.length) {
          DATA.empty(container, icon, emptyTitle, emptyMsg, colspan || cells);
          return [];
        }
        container.innerHTML = list.map(mapRow).join("");
        JONE.icons.inject(container);
        return list;
      } catch (err) {
        DATA.error(container, errorTitle || "We couldn't load this data.", (err && err.message) || errorMsg || "", colspan || cells);
        return null;
      }
    }
  };

  /* ----------------------- Generic helpers for pages ----------------------- */
  function statusPill(status, textOrOverride) {
    const s = (status || "").toLowerCase().replace(/[\s_]+/g, "_");
    const label = textOrOverride || String(status || "").replace(/[_-]+/g, " ").toUpperCase();
    return '<span class="status-pill status-' + JONE.esc(s) + '">' + JONE.esc(label) + "</span>";
  }

  function badge(text) {
    return '<span class="badge">' + JONE.esc(text) + "</span>";
  }

  /* Render bookmarks/counts for topbar notice of low stock etc. */
  function topbar(title, subtitle, actionsHTML) {
    const t = document.querySelector("[data-dash-title]");
    if (t) t.innerHTML = "<h1>" + JONE.esc(title) + "</h1>" + (subtitle ? "<p>" + JONE.esc(subtitle) + "</p>" : "");
    const a = document.querySelector("[data-topbar-actions]");
    if (a && actionsHTML) a.innerHTML = actionsHTML;
  }

  /* Boot a dashboard page: guard auth, render sidebar + user, mark active.
     Production ALWAYS requires real authentication — there is no demo bypass.
     If a backend-less visual preview is ever required during development it must
     be enabled explicitly through window.APP_CONFIG.DEV_PREVIEW (default off)
     and never surfaces in a deployed build. */
  function boot(minRole) {
    const devPreview = !!(window.APP_CONFIG && window.APP_CONFIG.DEV_PREVIEW);
    if (!window.Auth.guard(minRole)) return false;
    renderSidebar("[data-dash-nav]");
    renderUser("[data-dash-user]");
    window.JONE.nav && window.JONE.nav.initDashboardNav();
    if (window.JONE.nav) window.JONE.nav.markActive(document);
    return true;
  }

  window.JONE = window.JONE || {};
  window.JONE.dashboard = { renderSidebar, renderUser, statusPill, boot, topbar, NAV, badge, DATA };
})();
