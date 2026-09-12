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
      { label: "Reports", href: "reports.html", icon: "barChart", view: "reports", minRole: "manager" },
    ]},
    { group: "Content", items: [
      { label: "Facilities", href: "facilities.html", icon: "building", view: "facilities", minRole: "manager" },
      { label: "Gallery", href: "gallery.html", icon: "image", view: "gallery", minRole: "manager" },
      { label: "Offers", href: "offers.html", icon: "tag", view: "offers", minRole: "manager" },
    ]},
    { group: "Communication", items: [
      { label: "Enquiries", href: "enquiries.html", icon: "message", view: "enquiries" },
      { label: "Notifications", href: "notifications.html", icon: "bell", view: "notifications" },
    ]},
    { group: "Administration", items: [
      { label: "Staff", href: "staff.html", icon: "users", view: "staff", role: "admin" },
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
      const items = g.items.filter((it) => {
        if (it.role && !(window.Auth && window.Auth.hasRole && window.Auth.hasRole(it.role))) return false;
        if (it.minRole && !(window.Auth && window.Auth.hasRole && window.Auth.hasRole(it.minRole))) return false;
        return true;
      });
      if (!items.length) return;
      html += '<div class="dash-nav-group"><div class="dash-nav-label">' + JONE.esc(g.group).toUpperCase() + '</div>';
      items.forEach((it) => {
        let cls = "dash-nav-item";
        const active = current.endsWith("/" + it.href);
        if (active) cls += " is-active";
        const badge = it.view === "notifications"
          ? '<span class="count notif-count" data-notif-badge hidden></span>' : "";
        html += '<a class="' + cls + '" href="' + it.href + '"' +
          (active ? ' aria-current="page"' : "") +
          ' data-base-label="' + JONE.esc(it.label) + '">' +
          '<span data-icon="' + it.icon + '"></span>' + JONE.esc(it.label) + badge + "</a>";
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
    const name = user.full_name || user.name || user.username || user.email || "Staff";
    const roleRaw = String(user.role || "staff").toLowerCase().replace(/_/g, " ");
    const role = roleRaw.charAt(0).toUpperCase() + roleRaw.slice(1);
    c.innerHTML =
      (user.profile_image_url
        ? '<img class="dash-avatar" src="' + JONE.esc(user.profile_image_url) + '" alt="" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'inline-flex\';">' : '') +
      '<div class="dash-avatar"' + (user.profile_image_url ? ' style="display:none;"' : '') + '>' + JONE.esc(JONE.initials(name)) + "</div>" +
      '<div><div class="dash-user-name">' + JONE.esc(name) + '</div><div class="dash-user-role">' + JONE.esc(role) + "</div></div>";
  }

  /* ------------------------------- Sidebar toggle --------------------------
     THE single dashboard drawer initialization path (spec §3). Idempotent:
     calling it twice never attaches duplicate listeners, so the hamburger
     can never double-toggle. Listeners are delegated on document so they
     survive the icon injector rewriting the toggle button's children, and the
     backdrop element is created here if the page shell didn't include one. */
  let sidebarWired = false;
  function setupSidebar() {
    const sidebar = document.querySelector(".dash-sidebar");
    if (!sidebar) return;

    let backdrop = document.querySelector(".dash-sidebar-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.className = "dash-sidebar-backdrop";
      backdrop.setAttribute("aria-hidden", "true");
      document.body.appendChild(backdrop);
    }
    const toggleBtn = () => document.querySelector(".dash-menu-toggle");
    const t0 = toggleBtn();
    if (t0) {
      t0.setAttribute("aria-expanded", "false");
      t0.setAttribute("aria-controls", "dash-sidebar");
      if (!t0.getAttribute("aria-label")) t0.setAttribute("aria-label", "Open menu");
    }
    if (!sidebar.id) sidebar.id = "dash-sidebar";

    if (sidebarWired) return;   // never attach the document listeners twice
    sidebarWired = true;

    function setOpen(open) {
      const bd = document.querySelector(".dash-sidebar-backdrop") || backdrop;
      sidebar.classList.toggle("open", open);
      bd.classList.toggle("open", open);
      document.body.classList.toggle("drawer-open", open);
      const t = toggleBtn();
      if (t) {
        t.setAttribute("aria-expanded", open ? "true" : "false");
        t.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      }
      if (open) {
        const first = sidebar.querySelector("a, button");
        if (first) { try { first.focus({ preventScroll: true }); } catch (_) { first.focus(); } }
      } else if (t && document.activeElement && sidebar.contains(document.activeElement)) {
        try { t.focus({ preventScroll: true }); } catch (_) { t.focus(); }
      }
    }
    const isOpen = () => sidebar.classList.contains("open");

    document.addEventListener("click", (e) => {
      if (e.target.closest(".dash-menu-toggle")) {
        e.preventDefault();
        setOpen(!isOpen());
        return;
      }
      // Tap backdrop or a nav link closes the drawer.
      if (e.target.closest(".dash-sidebar-backdrop") || e.target.closest(".dash-sidebar a")) {
        if (isOpen()) setOpen(false);
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && isOpen()) setOpen(false);
    });
  }

  /* ---------------------- Unread notification badge -----------------------
     One centralized refresh path (spec §21): a single request per page load
     (plus explicit refreshes after read/mark-all actions), fanned out to
     every badge target — sidebar item, bottom-nav item, topbar control. */
  const notifBadge = (() => {
    let lastCount = null;
    let inflight = null;

    function paint(count) {
      lastCount = count;
      const label = count > 99 ? "99+" : String(count);
      document.querySelectorAll("[data-notif-badge]").forEach((el) => {
        el.textContent = label;
        el.hidden = !(count > 0);
        const host = el.closest("a, button");
        if (host) {
          const base = host.getAttribute("data-base-label") || "Notifications";
          host.setAttribute("aria-label", count > 0 ? base + " (" + count + " unread)" : base);
        }
      });
    }

    async function refresh(force) {
      if (!window.Auth || !window.Auth.isAuthenticated()) return 0;
      if (inflight && !force) return inflight;   // de-duplicate concurrent callers
      inflight = (async () => {
        try {
          const res = await window.API.getUnreadCount();
          const count = (res.data && Number(res.data.unread_count)) || 0;
          paint(count);
          return count;
        } catch (_) {
          return lastCount || 0;   // keep last honest value; no retry storm
        } finally {
          inflight = null;
        }
      })();
      return inflight;
    }

    // Pages that already know the fresh value (notifications page) push it
    // here instead of causing another request.
    function set(count) { paint(Math.max(0, Number(count) || 0)); }

    return { refresh, set, get: () => lastCount };
  })();

  /* -------------------------- Mobile bottom nav ---------------------------
     Fixed bottom navigation for phones (spec §8). Settings is appended ONLY
     for admins — role comes from the authenticated profile and the backend
     enforces authorization regardless. */
  const BOTTOM_NAV = [
    { label: "Dashboard", href: "index.html", icon: "layout" },
    { label: "Bookings", href: "bookings.html", icon: "calendar" },
    { label: "Availability", href: "availability.html", icon: "grid" },
    { label: "Notifications", href: "notifications.html", icon: "bell", badge: true },
    { label: "Settings", href: "settings.html", icon: "settings", role: "admin" },
  ];

  /* Topbar bell with unread badge — same centralized badge fan-out. */
  function renderTopbarBell() {
    const right = document.querySelector(".dash-topbar-right");
    if (!right || right.querySelector("[data-topbar-bell]")) return;
    const a = document.createElement("a");
    a.href = "notifications.html";
    a.className = "btn-icon btn-ghost dash-topbar-bell";
    a.setAttribute("data-topbar-bell", "");
    a.setAttribute("data-base-label", "Notifications");
    a.setAttribute("aria-label", "Notifications");
    a.innerHTML = '<span data-icon="bell" data-size="19"></span><span class="notif-count" data-notif-badge hidden></span>';
    right.insertBefore(a, right.firstChild);
    JONE.icons.inject(a);
  }

  function renderBottomNav() {
    if (document.querySelector(".dash-bottom-nav")) return;   // once per page
    const page = (location.pathname.split("/").pop() || "index.html");
    const items = BOTTOM_NAV.filter((it) =>
      !it.role || (window.Auth && window.Auth.hasRole && window.Auth.hasRole(it.role))
    );
    const nav = document.createElement("nav");
    nav.className = "dash-bottom-nav";
    nav.setAttribute("aria-label", "Dashboard quick navigation");
    nav.innerHTML = items.map((it) => {
      const active = page === it.href;
      return '<a class="dash-bottom-item' + (active ? " is-active" : "") + '" href="' + it.href + '"' +
        (active ? ' aria-current="page"' : "") +
        ' data-base-label="' + JONE.esc(it.label) + '" aria-label="' + JONE.esc(it.label) + '">' +
        '<span class="dash-bottom-icon"><span data-icon="' + it.icon + '" data-size="22"></span>' +
        (it.badge ? '<span class="notif-count" data-notif-badge hidden></span>' : "") +
        '</span><span class="dash-bottom-label">' + JONE.esc(it.label) + "</span></a>";
    }).join("");
    document.body.appendChild(nav);
    document.body.classList.add("has-bottom-nav");
    JONE.icons.inject(nav);
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
        ? '<div class="spinner" role="status"></div><p class="muted">' + JONE.esc(msg || "Loading page") + '</p>'
        : ic + '<h3>' + JONE.esc(title) + '</h3>' + m + (extra || '')) +
      '</div>';
  }

  const DATA = {
    apiBaseConfigured() {
      return !!(window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL);
    },
    // Real column count from the table's own header, so loading/empty/error
    // rows always span the full width regardless of the table layout.
    colCount(el) {
      const table = el && el.closest ? el.closest("table") : null;
      const headRow = table && table.querySelector("thead tr");
      const n = headRow ? headRow.children.length : 0;
      return n || 8;
    },
    loading(el, kind = "table") {
      if (!el) return;
      const tbl = isTable(el);
      el.innerHTML = tbl
        ? '<tr><td colspan="' + DATA.colCount(el) + '">' + stateBody("loading", "", "", "Loading page") + '</td></tr>'
        : stateBody("loading", "", "", "Loading page");
    },
    empty(el, icon, title, msg, colspan) {
      if (!el) return;
      const tbl = isTable(el);
      el.innerHTML = tbl
        ? '<tr><td colspan="' + (colspan || DATA.colCount(el)) + '">' + stateBody("", icon, title, msg) + '</td></tr>'
        : stateBody("", icon, title, msg);
      if (icon || title) JONE.icons.inject(el);
    },
    error(el, title, msg, colspan, showRetry = true) {
      if (!el) return;
      const retry = showRetry ? '<button class="btn btn-sm btn-outline" data-retry style="margin-top:0.75rem;">Try again</button>' : '';
      const tbl = isTable(el);
      el.innerHTML = tbl
        ? '<tr><td colspan="' + (colspan || DATA.colCount(el)) + '">' + stateBody("", "alertTriangle", title, msg, retry) + '</td></tr>'
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
    if (!window.Auth.guard(minRole)) return false;
    renderSidebar("[data-dash-nav]");
    renderUser("[data-dash-user]");
    setupSidebar();
    renderTopbarBell();
    renderBottomNav();
    window.JONE.nav && window.JONE.nav.initDashboardNav();
    if (window.JONE.nav) window.JONE.nav.markActive(document);
    // One badge request per page load, fanned out to every badge target.
    notifBadge.refresh();
    return true;
  }

  /* ------------------------- Image upload field ----------------------------
     Premium drop-zone used by any dashboard form that uploads a picture
     (field type "imagefile"). Shows the CURRENT image when editing, previews a
     newly chosen file immediately, validates type/size client-side for fast
     feedback (the backend stays authoritative) and supports removing the
     existing image where the API allows it.

     Contract with formModal():
       - the chosen File is appended to FormData under the field's own name
       - when the user removes an existing image, `removeName` is appended as
         "true" (the backend field that deletes it, e.g. remove_image)
       - choosing a new file always supersedes a pending removal, so an old
         image can never be submitted by accident. */
  const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
  const IMAGE_EXT_LABEL = "JPG, PNG or WebP";

  function formatBytes(bytes) {
    if (!bytes && bytes !== 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function buildImageField(f, currentUrl) {
    const maxMB = f.maxMB || 5;
    const wrap = document.createElement("div");
    wrap.className = "field img-field";
    wrap.dataset.fmField = f.name;

    const label = document.createElement("label");
    label.className = "field-label";
    label.setAttribute("for", "fm-" + f.name);
    label.textContent = f.label + (f.required ? " *" : "");
    wrap.appendChild(label);

    const zone = document.createElement("div");
    zone.className = "img-drop";

    const input = document.createElement("input");
    input.type = "file";
    input.id = "fm-" + f.name;
    input.name = f.name;
    input.accept = f.accept || IMAGE_TYPES.join(",");
    input.className = "img-drop-input";
    if (f.required && !currentUrl) input.required = true;

    const preview = document.createElement("div");
    preview.className = "img-drop-preview";
    const thumb = document.createElement("img");
    thumb.alt = "";
    thumb.loading = "lazy";
    const meta = document.createElement("div");
    meta.className = "img-drop-meta";
    const metaName = document.createElement("div");
    metaName.className = "img-drop-name";
    const metaInfo = document.createElement("div");
    metaInfo.className = "caption img-drop-info";
    meta.appendChild(metaName);
    meta.appendChild(metaInfo);
    const actions = document.createElement("div");
    actions.className = "img-drop-actions";
    const changeBtn = document.createElement("button");
    changeBtn.type = "button";
    changeBtn.className = "btn btn-sm btn-outline";
    changeBtn.textContent = "Change";
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn btn-sm btn-outline";
    removeBtn.textContent = "Remove";
    actions.appendChild(changeBtn);
    if (f.removeName) actions.appendChild(removeBtn);
    preview.appendChild(thumb);
    preview.appendChild(meta);
    preview.appendChild(actions);

    const empty = document.createElement("div");
    empty.className = "img-drop-empty";
    empty.innerHTML =
      '<span class="img-drop-icon" data-icon="image" data-size="22"></span>' +
      '<div class="img-drop-cta"><strong>Select an image</strong>' +
      '<span class="caption">' + IMAGE_EXT_LABEL + " &middot; up to " + maxMB + " MB</span></div>";

    const err = document.createElement("div");
    err.className = "field-error";

    zone.appendChild(input);
    zone.appendChild(empty);
    zone.appendChild(preview);
    wrap.appendChild(zone);
    if (f.help) {
      const help = document.createElement("div");
      help.className = "hint";
      help.textContent = f.help;
      wrap.appendChild(help);
    }
    wrap.appendChild(err);

    // state: "empty" | "current" (server image) | "selected" (new file) | "removed"
    const state = { mode: currentUrl ? "current" : "empty", file: null, objectUrl: null };

    function releaseObjectUrl() {
      if (state.objectUrl) { URL.revokeObjectURL(state.objectUrl); state.objectUrl = null; }
    }
    function paint() {
      const showPreview = state.mode === "current" || state.mode === "selected";
      zone.classList.toggle("has-image", showPreview);
      preview.style.display = showPreview ? "" : "none";
      empty.style.display = showPreview ? "none" : "";
      removeBtn.textContent = state.mode === "selected" && currentUrl ? "Undo" : "Remove";
      if (state.mode === "current") {
        thumb.src = currentUrl;
        metaName.textContent = "Current image";
        metaInfo.textContent = "Select a new file to replace it.";
      } else if (state.mode === "selected" && state.file) {
        thumb.src = state.objectUrl;
        metaName.textContent = state.file.name;
        metaInfo.textContent = formatBytes(state.file.size) + " · ready to upload";
      } else if (state.mode === "removed") {
        empty.querySelector(".img-drop-cta strong").textContent = "Image will be removed";
      }
    }
    function fail(message) {
      err.textContent = message;
      err.style.display = "block";
      wrap.classList.add("has-error");
    }
    function clearError() {
      err.textContent = "";
      err.style.display = "none";
      wrap.classList.remove("has-error");
    }

    function reject(message) {
      input.value = "";
      releaseObjectUrl();
      state.file = null;
      state.mode = currentUrl ? "current" : "empty";
      paint();
      fail(message);
    }

    function accept(file) {
      clearError();
      if (!file) return;
      // The browser derives file.type from the extension, so these checks are
      // only a fast first pass — the real decode test follows, and the backend
      // validates independently either way.
      if (IMAGE_TYPES.indexOf(file.type) === -1) {
        return reject("Unsupported format. Use " + IMAGE_EXT_LABEL + ".");
      }
      if (!file.size) {
        return reject("That file is empty.");
      }
      if (file.size > maxMB * 1024 * 1024) {
        return reject("That image is " + formatBytes(file.size) + ". The maximum is " + maxMB + " MB.");
      }
      releaseObjectUrl();
      state.file = file;
      state.objectUrl = URL.createObjectURL(file);
      state.mode = "selected";
      paint();

      // Confirm the bytes really are a decodable image (catches a renamed or
      // truncated file before it is ever uploaded).
      const probe = new Image();
      const token = state.objectUrl;
      probe.onload = () => {
        if (state.objectUrl !== token) return;      // superseded by a newer pick
        metaInfo.textContent =
          formatBytes(file.size) + " · " + probe.naturalWidth + "×" + probe.naturalHeight + " · ready to upload";
      };
      probe.onerror = () => {
        if (state.objectUrl !== token) return;
        reject("That file isn't a readable image. Please choose a valid " + IMAGE_EXT_LABEL + " file.");
      };
      probe.src = state.objectUrl;
    }

    input.addEventListener("change", () => accept(input.files && input.files[0]));
    changeBtn.addEventListener("click", () => input.click());
    removeBtn.addEventListener("click", () => {
      clearError();
      if (state.mode === "selected") {
        // Undo the pending selection — restore the server image if there is one.
        releaseObjectUrl();
        state.file = null;
        input.value = "";
        state.mode = currentUrl ? "current" : "empty";
      } else {
        state.mode = currentUrl ? "removed" : "empty";
      }
      paint();
    });
    ["dragenter", "dragover"].forEach((evt) =>
      zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.add("is-dragging"); }));
    ["dragleave", "drop"].forEach((evt) =>
      zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.remove("is-dragging"); }));
    zone.addEventListener("drop", (e) => {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) {
        try { input.files = e.dataTransfer.files; } catch (_) {}
        accept(file);
      }
    });

    paint();
    return {
      wrap,
      /* Append this field's contribution to the outgoing FormData. */
      appendTo(formData) {
        if (state.mode === "selected" && state.file) {
          formData.append(f.name, state.file, state.file.name);
        } else if (state.mode === "removed" && f.removeName) {
          formData.append(f.removeName, "true");
        }
      },
      hasFile: () => state.mode === "selected",
      isRequiredMissing: () => !!f.required && state.mode !== "selected" && state.mode !== "current",
      showError: fail,
      dispose: releaseObjectUrl
    };
  }

  /* --------------------------- Modal form builder --------------------------
     Shared create/edit dialog for dashboard CRUD pages.
     opts: {
       title, submitText,
       fields: [{ name, label, type: text|number|date|select|checkbox|textarea|file|imagefile,
                  options:[{value,label}], value, required, placeholder, help, step, accept,
                  // imagefile only:
                  currentUrl,      // existing image shown as "current" when editing
                  removeName,      // backend flag appended as "true" on removal
                  maxMB }],        // client-side size guard (backend is authoritative)
       values: {name: value},           // prefill (edit mode)
       multipart: bool,                 // include file inputs -> FormData
       onSubmit(values, formData) -> Promise   // throw to keep the dialog open
     }
     Field errors from the backend envelope ({errors:{field:[msgs]}}) are shown
     inline; the dialog only closes after onSubmit resolves. */
  function formModal(opts) {
    return new Promise((resolve) => {
      const backdrop = document.createElement("div");
      backdrop.className = "modal";
      backdrop.innerHTML = '<div class="modal-backdrop" data-fm-cancel></div>';

      const panel = document.createElement("div");
      panel.className = "modal-panel" + (opts.wide ? " modal-lg" : "");
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-modal", "true");
      panel.setAttribute("aria-label", opts.title || "Form");

      const head = document.createElement("div");
      head.className = "modal-head";
      head.innerHTML = '<h3 style="font-size:var(--fs-md);"></h3>' +
        '<button class="btn-icon btn-ghost modal-close" type="button" data-fm-cancel aria-label="Close">' +
        JONE.icons.get("x") + "</button>";
      head.querySelector("h3").textContent = opts.title || "";

      const form = document.createElement("form");
      form.className = "modal-body";
      form.noValidate = true;

      const errBox = document.createElement("div");
      errBox.className = "field-error";
      errBox.style.cssText = "display:none;margin-bottom:0.75rem;font-weight:500;";

      // Image drop-zones are tracked so their files can be added to FormData.
      const imageFields = {};

      (opts.fields || []).forEach((f) => {
        if (f.type === "imagefile") {
          const current = f.currentUrl || (opts.values ? opts.values[f.name + "_url"] : null) || null;
          const built = buildImageField(f, current);
          imageFields[f.name] = built;
          form.appendChild(built.wrap);
          return;
        }
        const wrap = document.createElement("div");
        wrap.className = "field";
        wrap.dataset.fmField = f.name;
        const pre = opts.values ? opts.values[f.name] : f.value;   // prefill (edit mode)
        const label = document.createElement("label");
        label.className = "field-label";
        label.setAttribute("for", "fm-" + f.name);
        label.textContent = f.label + (f.required ? " *" : "");
        wrap.appendChild(label);

        if (f.type === "checks") {
          // Checkbox group — values[f.name] ends up as an array of selected values.
          const group = document.createElement("div");
          group.className = "check-grid";
          group.style.cssText = "display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:0.4rem 0.9rem;padding-top:0.2rem;";
          const preArr = Array.isArray(pre) ? pre.map(String) : [];
          (f.options || []).forEach((o) => {
            const row = document.createElement("label");
            row.style.cssText = "display:flex;align-items:center;gap:0.5rem;font-size:var(--fs-sm);cursor:pointer;";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.dataset.fmCheck = f.name;
            cb.value = o.value;
            cb.checked = preArr.indexOf(String(o.value)) !== -1;
            const sp = document.createElement("span");
            sp.textContent = o.label;
            row.appendChild(cb);
            row.appendChild(sp);
            group.appendChild(row);
          });
          wrap.innerHTML = "";
          wrap.appendChild(label);
          wrap.appendChild(group);
          const ferr2 = document.createElement("div");
          ferr2.className = "field-error";
          wrap.appendChild(ferr2);
          form.appendChild(wrap);
          return;
        }

        let input;
        if (f.type === "select") {
          input = document.createElement("select");
          input.className = "select";
          (f.options || []).forEach((o) => {
            const op = document.createElement("option");
            op.value = o.value;
            op.textContent = o.label;
            input.appendChild(op);
          });
        } else if (f.type === "textarea") {
          input = document.createElement("textarea");
          input.className = "textarea";
          input.rows = f.rows || 3;
        } else if (f.type === "checkbox") {
          input = document.createElement("input");
          input.type = "checkbox";
          input.style.width = "auto";
          input.style.marginRight = "0.5rem";
        } else {
          input = document.createElement("input");
          input.className = "input";
          input.type = f.type || "text";
          if (f.step) input.step = f.step;
          if (f.accept) input.accept = f.accept;
        }
        input.id = "fm-" + f.name;
        input.name = f.name;
        if (f.placeholder) input.placeholder = f.placeholder;
        if (f.required) input.required = true;
        if (f.type === "checkbox") input.checked = pre === true || pre === "true";
        else if (pre != null && pre !== "" && f.type !== "file") input.value = pre;

        if (f.type === "checkbox") {
          const row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;padding:0.45em 0;";
          row.appendChild(input);
          row.appendChild(label);
          label.style.marginBottom = "0";
          label.style.cssText = "font-size:var(--fs-sm);font-weight:500;letter-spacing:0;text-transform:none;margin-bottom:0;cursor:pointer;";
          wrap.innerHTML = "";
          wrap.appendChild(row);
        } else {
          wrap.appendChild(input);
        }

        if (f.help) {
          const help = document.createElement("div");
          help.className = "hint";
          help.textContent = f.help;
          wrap.appendChild(help);
        }
        const ferr = document.createElement("div");
        ferr.className = "field-error";
        wrap.appendChild(ferr);
        form.appendChild(wrap);
      });

      form.appendChild(errBox);

      const foot = document.createElement("div");
      foot.style.cssText = "display:flex;gap:0.6rem;justify-content:flex-end;padding-top:0.5rem;";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "btn btn-outline";
      cancel.textContent = "Cancel";
      cancel.setAttribute("data-fm-cancel", "");
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.className = "btn btn-accent";
      submit.textContent = opts.submitText || "Save";
      foot.appendChild(cancel);
      foot.appendChild(submit);
      form.appendChild(foot);

      panel.appendChild(head);
      panel.appendChild(form);
      backdrop.appendChild(panel);
      document.body.appendChild(backdrop);
      document.body.classList.add("modal-open");
      requestAnimationFrame(() => backdrop.classList.add("open"));
      JONE.icons.inject(panel);
      const first = form.querySelector("input, select, textarea");
      if (first) first.focus();

      function close(result) {
        document.removeEventListener("keydown", onKey);
        // Release any preview object URLs held by image drop-zones.
        Object.keys(imageFields).forEach((k) => imageFields[k].dispose());
        backdrop.classList.remove("open");
        setTimeout(() => {
          backdrop.remove();
          if (!document.querySelector(".modal.open")) document.body.classList.remove("modal-open");
        }, 200);
        resolve(result || null);
      }
      function onKey(e) { if (e.key === "Escape") close(null); }
      document.addEventListener("keydown", onKey);
      backdrop.addEventListener("click", (e) => {
        if (e.target.closest("[data-fm-cancel]")) close(null);
      });

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!JONE.guardSubmit(submit)) return;
        // Clear old errors
        errBox.style.display = "none";
        form.querySelectorAll("[data-fm-field]").forEach((w) => {
          w.classList.remove("has-error");
          const fe = w.querySelector(".field-error");
          if (fe) fe.style.display = "none";
        });
        if (!form.checkValidity()) { form.reportValidity(); JONE.releaseGuard(submit); return; }

        // Required image fields are validated here (a drop-zone has no native
        // constraint once an existing image is already present).
        let imageMissing = false;
        Object.keys(imageFields).forEach((key) => {
          if (imageFields[key].isRequiredMissing()) {
            imageFields[key].showError("Please select an image.");
            imageMissing = true;
          }
        });
        if (imageMissing) { JONE.releaseGuard(submit); return; }

        const values = {};
        let formData = null;
        // A picked image forces multipart regardless of the caller's default.
        const hasImagePayload = Object.keys(imageFields).length > 0;
        if (opts.multipart || hasImagePayload) formData = new FormData();
        (opts.fields || []).forEach((f) => {
          if (f.type === "imagefile") {
            if (formData) imageFields[f.name].appendTo(formData);
            return;
          }
          if (f.type === "checks") {
            const checked = Array.from(form.querySelectorAll('[data-fm-check="' + f.name + '"]:checked')).map((c) => c.value);
            values[f.name] = checked.map(Number);
            if (formData) checked.forEach((v) => formData.append(f.name, v));
            return;
          }
          const el = form.elements[f.name];
          if (!el) return;
          if (f.type === "checkbox") {
            values[f.name] = el.checked;
            if (formData) formData.append(f.name, el.checked);
          } else if (f.type === "file") {
            if (el.files && el.files[0]) {
              values[f.name] = el.files[0];
              formData.append(f.name, el.files[0], el.files[0].name);
            }
          } else {
            values[f.name] = el.value;
            if (formData && el.value !== "") formData.append(f.name, el.value);
          }
        });

        try {
          const out = await opts.onSubmit(values, formData);
          JONE.releaseGuard(submit);
          close(out === undefined ? true : out);
        } catch (err) {
          JONE.releaseGuard(submit);
          // Field-level errors from the backend envelope
          const errs = err && err.data && err.data.errors;
          if (errs && typeof errs === "object") {
            Object.keys(errs).forEach((k) => {
              const w = form.querySelector('[data-fm-field="' + k + '"]');
              const msg = Array.isArray(errs[k]) ? errs[k].join(" ") : String(errs[k]);
              if (w) {
                w.classList.add("has-error");
                const fe = w.querySelector(".field-error");
                if (fe) { fe.textContent = msg; fe.style.display = "block"; }
              } else {
                errBox.textContent = msg;
                errBox.style.display = "block";
              }
            });
            if (!errBox.textContent) { errBox.textContent = "Please review the highlighted fields."; errBox.style.display = "block"; }
          } else {
            const msg = (err && err.message) || "The request failed. Please try again.";
            errBox.textContent = msg;
            errBox.style.display = "block";
            JONE.ui.toast(msg, "error");
          }
        }
      });
    });
  }

  window.JONE = window.JONE || {};
  window.JONE.dashboard = {
    renderSidebar, renderUser, setupSidebar, renderTopbarBell, renderBottomNav,
    notifBadge, statusPill, boot, topbar, NAV, badge, DATA, formModal
  };
})();
