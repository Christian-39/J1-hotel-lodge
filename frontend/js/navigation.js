/* ==========================================================================
   Header / navigation behaviour — sticky transitions, mobile drawer, active
   link highlighting, dashboard sidebar, auto-injected component chrome.
   ========================================================================== */

(function () {
  "use strict";

  function initPublicHeader() {
    const header = document.querySelector(".site-header");
    if (!header) return;

    // Sticky shrink
    const onScroll = JONE.throttle(() => {
      header.classList.toggle("scrolled", window.scrollY > 12);
    }, 80);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    // Mobile drawer
    const drawer = document.querySelector(".mobile-drawer");
    const backdrop = document.querySelector(".mobile-drawer-backdrop");
    const toggle = document.querySelector(".menu-toggle");
    if (!drawer || !toggle) return;

    const setOpen = (open) => {
      drawer.classList.toggle("open", open);
      drawer.setAttribute("aria-hidden", open ? "false" : "true");
      if (backdrop) backdrop.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      // Lock background scroll while the drawer is open; restore on close.
      document.body.classList.toggle("modal-open", open);
      if (open) {
        const first = drawer.querySelector("[data-drawer-close]") || drawer.querySelector("a, button");
        first && first.focus();
      } else {
        toggle.focus();
      }
    };

    toggle.addEventListener("click", () => {
      setOpen(!drawer.classList.contains("open"));
    });
    // The drawer's own close (×) button — explicitly bound, never assumed.
    drawer.querySelectorAll("[data-drawer-close]").forEach((b) => {
      b.addEventListener("click", () => setOpen(false));
    });
    if (backdrop) backdrop.addEventListener("click", () => setOpen(false));
    document.addEventListener("click", (e) => {
      if (e.target.closest(".mobile-drawer") === null && e.target.closest(".menu-toggle") === null) {
        if (drawer.classList.contains("open")) setOpen(false);
      }
    });
    // Escape closes the drawer from anywhere on the page.
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && drawer.classList.contains("open")) {
        setOpen(false);
      }
    });
    // Close when a nav item is chosen
    drawer.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => setOpen(false)));
  }

  /* Mark the active nav link based on the current path.
     A link is active when the current page path matches its href (ignoring any
     hash fragment). Works for the desktop header, the mobile drawer, and any
     element carrying data-nav. */
  function markActive(root = document) {
    let path = location.pathname.replace(/\/+$/g, "") || "/";
    if (path === "") path = "/index.html";
    root.querySelectorAll("[data-nav]").forEach((a) => {
      const rawHref = a.getAttribute("href") || "";
      const href = rawHref.split("#")[0].split("?")[0].replace(/\/+$/g, "");
      a.classList.remove("is-active");
      if (!href) {
        // Same-page anchor (e.g. index.html section): active only on that page.
        if (path === "/index.html" || path === "/") a.classList.add("is-active");
        return;
      }
      const hrefNorm = "/" + href;
      if (path === hrefNorm || path.endsWith(hrefNorm)) {
        a.classList.add("is-active");
      }
    });
  }

  /* Dashboard sidebar mobile drawer + active on desktop. */
  function initDashboardNav() {
    // Dashboard pages also need hotel info (e.g. the timezone that drives
    // date defaults on availability/check-in pages).
    if (window.JONE && window.JONE.hotel) window.JONE.hotel.init();
    const sidebar = document.querySelector(".dash-sidebar");
    const toggle = document.querySelector(".dash-menu-toggle");
    const backdrop = document.querySelector(".dash-sidebar-backdrop");
    if (!sidebar) return;
    if (!backdrop) {
      const b = JONE.el("div", { class: "dash-sidebar-backdrop" });
      document.body.appendChild(b);
      const back = document.querySelector(".dash-sidebar-backdrop");
      back && back.addEventListener("click", close);
    } else {
      backdrop.addEventListener("click", close);
    }
    function close() {
      sidebar.classList.remove("open");
      const b = document.querySelector(".dash-sidebar-backdrop");
      if (b) b.classList.remove("open");
      document.body.classList.remove("modal-open");
    }
    toggle && toggle.addEventListener("click", () => {
      const open = !sidebar.classList.contains("open");
      sidebar.classList.toggle("open", open);
      const b = document.querySelector(".dash-sidebar-backdrop");
      if (b) b.classList.toggle("open", open);
      document.body.classList.toggle("modal-open", open);
    });
    sidebar.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  }

  /* Render the running year in any [data-year] element. */
  function initYear() {
    document.querySelectorAll("[data-year]").forEach((n) => { n.textContent = new Date().getFullYear(); });
  }

  /* Render a configured WhatsApp link if phone is set. */
  function renderContact(pointers, settings) {
    if (!settings) return;
    const fillAll = (sel, val) => { if (val) document.querySelectorAll(sel).forEach(n => n.textContent = val); };
    fillAll("[data-contact-phone]", settings.phone);
    fillAll("[data-contact-email]", settings.email);
    fillAll("[data-contact-address]", settings.address);
    if (settings.google_maps_url) {
      document.querySelectorAll("[data-google-maps]").forEach(n => n.setAttribute("href", settings.google_maps_url));
    } else {
      document.querySelectorAll("[data-google-maps]").forEach(n => { n.style.display = "none"; });
    }
    const wa = settings.whatsapp ? String(settings.whatsapp).replace(/\D/g, "") : "";
    if (wa) {
      document.querySelectorAll("[data-contact-whatsapp]").forEach(n => n.setAttribute("href", "https://wa.me/" + wa));
    } else {
      document.querySelectorAll("[data-contact-whatsapp]").forEach(n => { n.style.display = "none"; });
    }
    window.HOTEL = settings;
  }

  function init() {
    initPublicHeader();
    markActive(document);
    initYear();
    // Centralized hotel-info hydration (see hotel-data.js). Non-blocking + graceful.
    if (window.JONE && window.JONE.hotel) {
      window.JONE.hotel.init();
    } else {
      loadHotelChrome();
    }
  }

  async function loadHotelChrome() {
    try {
      const res = await window.API.getHotelInfo();
      const settings = res.data && (res.data.settings || res.data);
      if (settings) {
        window.HOTEL = settings;
        renderContact({}, settings);
        document.querySelectorAll("[data-hotel-name]").forEach(n => n.textContent = settings.name);
        document.dispatchEvent(new CustomEvent("jone:hotel", { detail: settings }));
      }
    } catch (_) {
      // API unreachable — keep the safe defaults already rendered inline.
    }
  }

  window.JONE.nav = { init, initDashboardNav, markActive, initYear, loadHotelChrome };
  window.JONE.renderContact = renderContact;
})();
