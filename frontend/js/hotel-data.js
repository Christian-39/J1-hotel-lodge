/* ==========================================================================
   hotel-data.js — centralized, data-driven hotel information.

   The hotel's name, address, phone, email, WhatsApp and Google Maps URL are
   configured in the backend and hydrated into every matching element via
   the [data-hotel-*] attributes. Nothing is hardcoded per page, and every
   matching element is filled (not just the first).

   Caching: safe, non-sensitive configuration is cached in a short-lived
   in-memory cache so pages don't refetch hotel info on every load. It never
   caches secrets and is refreshed on hard navigation.
   ========================================================================== */

(function () {
  "use strict";

  const CACHE_KEY = "jone.hotel.cache";
  const CACHE_TTL = 5 * 60 * 1000; // 5 minutes — safe, non-sensitive config only
  let hot = null;
  let hotAt = 0;

  function norm(raw) {
    // Accept {settings:{...}} or a flat object; tolerate field aliases.
    const s = (raw && (raw.settings || raw)) || {};
    const pick = (...keys) => { for (const k of keys) if (s[k] != null) return s[k]; return null; };
    return {
      name: pick("name", "hotel_name", "display_name") || s.name,
      address: pick("address", "street_address") || null,
      phone: pick("phone", "phone_number", "telephone") || null,
      email: pick("email", "contact_email") || null,
      whatsapp: pick("whatsapp", "whatsapp_number") || null,
      google_maps_url: pick("google_maps_url", "maps_url", "google_maps", "map_url") || null,
      timezone: pick("timezone") || null,
      checkin_time: pick("checkin_time", "check_in_time") || s.checkin_time,
      checkout_time: pick("checkout_time", "check_out_time") || s.checkout_time,
      raw: s
    };
  }

  function loadHot() {
    try { return JSON.parse(localStorage.getItem(CACHE_KEY)); } catch (_) { return null; }
  }
  function saveHot(v) {
    try { localStorage.setItem(CACHE_KEY, JSON.stringify(v)); } catch (_) {}
  }

  async function fetchHotel(fromCache = true) {
    if (fromCache && hot && Date.now() - hotAt < CACHE_TTL) return hot;
    try {
      const res = await window.API.getHotelInfo();
      const settings = norm(res.data);
      hot = settings;
      hotAt = Date.now();
      saveHot(settings);
      return settings;
    } catch (_) {
      // API unreachable: fall back to a previously cached safe value, else null.
      const cached = loadHot();
      if (cached) { hot = cached; return cached; }
      return null;
    }
  }

  /* Hydrate every matching element in the document. */
  function hydrate(settings) {
    if (!settings) return;
    window.HOTEL = settings;

    const fillAll = (sel, val, attr = "textContent") => {
      document.querySelectorAll(sel).forEach((n) => {
        if (!val && val !== "") return; // never blank a configured field with nothing
        if (attr === "textContent") n.textContent = val;
        else n.setAttribute(attr, val);
      });
    };

    const fmtTime = (t) => {
      if (!t) return null;
      const m = /^(\d{1,2}):(\d{2})/.exec(String(t));
      if (!m) return String(t);
      let h = parseInt(m[1], 10);
      const ap = h >= 12 ? "PM" : "AM";
      h = h % 12 || 12;
      return h + ":" + m[2] + " " + ap;
    };
    if (settings.timezone) JONE.hotelTimezone = settings.timezone;
    // Pages that compute date minimums ("today" in hotel time) listen for this
    // so they can re-apply them once the timezone is known (first visit, no cache).
    try { document.dispatchEvent(new CustomEvent("jone:hotel", { detail: { timezone: settings.timezone } })); } catch (_) {}
    fillAll("[data-hotel-name]", settings.name);
    fillAll("[data-contact-phone]", settings.phone);
    fillAll("[data-contact-email]", settings.email);
    fillAll("[data-contact-address]", settings.address);
    fillAll("[data-contact-checkin]", fmtTime(settings.checkin_time));
    fillAll("[data-contact-checkout]", fmtTime(settings.checkout_time));

    // Google Maps: only set a real, configured URL. Never point at a fake one.
    if (settings.google_maps_url) {
      document.querySelectorAll("[data-google-maps]").forEach((n) => n.setAttribute("href", settings.google_maps_url));
    } else {
      document.querySelectorAll("[data-google-maps]").forEach((n) => { n.style.display = "none"; });
    }

    /* Embedded map on the contact page. Source of truth, in order:
       1. A configured google_maps_url that is already an embed URL -> use as-is.
       2. A configured google_maps_url pointing at maps.google.com -> convert to
          an embed URL so it can render inside an iframe.
       3. Otherwise -> embed a query for the hotel's configured ADDRESS.
       If none of these produce a location, the map block hides (no fake map). */
    document.querySelectorAll("[data-contact-map]").forEach((block) => {
      const iframe = block.querySelector("iframe");
      if (!iframe) return;
      let src = "";
      const url = settings.google_maps_url ? String(settings.google_maps_url).trim() : "";
      if (url) {
        try {
          const u = new URL(url, "https://maps.google.com");
          if (u.hostname.includes("google.com") && (u.pathname.includes("/embed") || u.searchParams.get("output") === "embed")) {
            src = url;                                   // already embeddable
          } else if (u.hostname.includes("google.com")) {
            const q = u.searchParams.get("q") || u.searchParams.get("query") || u.pathname.split("/maps/search/").pop() || "";
            src = q ? "https://maps.google.com/maps?q=" + encodeURIComponent(q) + "&output=embed" : "";
          } else {
            src = url;                                   // non-Google map service that allows embedding
          }
        } catch (_) { src = ""; }
      }
      if (!src && settings.address) {
        const parts = [settings.address, settings.city, settings.state, settings.country].filter(Boolean).join(", ");
        src = "https://maps.google.com/maps?q=" + encodeURIComponent(parts) + "&output=embed";
      }
      if (src) {
        iframe.setAttribute("src", src);
        iframe.setAttribute("title", "Map showing " + (settings.name || "the hotel"));
        iframe.setAttribute("loading", "lazy");
        iframe.setAttribute("referrerpolicy", "no-referrer-when-downgrade");
      } else {
        block.style.display = "none";                    // honest: no location configured
      }
    });

    // WhatsApp: build a wa.me link only when configured.
    if (settings.whatsapp) {
      const wa = String(settings.whatsapp).replace(/\D/g, "");
      document.querySelectorAll("[data-contact-whatsapp]").forEach((n) => n.setAttribute("href", "https://wa.me/" + wa));
    } else {
      document.querySelectorAll("[data-contact-whatsapp]").forEach((n) => { n.style.display = "none"; });
    }

    document.dispatchEvent(new CustomEvent("jone:hotel", { detail: settings }));
  }

  /* Public entry: hydrate config then refresh from backend if reachable. */
  async function init() {
    const cached = loadHot() || hot;
    if (cached) { hot = cached; hydrate(cached); }
    try {
      const fresh = await fetchHotel(false);
      if (fresh) hydrate(fresh);
    } catch (_) {}
  }

  window.JONE = window.JONE || {};
  window.JONE.hotel = { init, fetchHotel, hydrate, norm, get: () => hot };
})();
