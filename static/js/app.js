(function () {
  "use strict";

  // Fixed identity per property type: colour AND marker shape, so the
  // series never rely on colour alone.
  const TYPE_STYLES = {
    "Detached":        { colorVar: "--series-1", shape: "circle" },
    "Semi-detached":   { colorVar: "--series-2", shape: "square" },
    "Terraced":        { colorVar: "--series-3", shape: "triangle" },
    "Flat/Maisonette": { colorVar: "--series-4", shape: "diamond" },
  };
  const OTHER_STYLE = { colorVar: "--text-muted", shape: "cross" };
  const TYPE_ORDER = ["Detached", "Semi-detached", "Terraced", "Flat/Maisonette"];

  // Past this many visible points, per-point house-number labels become
  // unreadable soup — the tooltip and table still carry them.
  const LABEL_LIMIT = 250;

  const form = document.getElementById("search-form");
  const statusEl = document.getElementById("status");
  const resultCard = document.getElementById("result-card");
  const resultTitle = document.getElementById("result-title");
  const legendEl = document.getElementById("legend");
  const chartMount = document.getElementById("chart-mount");
  const tooltipEl = document.getElementById("tooltip");
  const tableBody = document.querySelector("#data-table tbody");
  const tableWrap = document.querySelector(".table-wrap");
  const mapToggle = document.getElementById("map-toggle");
  const mapSection = document.getElementById("map-section");
  const mapNote = document.getElementById("map-note");
  const outlierNote = document.getElementById("outlier-note");
  const tableNote = document.getElementById("table-note");

  let allSales = [];
  let resultLabel = "";
  let activeTypes = new Set();
  let map = null;
  let mapMarkersLayer = null;
  let geocodeCache = {};   // property key -> {lat, lng, precision} | null
  let geocodeFailed = false;
  let medianPrice = 0;
  let epcByProperty = {};  // property key -> {rooms, floor_area}
  let zoomDomain = null;   // {x0, x1, y0, y1} in data units, null = fitted
  let isPanning = false;
  let chartMode = "price"; // "price" | "sqm" (price per square metre)
  let showTrend = true;

  function floorAreaOf(s) {
    const e = epcByProperty[propKey(s)];
    return e && e.floor_area ? e.floor_area : null;
  }

  // The value plotted on the y-axis in the current chart mode.
  function yValueOf(s) {
    if (chartMode === "sqm") {
      const area = floorAreaOf(s);
      return area ? s.price / area : null;
    }
    return s.price;
  }

  function formatY(v) {
    if (chartMode === "sqm") return "£" + Math.round(v).toLocaleString("en-GB");
    return formatPrice(v);
  }

  const chartModeEl = document.getElementById("chart-mode");
  chartModeEl.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (chartMode === btn.dataset.mode) return;
      chartMode = btn.dataset.mode;
      chartModeEl.querySelectorAll("button").forEach((b) => {
        b.classList.toggle("is-active", b === btn);
        b.setAttribute("aria-pressed", String(b === btn));
      });
      zoomDomain = null;
      renderAll();
    });
  });

  function propKey(s) {
    return [s.saon, s.paon, s.street, s.postcode].map((v) => v || "").join("|");
  }

  function median(values) {
    const sorted = values.slice().sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const q = (new FormData(form).get("q") || "").trim();
    if (!q) {
      setStatus("Enter a postcode (and optionally a street name).", true);
      return;
    }

    setStatus("Loading from HM Land Registry…", false);
    resultCard.hidden = true;

    try {
      const resp = await fetch("/api/sales?" + new URLSearchParams({ q }).toString());
      const body = await resp.json();
      if (!resp.ok) {
        throw new Error(body.error || "Request failed");
      }
      const sales = (body.sales || []).filter((s) => s.price != null && s.date);
      if (sales.length === 0) {
        setStatus(
          "No sales found for that search." +
          (body.street && !body.postcode
            ? " Street-only searches need the exact full street name (e.g. 'Downing Street', not 'Downing') — adding a postcode allows partial street names."
            : ""),
          true
        );
        return;
      }
      setStatus("", false);

      sales.sort((a, b) => a.date.localeCompare(b.date));
      sales.forEach((s, i) => { s._id = i; });

      medianPrice = median(sales.map((s) => s.price));
      const outlierThreshold = medianPrice * 3;
      sales.forEach((s) => { s._outlier = s.price > outlierThreshold; });

      allSales = sales;
      zoomDomain = null;
      const streetPart = body.street ? (body.paon ? body.paon + " " : "") + body.street : "";
      resultLabel = [body.postcode, streetPart].filter(Boolean).join(" · ");
      activeTypes = new Set(typesPresent(sales));
      geocodeCache = {};
      geocodeFailed = false;
      epcByProperty = {};
      chartMode = "price";
      chartModeEl.hidden = true;
      chartModeEl.querySelectorAll("button").forEach((b) => {
        const active = b.dataset.mode === "price";
        b.classList.toggle("is-active", active);
        b.setAttribute("aria-pressed", String(active));
      });

      resultCard.hidden = false;
      renderAll();
      loadEpc();
      if (!mapSection.hidden) refreshMap();
    } catch (err) {
      setStatus(err.message || "Something went wrong.", true);
    }
  });

  function setStatus(message, isError) {
    statusEl.textContent = message;
    statusEl.classList.toggle("is-error", !!isError);
  }

  function styleFor(type) {
    return TYPE_STYLES[type] || OTHER_STYLE;
  }

  function typeKey(sale) {
    return sale.property_type || "Other";
  }

  function typesPresent(sales) {
    const present = new Set(sales.map(typeKey));
    const ordered = TYPE_ORDER.filter((t) => present.has(t));
    for (const t of present) {
      if (!TYPE_ORDER.includes(t)) ordered.push(t);
    }
    return ordered;
  }

  // Rows shown in the table: legend-filtered, outliers included (greyed).
  function tableSales() {
    return allSales.filter((s) => activeTypes.has(typeKey(s)));
  }

  // Points plotted on the chart: legend-filtered, outliers excluded, and in
  // £/m² mode only sales with a known floor area.
  function chartSales() {
    return tableSales().filter((s) => !s._outlier && yValueOf(s) != null);
  }

  function renderAll() {
    const plotted = chartSales();
    const shown = tableSales();
    const outliers = shown.filter((s) => s._outlier).length;
    const noArea = chartMode === "sqm"
      ? shown.filter((s) => !s._outlier && yValueOf(s) == null).length
      : 0;

    resultTitle.textContent =
      resultLabel + " — " + plotted.length + (plotted.length === 1 ? " sale" : " sales") +
      (plotted.length !== allSales.length ? " of " + allSales.length : "");

    const noteParts = [];
    if (outliers > 0) {
      noteParts.push(
        outliers + (outliers === 1 ? " sale" : " sales") + " above 3× the median price (" +
        formatPrice(medianPrice) + " median) excluded from the chart — greyed out in the table below");
    }
    if (noArea > 0) {
      noteParts.push(
        noArea + (noArea === 1 ? " sale" : " sales") + " without EPC floor area hidden in the £/m² view");
    }
    outlierNote.hidden = noteParts.length === 0;
    outlierNote.textContent = noteParts.join(". ") + (noteParts.length ? "." : "");

    renderLegend();
    renderTable(shown);
    renderChart(plotted);
    if (!mapSection.hidden) renderMapMarkers();
  }

  // ---- Legend: one toggle button per property type ----

  function renderLegend() {
    legendEl.innerHTML = "";
    const types = typesPresent(allSales);
    if (types.length === 0) {
      legendEl.setAttribute("aria-hidden", "true");
      return;
    }
    legendEl.removeAttribute("aria-hidden");
    for (const type of types) {
      const st = styleFor(type);
      const item = document.createElement("button");
      item.type = "button";
      item.className = "legend-item";
      const on = activeTypes.has(type);
      if (!on) item.classList.add("is-off");
      item.setAttribute("aria-pressed", String(on));
      item.title = (on ? "Hide " : "Show ") + type;

      const swatch = document.createElementNS(NS, "svg");
      swatch.setAttribute("width", 14);
      swatch.setAttribute("height", 14);
      swatch.setAttribute("viewBox", "0 0 14 14");
      swatch.appendChild(makeMarker(st.shape, 7, 7, 5, cssVar(st.colorVar), "none"));

      const label = document.createElement("span");
      label.textContent = type;

      item.append(swatch, label);
      item.addEventListener("click", () => {
        if (activeTypes.has(type)) activeTypes.delete(type);
        else activeTypes.add(type);
        renderAll();
      });
      legendEl.appendChild(item);
    }

    // Trend-line toggle rides in the legend when there's enough history.
    if (trendPoints(chartSales()).length) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "legend-item";
      if (!showTrend) item.classList.add("is-off");
      item.setAttribute("aria-pressed", String(showTrend));
      item.title = (showTrend ? "Hide" : "Show") + " the 12-month rolling median line";

      const swatch = document.createElementNS(NS, "svg");
      swatch.setAttribute("width", 14);
      swatch.setAttribute("height", 14);
      swatch.setAttribute("viewBox", "0 0 14 14");
      const lineKey = document.createElementNS(NS, "line");
      lineKey.setAttribute("x1", 1);
      lineKey.setAttribute("y1", 7);
      lineKey.setAttribute("x2", 13);
      lineKey.setAttribute("y2", 7);
      lineKey.setAttribute("stroke", cssVar("--text-secondary"));
      lineKey.setAttribute("stroke-width", "2");
      lineKey.setAttribute("stroke-linecap", "round");
      swatch.appendChild(lineKey);

      const label = document.createElement("span");
      label.textContent = "12-mo median";

      item.append(swatch, label);
      item.addEventListener("click", () => {
        showTrend = !showTrend;
        renderAll();
      });
      legendEl.appendChild(item);
    }
  }

  // ---- Chart: scatter plot, marker shape per type, house-number labels ----

  const NS = "http://www.w3.org/2000/svg";
  const MARGIN = { top: 16, right: 40, bottom: 36, left: 68 };

  function makeMarker(shape, cx, cy, r, fill, stroke) {
    let el;
    if (shape === "circle") {
      el = document.createElementNS(NS, "circle");
      el.setAttribute("cx", cx);
      el.setAttribute("cy", cy);
      el.setAttribute("r", r);
    } else if (shape === "square") {
      el = document.createElementNS(NS, "rect");
      const side = r * 1.8;
      el.setAttribute("x", cx - side / 2);
      el.setAttribute("y", cy - side / 2);
      el.setAttribute("width", side);
      el.setAttribute("height", side);
    } else if (shape === "triangle") {
      el = document.createElementNS(NS, "polygon");
      const h = r * 1.2;
      el.setAttribute("points",
        `${cx},${cy - h} ${cx + h},${cy + h * 0.8} ${cx - h},${cy + h * 0.8}`);
    } else if (shape === "diamond") {
      el = document.createElementNS(NS, "polygon");
      const d = r * 1.25;
      el.setAttribute("points",
        `${cx},${cy - d} ${cx + d},${cy} ${cx},${cy + d} ${cx - d},${cy}`);
    } else { // cross
      el = document.createElementNS(NS, "polygon");
      const a = r * 0.42, b = r * 1.25;
      el.setAttribute("points", [
        `${cx - a},${cy - b}`, `${cx + a},${cy - b}`, `${cx + a},${cy - a}`,
        `${cx + b},${cy - a}`, `${cx + b},${cy + a}`, `${cx + a},${cy + a}`,
        `${cx + a},${cy + b}`, `${cx - a},${cy + b}`, `${cx - a},${cy + a}`,
        `${cx - b},${cy + a}`, `${cx - b},${cy - a}`, `${cx - a},${cy - a}`,
      ].join(" "));
    }
    el.setAttribute("fill", fill);
    if (stroke && stroke !== "none") {
      el.setAttribute("stroke", stroke);
      el.setAttribute("stroke-width", "2");
    }
    return el;
  }

  // ---- Zoom state helpers ----

  function fullDomainFor(sales) {
    if (!sales.length) return null;
    const dates = sales.map((s) => new Date(s.date).getTime());
    const values = sales.map(yValueOf);
    const xMin = Math.min(...dates);
    const xMax = Math.max(...dates);
    const yMaxRaw = Math.max(...values);
    const ticks = niceTicks(0, yMaxRaw, 5);
    return {
      x0: xMin,
      x1: xMax === xMin ? xMin + 30 * 86400000 : xMax,
      y0: 0,
      y1: ticks[ticks.length - 1],
    };
  }

  // ---- 12-month rolling median trend ----

  function trendPoints(sales) {
    if (sales.length < 12) return [];
    const pts = sales
      .map((s) => ({ t: new Date(s.date).getTime(), v: yValueOf(s) }))
      .sort((a, b) => a.t - b.t);
    const span = pts[pts.length - 1].t - pts[0].t;
    const MONTH = 30.44 * 86400000;
    if (span < 24 * MONTH) return [];
    const out = [];
    for (let t = pts[0].t; t <= pts[pts.length - 1].t + 1; t += MONTH) {
      const inWindow = pts.filter((p) => Math.abs(p.t - t) <= 6 * MONTH).map((p) => p.v);
      if (inWindow.length >= 5) out.push({ t, v: median(inWindow) });
    }
    return out.length >= 2 ? out : [];
  }

  function clampDomain(d, full) {
    if (!full) return null;
    const fx = full.x1 - full.x0;
    const fy = full.y1 - full.y0;
    let sx = Math.min(Math.max(d.x1 - d.x0, fx / 200), fx);
    let sy = Math.min(Math.max(d.y1 - d.y0, fy / 200), fy);
    let cx = (d.x0 + d.x1) / 2;
    let cy = (d.y0 + d.y1) / 2;
    let x0 = cx - sx / 2, x1 = cx + sx / 2;
    let y0 = cy - sy / 2, y1 = cy + sy / 2;
    if (x0 < full.x0) { x0 = full.x0; x1 = x0 + sx; }
    if (x1 > full.x1) { x1 = full.x1; x0 = x1 - sx; }
    if (y0 < full.y0) { y0 = full.y0; y1 = y0 + sy; }
    if (y1 > full.y1) { y1 = full.y1; y0 = y1 - sy; }
    // fully zoomed out = back to the fitted view
    if (sx >= fx * 0.999 && sy >= fy * 0.999) return null;
    return { x0, x1, y0, y1 };
  }

  function setZoom(domain) {
    zoomDomain = clampDomain(domain, fullDomainFor(chartSales()));
    rerenderChart();
  }

  function zoomBy(factor, center) {
    const d = zoomDomain || fullDomainFor(chartSales());
    if (!d) return;
    const c = center || { x: (d.x0 + d.x1) / 2, y: (d.y0 + d.y1) / 2 };
    setZoom({
      x0: c.x - (c.x - d.x0) * factor,
      x1: c.x + (d.x1 - c.x) * factor,
      y0: c.y - (c.y - d.y0) * factor,
      y1: c.y + (d.y1 - c.y) * factor,
    });
  }

  function rerenderChart() {
    renderChart(chartSales());
  }

  document.getElementById("chart-zoom-in").addEventListener("click", () => zoomBy(0.6));
  document.getElementById("chart-zoom-out").addEventListener("click", () => zoomBy(1 / 0.6));
  document.getElementById("chart-zoom-reset").addEventListener("click", () => {
    zoomDomain = null;
    rerenderChart();
  });

  function renderChart(sales) {
    chartMount.innerHTML = "";
    if (sales.length === 0) {
      const empty = document.createElement("p");
      empty.className = "chart-empty";
      empty.textContent = "No property types selected — click a legend item to show one.";
      chartMount.appendChild(empty);
      return;
    }

    const width = Math.max(chartMount.clientWidth || 800, 320);
    const height = 380;
    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;

    const domain = zoomDomain || fullDomainFor(sales);
    const { x0, x1, y0, y1 } = domain;
    const yTicks = ticksInRange(y0, y1, 5);

    const xScale = (t) => innerW * ((t - x0) / (x1 - x0));
    const yScale = (p) => innerH - innerH * ((p - y0) / (y1 - y0));

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Sale price over time");

    const root = document.createElementNS(NS, "g");
    root.setAttribute("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    svg.appendChild(root);

    // Marks are clipped to the plot area so zooming never spills them
    // over the axes.
    const defs = document.createElementNS(NS, "defs");
    const clip = document.createElementNS(NS, "clipPath");
    clip.setAttribute("id", "plot-clip");
    const clipRect = document.createElementNS(NS, "rect");
    clipRect.setAttribute("x", -6);
    clipRect.setAttribute("y", -6);
    clipRect.setAttribute("width", innerW + 12);
    clipRect.setAttribute("height", innerH + 12);
    clip.appendChild(clipRect);
    defs.appendChild(clip);
    svg.appendChild(defs);

    const gridlineColor = cssVar("--gridline");
    const mutedColor = cssVar("--text-muted");
    const axisColor = cssVar("--axis");
    const surfaceColor = cssVar("--surface-1");

    for (const tick of yTicks) {
      const y = yScale(tick);
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", 0);
      line.setAttribute("x2", innerW);
      line.setAttribute("y1", y);
      line.setAttribute("y2", y);
      line.setAttribute("stroke", gridlineColor);
      line.setAttribute("stroke-width", "1");
      root.appendChild(line);

      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", -10);
      label.setAttribute("y", y);
      label.setAttribute("text-anchor", "end");
      label.setAttribute("dominant-baseline", "middle");
      label.setAttribute("fill", mutedColor);
      label.setAttribute("font-size", "12");
      label.textContent = formatY(tick);
      root.appendChild(label);
    }

    const baseline = document.createElementNS(NS, "line");
    baseline.setAttribute("x1", 0);
    baseline.setAttribute("x2", innerW);
    baseline.setAttribute("y1", innerH);
    baseline.setAttribute("y2", innerH);
    baseline.setAttribute("stroke", axisColor);
    baseline.setAttribute("stroke-width", "1");
    root.appendChild(baseline);

    const xTicks = dateTicks(x0, x1, 6);
    for (const t of xTicks) {
      const x = xScale(t);
      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", x);
      label.setAttribute("y", innerH + 20);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", mutedColor);
      label.setAttribute("font-size", "12");
      label.textContent = formatDateTick(t, x1 - x0);
      root.appendChild(label);
    }

    const marksGroup = document.createElementNS(NS, "g");
    marksGroup.setAttribute("clip-path", "url(#plot-clip)");
    root.appendChild(marksGroup);

    // Rolling-median trend line sits under the marks.
    if (showTrend) {
      const trend = trendPoints(sales);
      if (trend.length) {
        const poly = document.createElementNS(NS, "polyline");
        poly.setAttribute("points",
          trend.map((p) => `${xScale(p.t)},${yScale(p.v)}`).join(" "));
        poly.setAttribute("fill", "none");
        poly.setAttribute("stroke", cssVar("--text-secondary"));
        poly.setAttribute("stroke-width", "2");
        poly.setAttribute("stroke-linejoin", "round");
        poly.setAttribute("stroke-linecap", "round");
        poly.setAttribute("opacity", "0.75");
        marksGroup.appendChild(poly);
      }
    }

    const hitTargets = [];
    // Count only points inside the current view when deciding whether
    // per-point labels fit — zooming in brings labels back.
    const inView = sales.filter((s) => {
      const t = new Date(s.date).getTime();
      const v = yValueOf(s);
      return t >= x0 && t <= x1 && v >= y0 && v <= y1;
    });
    const drawLabels = inView.length <= LABEL_LIMIT;
    const xPad = (x1 - x0) * 0.02;
    const yPad = (y1 - y0) * 0.02;

    for (const sale of sales) {
      const t = new Date(sale.date).getTime();
      const v = yValueOf(sale);
      // Skip marks well outside the view; the clip hides near-edge ones.
      if (t < x0 - xPad || t > x1 + xPad || v < y0 - yPad || v > y1 + yPad) {
        continue;
      }
      const st = styleFor(typeKey(sale));
      const color = cssVar(st.colorVar);
      const cx = xScale(t);
      const cy = yScale(v);

      const mark = makeMarker(st.shape, cx, cy, 4.5, color, surfaceColor);
      marksGroup.appendChild(mark);

      if (drawLabels && sale.paon) {
        const label = document.createElementNS(NS, "text");
        label.setAttribute("x", cx + 8);
        label.setAttribute("y", cy);
        label.setAttribute("dominant-baseline", "middle");
        label.setAttribute("fill", mutedColor);
        label.setAttribute("font-size", "10");
        label.textContent = sale.paon;
        marksGroup.appendChild(label);
      }

      hitTargets.push({ cx, cy, sale, color, el: mark, id: sale._id, key: propKey(sale) });
    }

    const crosshair = document.createElementNS(NS, "line");
    crosshair.setAttribute("y1", 0);
    crosshair.setAttribute("y2", innerH);
    crosshair.setAttribute("stroke", axisColor);
    crosshair.setAttribute("stroke-width", "1");
    crosshair.setAttribute("visibility", "hidden");
    root.appendChild(crosshair);

    const overlay = document.createElementNS(NS, "rect");
    overlay.setAttribute("x", 0);
    overlay.setAttribute("y", 0);
    overlay.setAttribute("width", innerW);
    overlay.setAttribute("height", innerH);
    overlay.setAttribute("fill", "transparent");
    root.appendChild(overlay);

    // The hovered point is highlighted, and so is every other sale of the
    // same property — in the chart and in the table.
    let highlighted = null;      // the primary hit
    let highlightedGroup = [];   // primary + sibling hits

    function clearHighlight() {
      for (const h of highlightedGroup) {
        h.el.removeAttribute("transform");
        setRowHighlight(h.id, null);
      }
      highlighted = null;
      highlightedGroup = [];
    }

    function applyHighlight(nearest) {
      highlighted = nearest;
      highlightedGroup = hitTargets.filter((h) => h.key === nearest.key);
      for (const h of highlightedGroup) {
        h.el.setAttribute("transform",
          `translate(${h.cx},${h.cy}) scale(1.35) translate(${-h.cx},${-h.cy})`);
        setRowHighlight(h.id, h === nearest ? "primary" : "related");
      }
      scrollRowIntoView(nearest.id);
    }

    overlay.addEventListener("pointermove", (evt) => {
      if (isPanning) return;
      const rect = overlay.getBoundingClientRect();
      const px = ((evt.clientX - rect.left) / rect.width) * innerW;
      const py = ((evt.clientY - rect.top) / rect.height) * innerH;

      let nearest = null;
      let bestDist = Infinity;
      for (const h of hitTargets) {
        const d = Math.hypot(h.cx - px, h.cy - py);
        if (d < bestDist) {
          bestDist = d;
          nearest = h;
        }
      }
      if (!nearest || bestDist > 40) {
        tooltipEl.hidden = true;
        crosshair.setAttribute("visibility", "hidden");
        clearHighlight();
        return;
      }

      if (highlighted !== nearest) {
        clearHighlight();
        applyHighlight(nearest);
      }

      crosshair.setAttribute("x1", nearest.cx);
      crosshair.setAttribute("x2", nearest.cx);
      crosshair.setAttribute("visibility", "visible");

      showTooltip(nearest, MARGIN);
    });

    overlay.addEventListener("pointerleave", () => {
      tooltipEl.hidden = true;
      crosshair.setAttribute("visibility", "hidden");
      clearHighlight();
    });

    // Wheel = zoom, centred on the cursor (like the map).
    overlay.addEventListener("wheel", (evt) => {
      evt.preventDefault();
      const rect = overlay.getBoundingClientRect();
      const fx = (evt.clientX - rect.left) / rect.width;
      const fy = (evt.clientY - rect.top) / rect.height;
      const center = {
        x: x0 + fx * (x1 - x0),
        y: y0 + (1 - fy) * (y1 - y0),
      };
      zoomBy(evt.deltaY < 0 ? 0.75 : 1 / 0.75, center);
    }, { passive: false });

    // Drag = pan. The chart re-renders each move, so the handlers live on
    // window for the duration of the drag.
    overlay.addEventListener("pointerdown", (evt) => {
      if (evt.button !== 0) return;
      evt.preventDefault();
      const startX = evt.clientX;
      const startY = evt.clientY;
      const startDomain = { x0, x1, y0, y1 };
      const rect = overlay.getBoundingClientRect();
      const scaleX = (x1 - x0) / rect.width;
      const scaleY = (y1 - y0) / rect.height;
      let moved = false;

      const onMove = (ev) => {
        const dx = ev.clientX - startX;
        const dy = ev.clientY - startY;
        if (!moved && Math.hypot(dx, dy) < 3) return;
        moved = true;
        isPanning = true;
        tooltipEl.hidden = true;
        setZoom({
          x0: startDomain.x0 - dx * scaleX,
          x1: startDomain.x1 - dx * scaleX,
          y0: startDomain.y0 + dy * scaleY,
          y1: startDomain.y1 + dy * scaleY,
        });
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        setTimeout(() => { isPanning = false; }, 0);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });

    // Double-click = reset to the fitted view.
    overlay.addEventListener("dblclick", () => {
      zoomDomain = null;
      rerenderChart();
    });

    overlay.style.cursor = zoomDomain ? "grab" : "crosshair";

    chartMount.appendChild(svg);
  }

  // ---- Chart ↔ table linking ----

  function setRowHighlight(id, level) {
    const row = tableBody.querySelector(`tr[data-id="${id}"]`);
    if (!row) return;
    row.classList.toggle("is-hover", level === "primary");
    row.classList.toggle("is-related", level === "related");
  }

  function scrollRowIntoView(id) {
    const row = tableBody.querySelector(`tr[data-id="${id}"]`);
    if (!row) return;
    const rowTop = row.offsetTop;
    const rowBottom = rowTop + row.offsetHeight;
    const viewTop = tableWrap.scrollTop;
    const viewBottom = viewTop + tableWrap.clientHeight;
    if (rowTop < viewTop || rowBottom > viewBottom) {
      tableWrap.scrollTop = rowTop - tableWrap.clientHeight / 2 + row.offsetHeight / 2;
    }
  }

  function showTooltip(hit, margin) {
    const sale = hit.sale;
    tooltipEl.innerHTML = "";

    const priceRow = document.createElement("div");
    priceRow.className = "t-row";
    const key = document.createElement("span");
    key.className = "t-key";
    key.style.background = hit.color;
    const value = document.createElement("span");
    value.className = "t-value";
    value.textContent = formatPrice(sale.price);
    priceRow.append(key, value);

    const dateRow = document.createElement("div");
    dateRow.textContent = formatFullDate(sale.date);

    tooltipEl.append(priceRow, dateRow);
    if (sale.address) {
      const addrRow = document.createElement("div");
      addrRow.textContent = sale.address;
      tooltipEl.append(addrRow);
    }
    if (sale.property_type) {
      const typeRow = document.createElement("div");
      typeRow.textContent = sale.property_type;
      tooltipEl.append(typeRow);
    }
    const area = floorAreaOf(sale);
    if (area) {
      const sqmRow = document.createElement("div");
      sqmRow.textContent =
        "£" + Math.round(sale.price / area).toLocaleString("en-GB") + "/m² · " +
        Math.round(area) + " m²";
      tooltipEl.append(sqmRow);
    }

    tooltipEl.hidden = false;
    tooltipEl.style.left = (margin.left + hit.cx) + "px";
    tooltipEl.style.top = (margin.top + hit.cy - 10) + "px";
  }

  function renderTable(sales) {
    tableBody.innerHTML = "";
    for (const s of sales) {
      const tr = document.createElement("tr");
      tr.dataset.id = s._id;
      if (s._outlier) {
        tr.classList.add("is-outlier");
        tr.title = "Above 3× the median price — not plotted on the chart";
      }

      const tdDate = document.createElement("td");
      tdDate.textContent = s.date;

      const tdPrice = document.createElement("td");
      tdPrice.className = "num";
      tdPrice.textContent = formatPrice(s.price);

      const tdAddr = document.createElement("td");
      tdAddr.textContent = s.address || "";

      const tdType = document.createElement("td");
      tdType.textContent = s.property_type || "";

      const epcEntry = epcByProperty[propKey(s)];

      const tdRooms = document.createElement("td");
      tdRooms.className = "num rooms";
      tdRooms.textContent = epcEntry && epcEntry.rooms != null ? String(epcEntry.rooms) : "—";

      const tdSqm = document.createElement("td");
      tdSqm.className = "num sqm";
      tdSqm.textContent = epcEntry && epcEntry.floor_area
        ? "£" + Math.round(s.price / epcEntry.floor_area).toLocaleString("en-GB")
        : "—";

      tr.append(tdDate, tdPrice, tdAddr, tdType, tdRooms, tdSqm);
      tableBody.appendChild(tr);
    }
  }

  // ---- Rooms column (EPC register's habitable-rooms count) ----

  function uniqueProperties() {
    const seen = new Map();
    for (const s of allSales) {
      const key = propKey(s);
      if (!seen.has(key)) {
        seen.set(key, {
          id: key,
          paon: s.paon,
          saon: s.saon,
          street: s.street,
          town: s.town,
          postcode: s.postcode,
        });
      }
    }
    return [...seen.values()];
  }

  async function loadEpc() {
    try {
      const resp = await fetch("/api/epc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ properties: uniqueProperties() }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || "EPC lookup failed");

      if (!body.configured) {
        tableNote.hidden = false;
        tableNote.textContent =
          "Rooms & £/m² come from the EPC register (habitable rooms and internal floor area; " +
          "no open dataset publishes bedroom counts). Free API key from epc.opendatacommunities.org — " +
          "set EPC_AUTH to enable.";
        return;
      }

      epcByProperty = body.properties || {};
      const matched = Object.keys(epcByProperty).length;
      const anyArea = Object.values(epcByProperty).some((e) => e.floor_area);
      chartModeEl.hidden = !anyArea;

      tableNote.hidden = false;
      tableNote.textContent =
        "Rooms = habitable rooms and £/m² = price ÷ internal floor area, both from the property's " +
        "most recent EPC" +
        (matched ? "" : " — no EPC matches found for this search") + ".";

      // Re-render so the table cells, tooltip data, and £/m² toggle pick up
      // the EPC values.
      renderAll();
    } catch (err) {
      tableNote.hidden = false;
      tableNote.textContent = "EPC lookup unavailable: " + (err.message || "unknown error");
    }
  }

  // ---- Map: one marker per property, coloured by type ----

  mapToggle.addEventListener("click", () => {
    const showing = !mapSection.hidden;
    if (showing) {
      mapSection.hidden = true;
      mapToggle.textContent = "Show map";
    } else {
      mapSection.hidden = false;
      mapToggle.textContent = "Hide map";
      refreshMap();
    }
  });

  async function refreshMap() {
    if (typeof L === "undefined") {
      mapNote.textContent = "The map library failed to load.";
      return;
    }
    if (!map) {
      map = L.map("map");
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      mapMarkersLayer = L.layerGroup().addTo(map);
      map.setView([54.5, -2.5], 5);
    }
    // Leaflet needs a size recalc when its container was hidden at init time.
    setTimeout(() => map.invalidateSize(), 50);

    const wanted = uniqueProperties();
    const missing = wanted.filter((p) => !(p.id in geocodeCache));
    if (missing.length > 0 && !geocodeFailed) {
      mapNote.textContent = "Locating properties… (house-level lookups take about a second each)";
      try {
        const resp = await fetch("/api/geocode", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ properties: missing }),
        });
        const body = await resp.json();
        if (!resp.ok) throw new Error(body.error || "Geocoding failed");
        Object.assign(geocodeCache, body.coords || {});
        for (const p of missing) {
          if (!(p.id in geocodeCache)) geocodeCache[p.id] = null; // known-unresolvable
        }
      } catch (err) {
        geocodeFailed = true;
        mapNote.textContent = "Could not locate properties: " + (err.message || "geocoding failed");
        return;
      }
    }
    renderMapMarkers();
  }

  function renderMapMarkers() {
    if (!map || mapSection.hidden) return;

    mapMarkersLayer.clearLayers();

    // One marker per property (unique address), carrying all its sales.
    const properties = new Map();
    for (const s of tableSales()) {
      const key = propKey(s);
      if (!properties.has(key)) properties.set(key, []);
      properties.get(key).push(s);
    }

    // Address-precision markers sit at their true location; postcode-precision
    // ones share a centroid, so fan those out to keep them clickable.
    const perPostcode = {};
    const latLngs = [];
    let unlocated = 0;
    let addressLevel = 0;

    for (const [key, salesAtProperty] of properties.entries()) {
      const first = salesAtProperty[0];
      const coord = geocodeCache[key];
      if (!coord) {
        unlocated += 1;
        continue;
      }
      let lat = coord.lat;
      let lng = coord.lng;
      if (coord.precision === "address") {
        addressLevel += 1;
      } else {
        const n = (perPostcode[first.postcode] = (perPostcode[first.postcode] || 0) + 1) - 1;
        const angle = n * 2.39996; // golden angle
        const radius = 0.00012 * Math.sqrt(n);
        lat += radius * Math.cos(angle);
        lng += radius * Math.sin(angle) * 1.6; // lng degrees are shorter
      }
      latLngs.push([lat, lng]);

      const st = styleFor(typeKey(first));
      const marker = L.circleMarker([lat, lng], {
        radius: 7,
        color: cssVar("--surface-1"),
        weight: 2,
        fillColor: cssVar(st.colorVar),
        fillOpacity: 0.9,
      });

      const popup = document.createElement("div");
      popup.className = "map-popup";
      const addr = document.createElement("strong");
      addr.textContent = first.address || first.postcode;
      popup.appendChild(addr);
      if (first.property_type) {
        const t = document.createElement("div");
        t.className = "map-popup-type";
        t.textContent = first.property_type;
        popup.appendChild(t);
      }
      const list = document.createElement("div");
      for (const s of salesAtProperty.slice().reverse()) {
        const row = document.createElement("div");
        row.textContent = formatFullDate(s.date) + " — " + formatPrice(s.price);
        list.appendChild(row);
      }
      popup.appendChild(list);
      marker.bindPopup(popup);
      mapMarkersLayer.addLayer(marker);
    }

    if (latLngs.length > 0) {
      map.fitBounds(latLngs, { padding: [30, 30], maxZoom: 17 });
      const postcodeLevel = latLngs.length - addressLevel;
      const parts = [];
      if (addressLevel) parts.push(addressLevel + " at street-address level (OpenStreetMap)");
      if (postcodeLevel) parts.push(postcodeLevel + " by postcode centroid (accurate to a few doors)");
      mapNote.textContent =
        latLngs.length + (latLngs.length === 1 ? " property" : " properties") + " located: " +
        parts.join(", ") +
        (unlocated ? "; " + unlocated + " could not be located" : "") + ".";
    } else {
      mapNote.textContent = geocodeFailed
        ? mapNote.textContent
        : "No properties could be located for this search.";
    }
  }

  // ---- formatting & scale helpers ----

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || getComputedStyle(document.body).getPropertyValue(name).trim();
  }

  function formatPrice(value) {
    if (value >= 1e6) return "£" + (value / 1e6).toFixed(value % 1e6 === 0 ? 0 : 1) + "m";
    if (value >= 1e3) return "£" + Math.round(value / 1e3) + "k";
    return "£" + Math.round(value);
  }

  function formatFullDate(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  function formatDateTick(t, spanMs) {
    const d = new Date(t);
    const spanYears = spanMs / (365 * 24 * 3600 * 1000);
    if (spanYears > 4) return String(d.getFullYear());
    if (spanYears > 0.25) return d.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });
  }

  function niceTicks(min, max, count) {
    if (max <= min) max = min + 1;
    const span = max - min;
    const rawStep = span / count;
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const residual = rawStep / magnitude;
    let step;
    if (residual > 5) step = 10 * magnitude;
    else if (residual > 2) step = 5 * magnitude;
    else if (residual > 1) step = 2 * magnitude;
    else step = magnitude;

    const ticks = [];
    let tick = 0;
    while (tick < max + step) {
      ticks.push(tick);
      tick += step;
      if (ticks.length > 20) break;
    }
    return ticks;
  }

  function dateTicks(min, max, count) {
    if (max <= min) return [min];
    const step = (max - min) / (count - 1);
    const ticks = [];
    for (let i = 0; i < count; i++) ticks.push(min + step * i);
    return ticks;
  }

  // Clean tick values covering [min, max] — unlike niceTicks, the range
  // does not have to start at zero (needed once the chart is zoomed).
  function ticksInRange(min, max, count) {
    if (max <= min) max = min + 1;
    const rawStep = (max - min) / count;
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const residual = rawStep / magnitude;
    let step;
    if (residual > 5) step = 10 * magnitude;
    else if (residual > 2) step = 5 * magnitude;
    else if (residual > 1) step = 2 * magnitude;
    else step = magnitude;

    const ticks = [];
    let tick = Math.ceil(min / step) * step;
    while (tick <= max + step * 1e-9) {
      ticks.push(tick);
      tick += step;
      if (ticks.length > 20) break;
    }
    return ticks;
  }

  window.addEventListener("resize", debounce(() => {
    if (allSales.length && !resultCard.hidden) {
      renderChart(chartSales());
    }
  }, 300));

  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }
})();
