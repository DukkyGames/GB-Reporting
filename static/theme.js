(function () {
  // Persist and apply light/dark theme (default: dark, matches grimmsbluff.events)
  const STORAGE_KEY = "gb-reporting-theme";

  function getTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function applyTheme(theme, reloadCharts) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEY, theme);
    if (typeof window.gbApplyChartTheme === "function") {
      window.gbApplyChartTheme(theme);
    }
    if (reloadCharts) {
      window.location.reload();
    }
  }

  function syncThemeControls() {
    const theme = getTheme();
    document.querySelectorAll("[data-theme-set]").forEach((btn) => {
      const isActive = btn.getAttribute("data-theme-set") === theme;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function bindThemeControls() {
    document.querySelectorAll("[data-theme-set]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.getAttribute("data-theme-set");
        if (!target || target === getTheme()) {
          return;
        }
        applyTheme(target, true);
      });
    });
    syncThemeControls();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindThemeControls);
  } else {
    bindThemeControls();
  }
})();
