/* ==========================================================================
   J-ONE HOTEL & LODGE — shared "Email guest" receipt modal.

   ONE implementation of the staff receipt-send experience, used by both
   dashboard/receipt-details.html and dashboard/receipts.html so the flow is
   identical everywhere:

     Click "Email Guest"
       → modal opens IMMEDIATELY (never a silent or delayed reaction)
       → guest / booking details are displayed
       → "Send receipt" → visible "Sending receipt…" state + spinner
       → duplicate submission disabled while in flight
       → API request → success / failure
       → "Receipt queued for delivery" (202: honest QUEUED semantics — the
         worker still has to deliver it) or "Receipt sent" (only when the
         mail backend actually accepted the message)
       → failure shows a safe, useful message with a Retry button

   Delivery status wording is deliberately precise:
     QUEUED  → "Receipt queued for delivery"
     SENT    → "Receipt sent"
     FAILED  → "Unable to queue receipt" + reason + Retry
   ========================================================================== */

(function () {
  "use strict";

  window.JONE = window.JONE || {};

  /* Poll the REAL delivery status of a QUEUED receipt so staff learn the true
     outcome (SENT / FAILED) instead of a blind "queued". Bounded attempts. */
  function pollReceiptStatus(logId, onUpdate) {
    var attempts = 0;
    // SMTP retries are scheduled at 30s, 60s and 120s. Keep polling for five
    // minutes so the modal can show the terminal SENT/FAILED state rather than
    // stopping while EmailLog truthfully says RETRYING.
    var max = 60;
    function tick() {
      attempts += 1;
      window.API.getEmailLog(logId).then(function (res) {
        var d = (res && res.data) || {};
        onUpdate(d);
        if (d.status === "SENT" || d.status === "FAILED" || attempts >= max) return;
        setTimeout(tick, 5000);
      }).catch(function () {
        if (attempts < max) setTimeout(tick, 5000);
      });
    }
    setTimeout(tick, 2500);
  }

  function open(opts) {
    opts = opts || {};
    var bookingReference = opts.bookingReference || "";
    var guestName = opts.guestName || "Guest";
    var guestEmail = opts.guestEmail || "";
    if (!bookingReference || !guestEmail) return;

    var status = JONE.el("p", {
      class: "muted", role: "status", "aria-live": "polite",
      textContent: "Ready to send."
    });
    var sendBtn = JONE.el("button", {
      class: "btn btn-accent", type: "button", textContent: "Send receipt"
    });
    var closeBtn = JONE.el("button", {
      class: "btn btn-outline", type: "button", textContent: "Close"
    });

    var summary = JONE.el("dl", { class: "receipt-send-summary" },
      JONE.el("dt", { textContent: "Guest" }),
      JONE.el("dd", { textContent: guestName }),
      JONE.el("dt", { textContent: "Email" }),
      JONE.el("dd", { textContent: guestEmail }),
      JONE.el("dt", { textContent: "Booking" }),
      JONE.el("dd", { textContent: bookingReference }),
      JONE.el("dt", { textContent: "Document" }),
      JONE.el("dd", { textContent: "Payment receipt (PDF attached)" })
    );

    var body = JONE.el("div", { class: "receipt-send-dialog" },
      JONE.el("p", { textContent: "Send payment receipt" }),
      summary,
      status
    );
    var footer = JONE.el("div", { class: "modal-actions" }, closeBtn, sendBtn);

    JONE.ui.modal.open({
      title: "Send payment receipt",
      body: body,
      footer: footer,
      size: "modal-md"
    });

    closeBtn.addEventListener("click", function () { JONE.ui.modal.close(); });

    function setBusy(busy, label) {
      sendBtn.disabled = busy;
      closeBtn.disabled = busy;
      if (busy) {
        sendBtn.setAttribute("aria-busy", "true");
        sendBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> ' + (label || "Sending receipt\u2026");
      } else {
        sendBtn.removeAttribute("aria-busy");
      }
    }

    function succeed(payload) {
      var sent = payload.status === "SENT";
      status.textContent = sent
        ? "Receipt sent — the mail server accepted the message for " + guestEmail + "."
        : "Receipt queued for delivery to " + guestEmail + ".";
      sendBtn.onclick = function () { JONE.ui.modal.close(); };
      JONE.ui.toast(
        sent ? "Receipt sent successfully." : "Receipt queued for delivery.",
        "success"
      );
      if (!sent && payload.email_log_id) {
        pollReceiptStatus(payload.email_log_id, function (d) {
          if (d.status === "SENT") {
            status.textContent = "Receipt sent — the mail server accepted the message for " + guestEmail + ".";
            JONE.ui.toast("Receipt email delivered to " + guestEmail + ".", "success");
          } else if (d.status === "FAILED") {
            if (d.failure_stage === "ATTACHMENT" || d.failure_stage === "RENDER") {
              status.textContent = "The receipt PDF could not be generated. No email was sent.";
            } else if (d.failure_stage === "BROKER") {
              status.textContent = "The receipt could not be queued because the email service is unavailable. No email was sent.";
            } else {
              status.textContent = "Delivery failed: " + (d.error_message || "the mail server rejected the message.");
            }
            JONE.ui.toast("Receipt email could not be delivered.", "error");
          } else if (d.status === "RETRYING") {
            status.textContent = "The email service is retrying a temporary delivery failure.";
          }
        });
      }
    }

    function fail(err) {
      var envelope = err && err.data;
      var details = envelope && envelope.data;
      var stage = (details && details.failure_stage) || "";
      var message;
      if (stage === "BROKER" || (err && err.code === "EMAIL_BROKER_UNAVAILABLE")) {
        message = "The receipt could not be queued because the email service is temporarily unavailable. No email was sent.";
      } else if (stage === "RENDER" || stage === "ATTACHMENT") {
        message = "The receipt PDF could not be generated. No email was sent.";
      } else if (stage === "SMTP") {
        message = (details && details.error) || (err && err.message) ||
          "The email server rejected the message. No email was sent.";
      } else if (err && err.kind === "timeout") {
        message = "The server did not respond in time. Check the email log before retrying because the request may already have been processed.";
      } else if (err && (err.kind === "network" || err.kind === "offline")) {
        message = "No response was received. Check the email log before retrying because the request outcome is unknown.";
      } else {
        message = (err && err.message) || "The receipt could not be processed. No email was sent.";
      }
      status.textContent = message;
      JONE.ui.toast("Receipt email was not confirmed. Review the status before retrying.", "error", { assertive: true });
    }

    sendBtn.addEventListener("click", async function () {
      if (sendBtn.disabled) return;             // duplicate-submit guard
      setBusy(true);
      status.textContent = "Sending receipt\u2026";
      var finalLabel = "Send receipt";
      try {
        var res = await window.API.sendReceipt(bookingReference);
        var payload = (res && res.data) || {};
        if (payload.status === "FAILED") {
          fail({ message: payload.error || "delivery failed at the mail server." });
          finalLabel = "Retry";
        } else if (payload.status === "IN_PROGRESS") {
          status.textContent = "A receipt for this booking is already being processed.";
          if (payload.email_log_id) {
            pollReceiptStatus(payload.email_log_id, function (d) {
              if (d.status === "SENT") {
                status.textContent = "Receipt sent — the mail server accepted the message for " + guestEmail + ".";
              } else if (d.status === "FAILED") {
                status.textContent = "Delivery failed: " + (d.error_message || "no email was sent.");
              }
            });
          }
          sendBtn.textContent = "Done";
          sendBtn.onclick = function () { JONE.ui.modal.close(); };
          finalLabel = "Done";
        } else {
          succeed(payload);
          finalLabel = "Done";
        }
      } catch (err) {
        fail(err);
        finalLabel = "Retry";
      }
      // Always end in a usable state — never a stuck disabled modal.
      sendBtn.disabled = false;
      closeBtn.disabled = false;
      sendBtn.removeAttribute("aria-busy");
      sendBtn.textContent = finalLabel;
    });
  }

  window.JONE.receiptEmailModal = { open: open };
})();
