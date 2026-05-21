(function () {
  const GB_CHART_FONT = "Arial, sans-serif";

  window.gbChartLayout = function (layout) {
    return Object.assign({ font: { family: GB_CHART_FONT } }, layout || {});
  };

  window.gbTickFont = function (size) {
    return { family: GB_CHART_FONT, size };
  };
})();
