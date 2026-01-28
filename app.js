const fileInput = document.getElementById('fileInput');
const loadSampleBtn = document.getElementById('loadSample');
const fileMeta = document.getElementById('fileMeta');
const footerNote = document.getElementById('footerNote');

const iconMap = {
  "Net Sales": "icons/Net Sales.png",
  "Total Collected": "icons/Total Collected.png",
  "Orders": "icons/Orders.png",
  "Units Sold": "icons/Units Sold.png",
  "Avg Order Value": "icons/Avg order value.png",
  "Avg Bottle Price": "icons/Average Bottle Price.png",
  "Unique Customers": "icons/Unique Customers.png",
  "Repeat Rate": "icons/Repeat Rate.png",
  "Avg Bottles / Customer": "icons/Average bottles Cust.png",
  "Shipped Orders": "icons/Shipped orders.png",
  "Pickup Orders": "icons/Pickup orders.png",
  "Taxes Collected": "icons/Taxes Collected.png",
  "Peak Month": "icons/Peak Month.png",
  "Lowest Month": "icons/Lowest month.png"
};

const samplePath = "data/sales-detail-x-8884389-from-2025-Jan-01-to-2025-Dec-31-on-2026-Jan-27.csv";

const chartRegistry = [];

function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        const next = text[i + 1];
        if (next === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        row.push(field);
        field = "";
      } else if (ch === '\n') {
        row.push(field);
        rows.push(row);
        row = [];
        field = "";
      } else if (ch !== '\r') {
        field += ch;
      }
    }
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  return rows;
}

function parseMoney(value) {
  if (value === null || value === undefined) return 0;
  let s = String(value).replace(/[$,]/g, "").trim();
  if (!s) return 0;
  let negative = false;
  if (s.startsWith("(") && s.endsWith(")")) {
    negative = true;
    s = s.slice(1, -1);
  }
  const num = Number.parseFloat(s);
  if (Number.isNaN(num)) return 0;
  return negative ? -num : num;
}

function parseNumber(value) {
  const num = Number.parseFloat(value);
  return Number.isNaN(num) ? 0 : num;
}

function parsePickup(value) {
  if (value === null || value === undefined) return false;
  const s = String(value).trim().toLowerCase();
  return s === "yes" || s === "true" || s === "1" || s === "y";
}

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function money0(x) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(x || 0);
}

function money2(x) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(x || 0);
}

function pct(x) {
  const value = Number.isFinite(x) ? x : 0;
  return `${(value * 100).toFixed(1)}%`;
}

function monthKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function monthLabel(key) {
  const [year, month] = key.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return date.toLocaleString("en-US", { month: "short", year: "numeric" });
}

function shortLabel(text, max = 6) {
  if (!text) return "";
  const cleaned = String(text).trim();
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max)}…`;
}

function summarizeData(rows) {
  if (!rows.length) return null;
  const headers = rows[0];
  const records = rows.slice(1).map((row) => {
    const obj = {};
    headers.forEach((header, idx) => {
      obj[header] = row[idx];
    });
    return obj;
  });

  const orderMap = new Map();
  const productMap = new Map();
  const customerMap = new Map();

  records.forEach((rec) => {
    const orderNumber = rec["Order Number"];
    if (!orderNumber) return;

    const completedDate = parseDate(rec["Completed Date"]);
    const pickup = parsePickup(rec["Pickup"]);
    const units = parseNumber(rec["Quantity Sold"]);
    const netSales = parseMoney(rec["Ext Item Price"]);
    const orderTotal = parseMoney(rec["Ext Item Total"]);
    const taxes = parseMoney(rec["Ext Item Taxes"]);
    const shippingPaid = parseMoney(rec["Ext Item Shipping"]);

    if (!orderMap.has(orderNumber)) {
      orderMap.set(orderNumber, {
        orderNumber,
        completedDate,
        orderType: rec["Order Type"] || "Unknown",
        shipState: rec["Ship State Code"] || "Unknown",
        customer: rec["Customer Number"] || "",
        pickup,
        units: 0,
        netSales: 0,
        orderTotal: 0,
        taxes: 0,
        shippingPaid: 0
      });
    }

    const order = orderMap.get(orderNumber);
    if (!order.completedDate && completedDate) order.completedDate = completedDate;
    order.units += units;
    order.netSales += netSales;
    order.orderTotal += orderTotal;
    order.taxes += taxes;
    order.shippingPaid += shippingPaid;

    const productSku = (rec["Product SKU"] || rec["Reorder SKU"] || rec["Product Name"] || "Unknown").trim();
    if (!productMap.has(productSku)) {
      productMap.set(productSku, { sku: productSku, units: 0, netSales: 0 });
    }
    const prod = productMap.get(productSku);
    prod.units += units;
    prod.netSales += netSales;

    const customer = rec["Customer Number"] || "";
    if (customer) {
      if (!customerMap.has(customer)) {
        customerMap.set(customer, { customer, units: 0, orders: new Set() });
      }
      const cust = customerMap.get(customer);
      cust.units += units;
      cust.orders.add(orderNumber);
    }
  });

  const orders = Array.from(orderMap.values());
  const totalOrders = orders.length;
  const totalUnits = orders.reduce((sum, o) => sum + o.units, 0);
  const netSales = orders.reduce((sum, o) => sum + o.netSales, 0);
  const orderTotal = orders.reduce((sum, o) => sum + o.orderTotal, 0);
  const taxes = orders.reduce((sum, o) => sum + o.taxes, 0);
  const avgOrderValue = totalOrders ? netSales / totalOrders : 0;
  const avgBottlePrice = totalUnits ? netSales / totalUnits : 0;

  const uniqueCustomers = customerMap.size;
  let repeatCustomers = 0;
  let avgBottlesPerCustomer = 0;
  if (uniqueCustomers) {
    let totalCustomerUnits = 0;
    customerMap.forEach((cust) => {
      totalCustomerUnits += cust.units;
      if (cust.orders.size > 1) repeatCustomers += 1;
    });
    avgBottlesPerCustomer = totalCustomerUnits / uniqueCustomers;
  }
  const repeatRate = uniqueCustomers ? repeatCustomers / uniqueCustomers : 0;

  const pickupCount = orders.filter((o) => o.pickup).length;
  const shippingCount = orders.filter((o) => !o.pickup).length;

  const monthlyMap = new Map();
  orders.forEach((o) => {
    if (!o.completedDate) return;
    const key = monthKey(o.completedDate);
    if (!monthlyMap.has(key)) {
      monthlyMap.set(key, { key, netSales: 0, orders: 0, units: 0 });
    }
    const entry = monthlyMap.get(key);
    entry.netSales += o.netSales;
    entry.orders += 1;
    entry.units += o.units;
  });

  const monthly = Array.from(monthlyMap.values()).sort((a, b) => a.key.localeCompare(b.key));
  const peak = monthly.reduce((best, cur) => (cur.netSales > best.netSales ? cur : best), monthly[0] || { netSales: 0 });
  const low = monthly.reduce((best, cur) => (cur.netSales < best.netSales ? cur : best), monthly[0] || { netSales: 0 });

  const channels = orders.reduce((map, o) => {
    const key = o.orderType || "Unknown";
    map.set(key, (map.get(key) || 0) + o.netSales);
    return map;
  }, new Map());
  const channelList = Array.from(channels, ([label, value]) => ({ label, value }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value);

  const topRevenue = Array.from(productMap.values()).sort((a, b) => b.netSales - a.netSales).slice(0, 10);
  const topUnits = Array.from(productMap.values()).sort((a, b) => b.units - a.units).slice(0, 10);

  const stateMap = new Map();
  orders.filter((o) => !o.pickup).forEach((o) => {
    const state = o.shipState || "Unknown";
    stateMap.set(state, (stateMap.get(state) || 0) + o.netSales);
  });
  const topStates = Array.from(stateMap, ([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value).slice(0, 10);

  return {
    totals: {
      totalOrders,
      totalUnits,
      netSales,
      orderTotal,
      taxes,
      avgOrderValue,
      avgBottlePrice,
      uniqueCustomers,
      repeatCustomers,
      repeatRate,
      avgBottlesPerCustomer,
      pickupCount,
      shippingCount,
      peak,
      low
    },
    monthly,
    channelList,
    topRevenue,
    topUnits,
    topStates
  };
}

function buildKpis(summary) {
  const { totals } = summary;
  const peakLabel = totals.peak && totals.peak.key ? `${monthLabel(totals.peak.key)} (${money0(totals.peak.netSales)})` : "N/A";
  const lowLabel = totals.low && totals.low.key ? `${monthLabel(totals.low.key)} (${money0(totals.low.netSales)})` : "N/A";

  return [
    { label: "Net Sales", value: money0(totals.netSales) },
    { label: "Total Collected", value: money0(totals.orderTotal) },
    { label: "Orders", value: totals.totalOrders.toLocaleString() },
    { label: "Units Sold", value: Math.round(totals.totalUnits).toLocaleString() },
    { label: "Avg Order Value", value: money0(totals.avgOrderValue) },
    { label: "Avg Bottle Price", value: money2(totals.avgBottlePrice) },
    { label: "Unique Customers", value: totals.uniqueCustomers.toLocaleString() },
    { label: "Repeat Rate", value: pct(totals.repeatRate) },
    { label: "Avg Bottles / Customer", value: totals.avgBottlesPerCustomer.toFixed(1) },
    { label: "Shipped Orders", value: totals.shippingCount.toLocaleString() },
    { label: "Pickup Orders", value: totals.pickupCount.toLocaleString() },
    { label: "Taxes Collected", value: money0(totals.taxes) },
    { label: "Peak Month", value: peakLabel },
    { label: "Lowest Month", value: lowLabel }
  ];
}

function renderKpis(kpis) {
  const grid = document.getElementById("kpiGrid");
  grid.innerHTML = "";
  kpis.forEach((kpi) => {
    const tile = document.createElement("div");
    tile.className = "kpi-tile";
    const img = document.createElement("img");
    img.src = iconMap[kpi.label] || "";
    img.alt = kpi.label;
    const body = document.createElement("div");
    const value = document.createElement("div");
    value.className = "kpi-value";
    value.textContent = kpi.value;
    const label = document.createElement("div");
    label.className = "kpi-label";
    label.textContent = kpi.label;
    body.append(value, label);
    tile.append(img, body);
    grid.append(tile);
  });
}

function createSVG(viewBox, content) {
  return `<svg viewBox="${viewBox}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">${content}</svg>`;
}

function barChartSVG(labels, values, opts = {}) {
  const width = 100;
  const height = opts.height || 68;
  const padding = Object.assign({ top: 8, right: 6, bottom: 20, left: 8 }, opts.padding || {});
  const labelFont = opts.labelFont || 3.2;
  const valueFont = opts.valueFont || 3.4;
  const rotateLabels = opts.rotateLabels || 0;
  const labelYOffset = opts.labelYOffset || 0;
  const maxValue = Math.max(...values, 1);
  const barAreaWidth = width - padding.left - padding.right;
  const barAreaHeight = height - padding.top - padding.bottom;
  const barWidth = barAreaWidth / values.length;

  let bars = "";
  let text = "";
  let valuesText = "";
  values.forEach((v, i) => {
    const tipLabel = (opts.tooltipLabels && opts.tooltipLabels[i]) || labels[i];
    const barHeight = (v / maxValue) * barAreaHeight;
    const x = padding.left + i * barWidth + barWidth * 0.2;
    const y = height - padding.bottom - barHeight;
    const w = barWidth * 0.6;
    const formatted = opts.format ? opts.format(v) : v.toLocaleString();
    bars += `<rect x="${x}" y="${y}" width="${w}" height="${barHeight}" rx="2" fill="${opts.color || '#0f8da0'}"><title>${tipLabel}: ${formatted}</title></rect>`;
    valuesText += `<text x="${x + w / 2}" y="${Math.max(y - 1.2, 5)}" text-anchor="middle" font-size="${valueFont}" fill="#2c3c43">${formatted}</text>`;
        const labelX = x + w / 2;
    const labelY = height - 6 + labelYOffset;
    const transform = rotateLabels
      ? ` transform="rotate(${rotateLabels} ${labelX} ${labelY})"`
      : "";
    text += `<text x="${labelX}" y="${labelY}" text-anchor="middle" font-size="${labelFont}" fill="#5e6c74"${transform}>${labels[i]}</text>`;
  });

  const axis = `<line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#dbe5e8" stroke-width="0.6" />`;
  return createSVG(`0 0 ${width} ${height}`, axis + bars + valuesText + text);
}

function horizontalBarChartSVG(labels, values, opts = {}) {
  const width = 100;
  const height = opts.height || 68;
  const padding = { top: 8, right: 10, bottom: 8, left: 34 };
  const labelFont = opts.labelFont || 3.2;
  const valueFont = opts.valueFont || 3.2;
  const maxValue = Math.max(...values, 1);
  const barAreaWidth = width - padding.left - padding.right;
  const barAreaHeight = height - padding.top - padding.bottom;
  const barHeight = barAreaHeight / values.length;

  let bars = "";
  let text = "";
  let valuesText = "";
  values.forEach((v, i) => {
    const tipLabel = (opts.tooltipLabels && opts.tooltipLabels[i]) || labels[i];
    const w = (v / maxValue) * barAreaWidth;
    const x = padding.left;
    const y = padding.top + i * barHeight + barHeight * 0.2;
    const h = barHeight * 0.6;
    const formatted = opts.format ? opts.format(v) : v.toLocaleString();
    bars += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="2" fill="${opts.color || '#5c8ef2'}"><title>${tipLabel}: ${formatted}</title></rect>`;
    valuesText += `<text x="${Math.min(x + w + 1.2, width - 4)}" y="${y + h * 0.8}" text-anchor="start" font-size="${valueFont}" fill="#2c3c43">${formatted}</text>`;
    text += `<text x="${padding.left - 2}" y="${y + h * 0.8}" text-anchor="end" font-size="${labelFont}" fill="#5e6c74">${labels[i]}</text>`;
  });

  const axis = `<line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#dbe5e8" stroke-width="0.6" />`;
  return createSVG(`0 0 ${width} ${height}`, axis + bars + valuesText + text);
}

function lineChartSVG(labels, values, opts = {}) {
  const width = 100;
  const height = opts.height || 68;
  const padding = Object.assign({ top: 8, right: 6, bottom: 20, left: 8 }, opts.padding || {});
  const labelFont = opts.labelFont || 3.2;
  const valueFont = opts.valueFont || 3.3;
  const maxValue = Math.max(...values, 1);
  const minValue = Math.min(...values, 0);
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  const points = values.map((v, i) => {
    const x = padding.left + (i / Math.max(values.length - 1, 1)) * chartWidth;
    const y = padding.top + (1 - (v - minValue) / (maxValue - minValue || 1)) * chartHeight;
    return [x, y];
  });

  const linePath = points.map((p, idx) => `${idx === 0 ? 'M' : 'L'}${p[0]} ${p[1]}`).join(' ');
  const areaPath = `${linePath} L ${padding.left + chartWidth} ${height - padding.bottom} L ${padding.left} ${height - padding.bottom} Z`;

  const axis = `<line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#dbe5e8" stroke-width="0.6" />`;
  const area = `<path d="${areaPath}" fill="${opts.area || 'rgba(15, 141, 160, 0.18)'}" />`;
  const line = `<path d="${linePath}" fill="none" stroke="${opts.color || '#0f8da0'}" stroke-width="1.2" />`;

  let text = "";
  let valueLabels = "";
  let dots = "";
  labels.forEach((label, i) => {
    const x = padding.left + (i / Math.max(labels.length - 1, 1)) * chartWidth;
    const y = points[i][1];
    const val = opts.format ? opts.format(values[i]) : values[i].toLocaleString();
    dots += `<circle cx="${x}" cy="${y}" r="1.6" fill="${opts.color || '#0f8da0'}"><title>${labels[i]}: ${val}</title></circle>`;
    valueLabels += `<text x="${x}" y="${Math.max(y - 2.2, 5)}" text-anchor="middle" font-size="${valueFont}" fill="#2c3c43">${val}</text>`;
    text += `<text x="${x}" y="${height - 6}" text-anchor="middle" font-size="${labelFont}" fill="#5e6c74">${label}</text>`;
  });

  return createSVG(`0 0 ${width} ${height}`, axis + area + line + dots + valueLabels + text);
}

function comboChartSVG(labels, bars, line, opts = {}) {
  const width = 100;
  const height = opts.height || 68;
  const padding = Object.assign({ top: 8, right: 6, bottom: 20, left: 8 }, opts.padding || {});
  const labelFont = opts.labelFont || 3.0;
  const valueFont = opts.valueFont || 3.1;
  const maxValue = Math.max(...bars, ...line, 1);
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const barWidth = chartWidth / bars.length;

  let barShapes = "";
  let barLabels = "";
  bars.forEach((v, i) => {
    const barHeight = (v / maxValue) * chartHeight;
    const x = padding.left + i * barWidth + barWidth * 0.2;
    const y = height - padding.bottom - barHeight;
    const w = barWidth * 0.6;
    barShapes += `<rect x="${x}" y="${y}" width="${w}" height="${barHeight}" rx="2" fill="#7dd3d6"><title>${labels[i]} Orders: ${bars[i].toLocaleString()}</title></rect>`;
    barLabels += `<text x="${x + w / 2}" y="${Math.max(y - 1.4, 5)}" text-anchor="middle" font-size="${valueFont}" fill="#2c3c43">${bars[i].toLocaleString()}</text>`;
  });

  const points = line.map((v, i) => {
    const x = padding.left + (i / Math.max(line.length - 1, 1)) * chartWidth;
    const y = padding.top + (1 - v / maxValue) * chartHeight;
    return [x, y];
  });

  const linePath = points.map((p, idx) => `${idx === 0 ? 'M' : 'L'}${p[0]} ${p[1]}`).join(' ');
  const lineShape = `<path d="${linePath}" fill="none" stroke="#f7b44a" stroke-width="1.2" />`;
  const dots = points
    .map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="1.4" fill="#f7b44a"><title>${labels[i]} Units: ${line[i].toLocaleString()}</title></circle>`)
    .join('');
  const lineLabels = points
    .map((p, i) => `<text x="${p[0]}" y="${Math.max(p[1] - 2.2, 5)}" text-anchor="middle" font-size="${valueFont}" fill="#2c3c43">${line[i].toLocaleString()}</text>`)
    .join('');

  let text = "";
  labels.forEach((label, i) => {
    const x = padding.left + (i / Math.max(labels.length - 1, 1)) * chartWidth;
    text += `<text x="${x}" y="${height - 6}" text-anchor="middle" font-size="${labelFont}" fill="#5e6c74">${label}</text>`;
  });

  const axis = `<line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#dbe5e8" stroke-width="0.6" />`;
  return createSVG(`0 0 ${width} ${height}`, axis + barShapes + barLabels + lineShape + dots + lineLabels + text);
}

function donutChartSVG(values, colors) {
  const total = values.reduce((sum, v) => sum + v, 0) || 1;
  const cx = 50;
  const cy = 34;
  const radius = 19;
  let angle = -90;
  let paths = "";

  values.forEach((value, idx) => {
    const slice = (value / total) * 360;
    const end = angle + slice;
    const largeArc = slice > 180 ? 1 : 0;
    const startRad = (Math.PI / 180) * angle;
    const endRad = (Math.PI / 180) * end;
    const x1 = cx + radius * Math.cos(startRad);
    const y1 = cy + radius * Math.sin(startRad);
    const x2 = cx + radius * Math.cos(endRad);
    const y2 = cy + radius * Math.sin(endRad);

    const label = idx === 0 ? "Repeat Customers" : "New Customers";
    paths += `<path d="M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z" fill="${colors[idx]}"><title>${label}: ${value.toLocaleString()}</title></path>`;
    angle = end;
  });

  const hole = `<circle cx="${cx}" cy="${cy}" r="10.5" fill="#ffffff" />`;
  const totalText = `<text x="50" y="36" text-anchor="middle" font-size="5.6" fill="#2c3c43">${values.reduce((sum, v) => sum + v, 0).toLocaleString()}</text>`;
  const caption = `<text x="50" y="42.5" text-anchor="middle" font-size="3.2" fill="#5e6c74">Customers</text>`;
  const leftLabel = `<text x="30" y="61" text-anchor="middle" font-size="3.2" fill="#2c3c43">${values[0].toLocaleString()}</text>`;
  const rightLabel = `<text x="70" y="61" text-anchor="middle" font-size="3.2" fill="#2c3c43">${values[1].toLocaleString()}</text>`;
  return createSVG("0 0 100 68", paths + hole + totalText + caption + leftLabel + rightLabel);
}

function setChart(id, svg) {
  const container = document.getElementById(id);
  container.innerHTML = svg;
}

function renderTable(monthly) {
  const tbody = document.querySelector("#monthlyTable tbody");
  tbody.innerHTML = "";
  monthly.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${monthLabel(row.key)}</td>
      <td>${money0(row.netSales)}</td>
      <td>${row.orders.toLocaleString()}</td>
      <td>${Math.round(row.units).toLocaleString()}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderDashboard(summary) {
  const kpis = buildKpis(summary);
  renderKpis(kpis);

  const monthLabels = summary.monthly.map((m) => monthLabel(m.key).slice(0, 3));
  const monthSales = summary.monthly.map((m) => m.netSales);
  const monthOrders = summary.monthly.map((m) => m.orders);
  const monthUnits = summary.monthly.map((m) => m.units);

  setChart("chartMonthlyNet", lineChartSVG(monthLabels, monthSales, { format: money0, labelFont: 2.5, valueFont: 2 }));
  setChart("chartOrdersUnits", comboChartSVG(monthLabels, monthOrders, monthUnits, { labelFont: 2.5, valueFont: 2 }));

  setChart(
    "chartChannel",
    barChartSVG(
      summary.channelList.map((c) => c.label),
      summary.channelList.map((c) => c.value),
      { color: "#0f8da0", format: money0, labelFont: 2.4, valueFont: 2.6, padding: { bottom: 30 }, height: 76, tooltipLabels: summary.channelList.map((c) => c.label) }
    )
  );

  setChart(
    "chartTopRevenue",
    horizontalBarChartSVG(
      summary.topRevenue.map((p) => p.sku.slice(0, 18)),
      summary.topRevenue.map((p) => p.netSales),
      { color: "#5c8ef2", format: money0, labelFont: 3, valueFont: 3.1, tooltipLabels: summary.topRevenue.map((p) => p.sku) }
    )
  );

  setChart(
    "chartTopUnits",
    horizontalBarChartSVG(
      summary.topUnits.map((p) => p.sku.slice(0, 18)),
      summary.topUnits.map((p) => p.units),
      { color: "#f7b44a", labelFont: 3, valueFont: 3.1, tooltipLabels: summary.topUnits.map((p) => p.sku) }
    )
  );

  setChart(
    "chartStates",
    barChartSVG(
      summary.topStates.map((s) => s.label),
      summary.topStates.map((s) => s.value),
      { color: "#0b6c7c", format: money0, labelFont: 3, valueFont: 2, tooltipLabels: summary.topStates.map((s) => s.label) }
    )
  );

  const repeat = summary.totals.repeatCustomers;
  const unique = summary.totals.uniqueCustomers - repeat;
  const donut = donutChartSVG([repeat, unique], ["#0f8da0", "#dbe5e8"]);
  setChart("chartCustomerMix", donut);

  renderTable(summary.monthly);

  footerNote.textContent = "Report generated";
}

function handleCSV(text, label) {
  const rows = parseCSV(text);
  const summary = summarizeData(rows);
  if (!summary) {
    footerNote.textContent = "No rows detected in CSV";
    return;
  }

  renderDashboard(summary);
  fileMeta.textContent = label || "File loaded";
}

fileInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    handleCSV(e.target.result, file.name);
  };
  reader.readAsText(file);
});

async function loadSample() {
  try {
    const response = await fetch(samplePath);
    if (!response.ok) throw new Error("Sample fetch failed");
    const text = await response.text();
    handleCSV(text, "Sample CSV");
  } catch (err) {
    footerNote.textContent = "Unable to load sample. Please upload the CSV manually.";
  }
}

loadSampleBtn.addEventListener("click", loadSample);

footerNote.textContent = "Loading sample CSV...";
loadSample();












