/* ==========================================================================
   contact.js — public contact/enquiry form.
   Submits to the backend via API.submitEnquiry with a real loading state,
   duplicate-submission protection, and success only AFTER the backend
   confirms. Never fakes a "sent" toast.
   ========================================================================== */

(function () {
  "use strict";
  var form = document.querySelector("[data-contact-form]");
  if (!form) return;

  var btn = form.querySelector("[type=submit]");
  var errBox = form.querySelector("[data-form-error]");
  var submitting = false;

  function showError(msg) {
    if (errBox) { errBox.textContent = msg; errBox.style.display = "block"; }
  }
  function clearError() { if (errBox) { errBox.textContent = ""; errBox.style.display = "none"; } }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    clearError();
    if (submitting) return;                       // prevent duplicate sends
    if (!form.checkValidity()) { form.reportValidity(); return; }
    if (!JONE.guardSubmit(btn)) return;

    var fd = new FormData(form);
    var payload = {
      name: (fd.get("name") || "").trim(),
      email: (fd.get("email") || "").trim(),
      phone: (fd.get("phone") || "").trim(),
      subject: (fd.get("subject") || "").trim(),
      message: (fd.get("message") || "").trim(),
      website: (fd.get("website") || "").trim()   // honeypot — must stay blank
    };

    submitting = true;
    try {
      await window.API.submitEnquiry(payload);
      // Only reach here on backend OK — now it is genuinely sent.
      JONE.ui.toast("Thank you! Your message has been sent. We'll be in touch soon.", "success");
      form.reset();
    } catch (err) {
      showError((err && err.status === 0)
        ? "We couldn't reach the hotel right now. Please try again in a moment."
        : ((err && err.message) || "Something went wrong. Please try again."));
      JONE.ui.toast("Your message couldn't be sent. Please try again.", "error");
    } finally {
      submitting = false;
      JONE.releaseGuard(btn);
    }
  });
})();
