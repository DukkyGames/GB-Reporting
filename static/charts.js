(function () {
  // Plotly styling aligned with grimmsbluff.events / gb-styles.css (gold on dark)
  const GB_CHART_FONT = '"Jost", system-ui, sans-serif';

  const PALETTES = {
    dark: {
      primary: "#c4874a",
      secondary: "#8a7f72",
      highlight: "#ede8e0",
      tertiary: "#5c534e",
      fill: "rgba(196, 135, 74, 0.18)",
      muted: "#6e6560",
      text: "#ede8e0",
      tick: "#8a7f72",
      grid: "rgba(237, 232, 224, 0.1)",
    },
    light: {
      primary: "#9a6b2f",
      secondary: "#5a7268",
      highlight: "#6f5340",
      tertiary: "#5a6272",
      fill: "rgba(154, 107, 47, 0.12)",
      muted: "#9aada3",
      text: "#2a221c",
      tick: "#6f6760",
      grid: "#e5dfd4",
    },
  };

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function applyPalette(theme) {
    const key = theme === "light" ? "light" : "dark";
    window.GB_CHART_COLORS = Object.assign({}, PALETTES[key]);
  }

  applyPalette(currentTheme());

  window.gbChartLayout = function (layout) {
    const C = window.GB_CHART_COLORS;
    return Object.assign(
      {
        font: { family: GB_CHART_FONT, color: C.text },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        colorway: [C.primary, C.secondary, C.highlight, C.tertiary, C.muted],
      },
      layout || {}
    );
  };

  window.gbTickFont = function (size) {
    const C = window.GB_CHART_COLORS;
    return { family: GB_CHART_FONT, size, color: C.tick };
  };

  window.gbChartGridColor = function () {
    return window.GB_CHART_COLORS.grid;
  };

  window.gbApplyChartTheme = function (theme) {
    applyPalette(theme);
  };
})();
