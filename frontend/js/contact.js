/* ==========================================================================
   contact.js — the ONE public contact/enquiry submission path.

   contact.html loads this file explicitly; js/site.js deliberately does NOT
   bind the same form any more (two listeners meant one click fired two POSTs
   and created two enquiries).

   Behaviour:
     • submits through the central API layer (window.API.submitEnquiry)
     • blocks duplicate submissions (button disabled + "Sending…")
     • success is only announced AFTER the backend confirms 201
     • backend validation messages are shown verbatim (never flattened into
       "Something went wrong")
     • network failures get their own honest message
   ========================================================================== */

(function () {
  "use strict";

  var form = document.querySelector("[data-contact-form]");
  if (!form) return;

  var btn = form.querySelector("[type=submit]");
  var errBox = form.querySelector("[data-form-error]");
  var submitting = false;
  var NETWORK_MESSAGE = "We couldn't reach the hotel right now. Please try again.";

  function showError(msg) {
    if (errBox) {
      errBox.textContent = msg;
      errBox.style.display = "block";
      errBox.setAttribute("role", "alert");
    }
  }

  function clearError() {
    if (errBox) {
      errBox.textContent = "";
      errBox.style.display = "none";
      errBox.removeAttribute("role");
    }
  }

  /* The form carries `novalidate`, so the checks below are the real gate.
     They mirror the server-side serializer rules (see EnquiryCreateSerializer)
     without ever replacing them — the backend stays authoritative. */
  function validate(values) {
    if (!values.name) return "Please enter your name.";
    if (!values.email) return "Please enter your email address.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(values.email)) return "Please enter a valid email address.";
    if (!values.subject) return "Please choose a subject.";
    if (!values.message) return "Please write your message.";
    if (values.message.length < 5) return "Please enter a more detailed message.";
    return null;
  }

  function setBusy(busy) {
    if (!btn) return;
    if (busy) {
      btn.dataset.originalLabel = btn.dataset.originalLabel || btn.textContent;
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      btn.classList.add("is-loading");
      btn.textContent = "Sending…";
    } else {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      btn.classList.remove("is-loading");
      if (btn.dataset.originalLabel) btn.textContent = btn.dataset.originalLabel;
    }
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (submitting) return;                     // never send twice
    clearError();

    var fd = new FormData(form);
    var payload = {
      name: (fd.get("name") || "").trim(),
      email: (fd.get("email") || "").trim(),
      phone: (fd.get("phone") || "").trim(),
      subject: (fd.get("subject") || "").trim(),
      message: (fd.get("message") || "").trim(),
      website: (fd.get("website") || "").trim()   // honeypot — must stay blank
    };

    var problem = validate(payload);
    if (problem) {
      showError(problem);
      var firstBad = form.querySelector("[name=" + (payload.name ? (payload.email ? (payload.subject ? "message" : "subject") : "email") : "name") + "]");
      if (firstBad && firstBad.focus) firstBad.focus();
      return;
    }

    submitting = true;
    setBusy(true);
    try {
      await window.API.submitEnquiry(payload);
      // Reached only on a backend 2xx — the enquiry genuinely exists.
      JONE.ui.toast("Message sent successfully", "success", {
        title: "Thank you",
        message: "We've received your message and will be in touch soon."
      });
      form.reset();
      clearError();
    } catch (err) {
      var status = err && err.status;
      // Backend validation errors carry a human sentence per field
      // (e.g. "Please enter a more detailed message.") — surface that, not a
      // generic failure. A status of 0 means the request never connected.
      var message = status === 0
        ? NETWORK_MESSAGE
        : ((err && err.message) || "We couldn't send your message. Please try again.");
      showError(message);
      // Validation feedback is already on the form beside the button; only a
      // connection failure also gets a toast (the form may be off-screen).
      if (status === 0) JONE.ui.toast(message, "error", { assertive: true });
    } finally {
      submitting = false;
      setBusy(false);
    }
  });
})();
