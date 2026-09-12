/* ==========================================================================
   Booking stepper — a reusable, accessible six-stage progress component for
   the J-ONE booking flow. Renders a polished horizontal stepper on desktop
   and a compact "step X of N" progress bar on mobile from ONE data source.

   It never changes booking state or talks to the API — it only visualises
   progress and lets guests jump BACK to completed steps. Forward jumps into
   incomplete steps are deliberately impossible (prevents inconsistent state).

   Usage:
     var stepper = JONE.stepper.mount(el, {
       current: 3,                 // 1-based active step
       criteria: {...},            // stay/room criteria used for back-nav URLs
       onNavigate: function (step, index) {
         // return true if handled in-page (panel switch); falsy => default
         // cross-page navigation using `criteria`.
       }
     });
     stepper.update(6);            // move the active step (e.g. after payment)
   ========================================================================== */
(function () {
  "use strict";

  var STEPS = [
    { key: "stay",         label: "Stay",         title: "Choose your stay",   page: "booking.html" },
    { key: "room",         label: "Room",         title: "Select a room",      page: "booking.html" },
    { key: "guest",        label: "Guest",        title: "Guest information",  page: "booking-review.html" },
    { key: "review",       label: "Review",       title: "Review your booking", page: "booking-review.html" },
    { key: "payment",      label: "Payment",      title: "Secure payment",     page: "booking-confirmation.html" },
    { key: "confirmation", label: "Confirmation", title: "Confirmation",       page: "booking-confirmation.html" }
  ];

  function checkSvg() {
    return (window.JONE && JONE.icons && JONE.icons.get) ? JONE.icons.get("check") : "\u2713";
  }

  // Build a back-navigation URL for a completed step, carrying the known
  // criteria so the destination page hydrates without losing information.
  function backUrl(step, criteria) {
    var c = criteria || {};
    var q = new URLSearchParams();
    if (c.check_in) q.set("check_in", c.check_in);
    if (c.check_out) q.set("check_out", c.check_out);
    if (c.adults != null) q.set("adults", c.adults);
    if (c.children != null) q.set("children", c.children);
    if (c.room) q.set("room", c.room);
    if (c.room_name) q.set("room_name", c.room_name);
    if (c.offer) q.set("offer", c.offer);

    if (step.key === "stay")   { return "booking.html?" + q.toString(); }
    if (step.key === "room")   { q.set("step", "room"); return "booking.html?" + q.toString(); }
    if (step.key === "guest")  { return "booking-review.html?" + q.toString(); }
    if (step.key === "review") { q.set("step", "review"); return "booking-review.html?" + q.toString(); }
    if (step.key === "payment"){ q.set("step", "payment"); return "booking-confirmation.html?" + q.toString(); }
    return step.page;
  }

  function mount(el, opts) {
    if (!el) return { update: function () {} };
    opts = opts || {};
    var current = Math.min(Math.max(1, opts.current || 1), STEPS.length);
    var criteria = opts.criteria || {};
    var onNavigate = typeof opts.onNavigate === "function" ? opts.onNavigate : null;

    // Persistent scaffold (built once); state is toggled via classes so the
    // DOM is never rebuilt on step changes.
    el.classList.add("bk-stepper-shell");
