/**
 * Injected-message handler plugin for llm-webchat.
 *
 * Listens for "injected_message" events on the SSE stream and refreshes
 * the page so the user sees the newly injected message. Preserves any
 * draft text in the message input across the refresh.
 */
window.addEventListener("load", function () {
  "use strict";

  var STORAGE_KEY = "llm_webchat_draft_message";

  // -- Draft preservation across refresh --

  function saveDraft() {
    var textarea = document.querySelector("textarea");
    if (textarea && textarea.value.trim()) {
      try {
        sessionStorage.setItem(STORAGE_KEY, textarea.value);
      } catch (e) {
        // sessionStorage may be unavailable; ignore
      }
    }
  }

  function restoreDraft() {
    var draft;
    try {
      draft = sessionStorage.getItem(STORAGE_KEY);
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      return;
    }
    if (!draft) return;

    // The textarea may not exist immediately after load; poll briefly
    var attempts = 0;
    var maxAttempts = 20;
    var intervalMs = 100;
    var interval = setInterval(function () {
      var textarea = document.querySelector("textarea");
      if (textarea) {
        clearInterval(interval);
        textarea.value = draft;
        textarea.focus();
        // Trigger input event so auto-resize works
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
      } else if (++attempts >= maxAttempts) {
        clearInterval(interval);
      }
    }, intervalMs);
  }

  // Restore any saved draft on load
  restoreDraft();

  // -- Stream event hook --

  $llm.on("stream_event", function (payload) {
    if (payload && payload.event && payload.event.type === "injected_message") {
      saveDraft();
      window.location.reload();
      // Return the event unchanged (it will be ignored by the main switch)
      return payload;
    }
    return payload;
  });
});
