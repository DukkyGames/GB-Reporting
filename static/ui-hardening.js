(function () {
  "use strict";

  // Prevent double submission on forms (cache refresh, CSV import, login).
  function initSubmitGuards() {
    document.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (form.dataset.submitting === "1") {
          event.preventDefault();
          return;
        }
        form.dataset.submitting = "1";
        const buttons = form.querySelectorAll('button[type="submit"]');
        buttons.forEach((btn) => {
          btn.disabled = true;
          btn.setAttribute("aria-busy", "true");
        });
      });
    });
  }

  // Warn when custom range has start after end before autosubmit reloads the page.
  function initDateRangeValidation() {
    document.querySelectorAll("form.date-form").forEach((form) => {
      const rangeSelect = form.querySelector("select[name='range']");
      const startInput = form.querySelector("input[name='start']");
      const endInput = form.querySelector("input[name='end']");
      if (!startInput || !endInput) return;

      const validate = () => {
        if (rangeSelect && rangeSelect.value !== "custom") {
          startInput.setCustomValidity("");
          endInput.setCustomValidity("");
          return true;
        }
        const start = startInput.value;
        const end = endInput.value;
        if (start && end && start > end) {
          endInput.setCustomValidity("End date must be on or after the start date.");
          return false;
        }
        endInput.setCustomValidity("");
        return true;
      };

      const onChange = () => {
        if (!validate()) {
          endInput.reportValidity();
        }
      };

      startInput.addEventListener("change", onChange);
      endInput.addEventListener("change", onChange);
      form.addEventListener("submit", (event) => {
        if (!validate()) {
          event.preventDefault();
          endInput.reportValidity();
        }
      });
    });
  }

  // Tock CSV: extension and a rough size ceiling before upload hits the server.
  function initCsvUploadValidation() {
    const form = document.querySelector('form[action*="tours/upload"]');
    if (!form) return;
    const input = form.querySelector('input[name="tock_csv"]');
    if (!input) return;
    const maxBytes = 50 * 1024 * 1024;

    form.addEventListener("submit", (event) => {
      const file = input.files && input.files[0];
      if (!file) return;
      const name = (file.name || "").toLowerCase();
      if (!name.endsWith(".csv")) {
        event.preventDefault();
        input.setCustomValidity("Choose a .csv file exported from Tock.");
        input.reportValidity();
        return;
      }
      if (file.size > maxBytes) {
        event.preventDefault();
        input.setCustomValidity("File is too large. Maximum size is 50 MB.");
        input.reportValidity();
        return;
      }
      input.setCustomValidity("");
    });
  }

  // Announce flash messages to screen readers.
  function initFlashAccessibility() {
    document.querySelectorAll(".flash").forEach((node) => {
      const isError = node.classList.contains("error");
      node.setAttribute("role", isError ? "alert" : "status");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSubmitGuards();
    initDateRangeValidation();
    initCsvUploadValidation();
    initFlashAccessibility();
  });
})();
