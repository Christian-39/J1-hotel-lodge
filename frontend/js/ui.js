/* ==========================================================================
   UI layer — toast, modal, confirmation, lightbox, accordions, drop-in icons.
   ========================================================================== */

(function () {
  "use strict";

  /* -------------------------------- Toast --------------------------------- */
  function ensureToastRegion() {
    let region = document.querySelector(".toast-region");
    if (!region) {
      region = JONE.el("div", { class: "toast-region" });
      region.setAttribute("role", "status");
      region.setAttribute("aria-live", "polite");
      document.body.appendChild(region);
    }
    return region;
  }

  const TOAST_ICONS = { success: "checkCircle", error: "alertCircle", warning: "alertTriangle", info: "info" };

  function toast(message, type = "info", opts = {}) {
    const region = ensureToastRegion();
    const icon = JONE.icons.get(TOAST_ICONS[type] || "info");

    // Optional richer layout: a bold title above the message. Used by the
    // booking flow for the "Payment successful" confirmation — same component,
    // same region, just an extra line. Falls back to the plain single-line
    // toast when no title is supplied.
    let body;
    if (opts.title) {
      body = JONE.el("span", { class: "toast-body" },
        JONE.el("span", { class: "toast-title", textContent: opts.title }),
        message ? JONE.el("span", { class: "toast-message", textContent: message }) : null
      );
    } else {
      body = JONE.el("span", { class: "toast-message", textContent: message });
    }

    const node = JONE.el("div", { class: `toast ${type}${opts.title ? " toast-rich" : ""}` },
      JONE.el("span", { class: "toast-icon", innerHTML: icon }),
      body,
      JONE.el("button", {
        class: "toast-close", "aria-label": "Dismiss",
        innerHTML: JONE.icons.get("x")
      })
    );
    // Assertive announcements (e.g. payment success/failure) are read out
    // immediately by screen readers.
    if (opts.assertive) node.setAttribute("aria-live", "assertive");
    node.querySelector(".toast-close").addEventListener("click", () => dismiss());
    region.appendChild(node);

    let timer;
    function dismiss() {
      node.classList.add("hide");
      setTimeout(() => node.remove(), 220);
      clearTimeout(timer);
    }
    const auto = opts.duration ?? (type === "success" ? 4200 : 6000);
    if (auto > 0) timer = setTimeout(dismiss, auto);
    return { node, dismiss };
  }

  /* ------------------------------- Modal ---------------------------------- */
  const modal = {
    focusSentinel: null,