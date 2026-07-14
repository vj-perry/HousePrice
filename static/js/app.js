(function () {
  "use strict";

  const SERIES_COLORS = [
    "--series-1", "--series-2", "--series-3", "--series-4",
    "--series-5", "--series-6", "--series-7", "--series-8",
  ];

  const form = document.getElementById("search-form");
  const statusEl = document.getElementById("status");
  const resultCard = document.getElementById("result-card");
  const resultTitle = document.getElementById("result-title");
  const legendEl = document.getElementById("legend");
  const chartMount = document.getElementById("chart-mount");
  const tooltipEl = document.getElementById("tooltip");
  const tableToggle = document.getElementById("table-toggle");
  const tableWrap = document.getElementById("table-wrap");
  const tableBody = document.querySelector("#data-table tbody");

  let mode = "property";
  let lastRender = null;

  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      mode = btn.dataset.mode;
      document.querySelectorAll(".mode-btn").forEach((b) => {
        b.classList.toggle("is-active", b === btn);
        b.setAttribute("aria-selected", String(b === btn));
      });
      document.querySelectorAll("[data-mode-fields]").forEach((f) => {
        f.hidden = f.dataset.modeFields !== mode;
      });
    });
  });

  tableToggle.addEventListener("click", () => {
    const showing = !tableWrap.hidden;
    tableWrap.hidden = showing;
    tableToggle.textContent = showing ? "Show table" : "Hide table";
  });

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const data = new FormData(form);
    let url;
    let title;

    if (mode === "property") {
      const postcode = (data.get("postcode") || "").trim();
      if (!postcode) {
        setStatus("Enter a postcode.", true);
        return;
      }
      const params = new URLSearchParams({ postcode });
      const house = (data.get("house") || "").trim();
      if (house) params.set("house", house);
      url = "/api/property-sales?" + params.toString();
      title = "Sales at " + postcode.toUpperCase() + (house ? ", " + house : "");
    } else {
      const area = (data.get("area") || "").trim();
      const town = (data.get("town") || "").trim();
      if (!area && !town) {
        setStatus("Enter a postcode area or a town.", true);
        return;
      }
      const params = new URLSearchParams();
      if (area) params.set("area", area);
      if (town) params.set("town", town);
      const dateFrom = data.get("date_from");
      const dateTo = data.get("date_to");
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      url = "/api/area-sales?" + params.toString();
      title = "Sales in " + (area ? area.toUpperCase() : town);
    }

    setStatus("Loading…", false);
    resultCard.hidden = true;

    try {
      const resp = await fetch(url);
      const body = await resp.json();
      if (!resp.ok) {
        throw new Error(body.error || "Request failed");
      }
      const sales = (body.sales || []).filter((s) => s.price != null && s.date);
      if (sales.length === 0) {
        setStatus("No sales found for that search.", true);
        return;
      }
      setStatus("", false);
      renderResult(sales, title, mode);
    } catch (err) {
      setStatus(err.message, true);
    }
  });

  function setStatus(message, isError) {
    statusEl.textContent = message;
    statusEl.classList.toggle("is-error", !!isError);
  }

  function renderResult(sales, title, currentMode) {
    resultTitle.textContent = title + " (" + sales.length + (sales.length === 1 ? " sale" : " sales") + ")";
    resultCard.hidden = false;
    tableWrap.hidden = true;
    tableToggle.textContent = "Show table";

    sales.sort((a, b) => a.date.localeCompare(b.date));

    const series = currentMode === "property"
      ? groupByAddress(sales)
      : groupByPropertyType(sales);

    renderLegend(series, currentMode === "property");
    lastRender = { sales, series, isLineMode: currentMode === "property" };
    renderChart(sales, series, currentMode === "property");
    renderTable(sales);
  }

  function groupByAddress(sales) {
    const keys = [];
    const groups = new Map();
    for (const s of sales) {
      const key = [s.saon, s.paon, s.street].filter(Boolean).join(" ") || "Unknown address";
      if (!groups.has(key)) {
        keys.push(key);
        groups.set(key, []);
      }
      groups.get(key).push(s);
    }
    return keys.map((key, i) => ({
      key,
      label: key,
      colorVar: SERIES_COLORS[i % SERIES_COLORS.length],
      points: groups.get(key),
      drawLine: groups.get(key).length > 1,
    }));
  }

  const TYPE_ORDER = ["Detached", "Semi-detached", "Terraced", "Flat/Maisonette", "Other"];

  function groupByPropertyType(sales) {
    const groups = new Map();
    for (const s of sales) {
      const key = s.property_type || "Unknown";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(s);
    }
    const orderedKeys = TYPE_ORDER.filter((t) => groups.has(t))
      .concat([...groups.keys()].filter((k) => !TYPE_ORDER.includes(k) && k !== "Unknown"))
      .concat(groups.has("Unknown") ? ["Unknown"] : []);

    return orderedKeys.map((key, i) => ({
      key,
      label: key,
      colorVar: key === "Unknown" ? "--text-muted" : SERIES_COLORS[i % SERIES_COLORS.length],
      points: groups.get(key),
      drawLine: false,
    }));
  }

  function renderLegend(series, isLineMode) {
    legendEl.innerHTML = "";
    if (series.length < 2) {
      legendEl.setAttribute("aria-hidden", "true");
      return;
    }
    legendEl.removeAttribute("aria-hidden");
    for (const s of series) {
      const item = document.createElement("span");
      item.className = "legend-item";

      const key = document.createElement("span");
      key.className = isLineMode ? "legend-key" : "legend-dot";
      key.style.background = `var(${s.colorVar})`;

      const label = document.createElement("span");
      label.textContent = s.label;

      item.append(key, label);
      legendEl.appendChild(item);
    }
  }

  // ---- Chart rendering (plain SVG, no dependencies) ----

  const NS = "http://www.w3.org/2000/svg";
  const MARGIN = { top: 16, right: 20, bottom: 36, left: 68 };

  function renderChart(allSales, series, isLineMode) {
    chartMount.innerHTML = "";
    const width = Math.max(chartMount.clientWidth || 800, 320);
    const height = 380;
    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;

    const dates = allSales.map((s) => new Date(s.date).getTime());
    const prices = allSales.map((s) => s.price);
    const xMin = Math.min(...dates);
    const xMax = Math.max(...dates);
    const yMaxRaw = Math.max(...prices);
    const yTicks = niceTicks(0, yMaxRaw, 5);
    const yMax = yTicks[yTicks.length - 1];

    const xScale = (t) => innerW * (xMax === xMin ? 0.5 : (t - xMin) / (xMax - xMin));
    const yScale = (p) => innerH - innerH * (p / yMax);

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Sale price over time");

    const root = document.createElementNS(NS, "g");
    root.setAttribute("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    svg.appendChild(root);

    const gridlineColor = cssVar("--gridline");
    const mutedColor = cssVar("--text-muted");
    const axisColor = cssVar("--axis");

    // horizontal gridlines + y labels
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
      label.textContent = formatPrice(tick);
      root.appendChild(label);
    }

    // x axis baseline
    const baseline = document.createElementNS(NS, "line");
    baseline.setAttribute("x1", 0);
    baseline.setAttribute("x2", innerW);
    baseline.setAttribute("y1", innerH);
    baseline.setAttribute("y2", innerH);
    baseline.setAttribute("stroke", axisColor);
    baseline.setAttribute("stroke-width", "1");
    root.appendChild(baseline);

    // x ticks
    const xTicks = dateTicks(xMin, xMax, 6);
    for (const t of xTicks) {
      const x = xScale(t);
      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", x);
      label.setAttribute("y", innerH + 20);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", mutedColor);
      label.setAttribute("font-size", "12");
      label.textContent = formatDateTick(t, xMax - xMin);
      root.appendChild(label);
    }

    // series: lines (property mode only) then markers on top
    const hitTargets = [];

    for (const s of series) {
      const color = cssVar(s.colorVar);
      if (isLineMode && s.drawLine) {
        const pts = s.points
          .map((p) => `${xScale(new Date(p.date).getTime())},${yScale(p.price)}`)
          .join(" ");
        const poly = document.createElementNS(NS, "polyline");
        poly.setAttribute("points", pts);
        poly.setAttribute("fill", "none");
        poly.setAttribute("stroke", color);
        poly.setAttribute("stroke-width", "2");
        poly.setAttribute("stroke-linejoin", "round");
        poly.setAttribute("stroke-linecap", "round");
        root.appendChild(poly);
      }

      for (const p of s.points) {
        const cx = xScale(new Date(p.date).getTime());
        const cy = yScale(p.price);

        const dot = document.createElementNS(NS, "circle");
        dot.setAttribute("cx", cx);
        dot.setAttribute("cy", cy);
        dot.setAttribute("r", 4.5);
        dot.setAttribute("fill", color);
        dot.setAttribute("stroke", cssVar("--surface-1"));
        dot.setAttribute("stroke-width", "2");
        root.appendChild(dot);

        hitTargets.push({ cx, cy, sale: p, color, el: dot });
      }
    }

    // crosshair line (hidden until hover)
    const crosshair = document.createElementNS(NS, "line");
    crosshair.setAttribute("y1", 0);
    crosshair.setAttribute("y2", innerH);
    crosshair.setAttribute("stroke", axisColor);
    crosshair.setAttribute("stroke-width", "1");
    crosshair.setAttribute("visibility", "hidden");
    root.appendChild(crosshair);

    // transparent overlay to catch pointer events across the whole plot
    const overlay = document.createElementNS(NS, "rect");
    overlay.setAttribute("x", 0);
    overlay.setAttribute("y", 0);
    overlay.setAttribute("width", innerW);
    overlay.setAttribute("height", innerH);
    overlay.setAttribute("fill", "transparent");
    root.appendChild(overlay);

    let highlighted = null;

    function clearHighlight() {
      if (highlighted) {
        highlighted.setAttribute("r", 4.5);
        highlighted = null;
      }
    }

    overlay.addEventListener("pointermove", (evt) => {
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

      clearHighlight();
      nearest.el.setAttribute("r", 6);
      highlighted = nearest.el;

      crosshair.setAttribute("x1", nearest.cx);
      crosshair.setAttribute("x2", nearest.cx);
      crosshair.setAttribute("visibility", "visible");

      showTooltip(nearest, chartMount, MARGIN);
    });

    overlay.addEventListener("pointerleave", () => {
      tooltipEl.hidden = true;
      crosshair.setAttribute("visibility", "hidden");
      clearHighlight();
    });

    chartMount.appendChild(svg);
  }

  function showTooltip(hit, mount, margin) {
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

    const addrRow = document.createElement("div");
    addrRow.textContent = sale.address || "";

    tooltipEl.append(priceRow, dateRow);
    if (sale.address) tooltipEl.append(addrRow);
    if (sale.property_type) {
      const typeRow = document.createElement("div");
      typeRow.textContent = sale.property_type;
      tooltipEl.append(typeRow);
    }

    tooltipEl.hidden = false;
    tooltipEl.style.left = (margin.left + hit.cx) + "px";
    tooltipEl.style.top = (margin.top + hit.cy - 10) + "px";
  }

  function renderTable(sales) {
    tableBody.innerHTML = "";
    for (const s of sales) {
      const tr = document.createElement("tr");

      const tdDate = document.createElement("td");
      tdDate.textContent = s.date;

      const tdPrice = document.createElement("td");
      tdPrice.className = "num";
      tdPrice.textContent = formatPrice(s.price);

      const tdAddr = document.createElement("td");
      tdAddr.textContent = s.address || "";

      const tdType = document.createElement("td");
      tdType.textContent = s.property_type || "";

      tr.append(tdDate, tdPrice, tdAddr, tdType);
      tableBody.appendChild(tr);
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
    return d.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
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

  window.addEventListener("resize", debounce(() => {
    if (lastRender && !resultCard.hidden) {
      renderChart(lastRender.sales, lastRender.series, lastRender.isLineMode);
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
