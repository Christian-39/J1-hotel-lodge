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
    const name = user.full_name || user.name || user.username || user.email || "Staff";
    const roleRaw = String(user.role || "staff").toLowerCase().replace(/_/g, " ");
    const role = roleRaw.charAt(0).toUpperCase() + roleRaw.slice(1);
    c.innerHTML =
      '<div class="dash-avatar">' + JONE.esc(JONE.initials(name)) + "</div>" +
      '<div><div class="dash-user-name">' + JONE.esc(name) + '</div><div class="dash-user-role">' + JONE.esc(role) + "</div></div>";
  }

  /* ------------------------------- Sidebar toggle --------------------------
     Mobile drawer: the CSS already provides .dash-sidebar.open and
     .dash-sidebar-backdrop.open. Listeners are delegated on document so they
     survive the icon injector rewriting the toggle button's children, and the
     backdrop element is created here if the page shell didn't include one. */
  function setupSidebar() {
    const sidebar = document.querySelector(".dash-sidebar");
    if (!sidebar) return;

    let backdrop = document.querySelector(".dash-sidebar-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.className = "dash-sidebar-backdrop";
      document.body.appendChild(backdrop);
    }

    function open() {
      sidebar.classList.add("open");
      backdrop.classList.add("open");
      const t = document.querySelector(".dash-menu-toggle");
      if (t) t.setAttribute("aria-label", "Close menu");
    }
    function close() {
      sidebar.classList.remove("open");
      backdrop.classList.remove("open");
      const t = document.querySelector(".dash-menu-toggle");
      if (t) t.setAttribute("aria-label", "Open menu");
    }

    document.addEventListener("click", (e) => {
      if (e.target.closest(".dash-menu-toggle")) {
        sidebar.classList.contains("open") ? close() : open();
        return;
      }
      // Tap backdrop or a nav link closes the drawer.
      if (e.target.closest(".dash-sidebar-backdrop") || e.target.closest(".dash-sidebar a")) {
        close();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
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
    setupSidebar();
    window.JONE.nav && window.JONE.nav.initDashboardNav();
    if (window.JONE.nav) window.JONE.nav.markActive(document);
    return true;
  }

  /* --------------------------- Modal form builder --------------------------
     Shared create/edit dialog for dashboard CRUD pages.
     opts: {
       title, submitText,
       fields: [{ name, label, type: text|number|date|select|checkbox|textarea|file,
                  options:[{value,label}], value, required, placeholder, help, step, accept }],
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

      (opts.fields || []).forEach((f) => {
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

        const values = {};
        let formData = null;
        if (opts.multipart) formData = new FormData();
        (opts.fields || []).forEach((f) => {
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
  window.JONE.dashboard = { renderSidebar, renderUser, setupSidebar, statusPill, boot, topbar, NAV, badge, DATA, formModal };
})();
