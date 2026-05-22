(function () {
  "use strict";

  // Collapsible sidebar for narrow viewports: drawer, backdrop, escape, and resize cleanup.
  function initMobileNav() {
    const sidebar = document.getElementById("app-sidebar");
    const toggle = document.querySelector(".nav-toggle");
    const backdrop = document.querySelector(".nav-backdrop");
    if (!sidebar || !toggle || !backdrop) {
      return;
    }

    const mq = window.matchMedia("(max-width: 860px)");

    const setOpen = (open) => {
      document.body.classList.toggle("nav-open", open);
      sidebar.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
      backdrop.hidden = !open;
    };

    const closeNav = () => setOpen(false);

    toggle.addEventListener("click", () => {
      const next = !document.body.classList.contains("nav-open");
      setOpen(next);
      if (next) {
        const firstLink = sidebar.querySelector(".sidebar-nav .nav-link");
        if (firstLink) {
          firstLink.focus();
        }
      }
    });

    backdrop.addEventListener("click", closeNav);

    sidebar.querySelectorAll(".sidebar-nav .nav-link").forEach((link) => {
      link.addEventListener("click", () => {
        if (mq.matches) {
          closeNav();
        }
      });
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && document.body.classList.contains("nav-open")) {
        closeNav();
        toggle.focus();
      }
    });

    const onBreakpointChange = () => {
      if (!mq.matches) {
        closeNav();
      }
    };

    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", onBreakpointChange);
    } else {
      mq.addListener(onBreakpointChange);
    }
  }

  document.addEventListener("DOMContentLoaded", initMobileNav);
})();
