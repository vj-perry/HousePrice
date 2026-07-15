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

  const form = document.getElementById("search-form");
  const statusEl = document.getElementById("status");
  const resultCard = document.getElementById("result-card");
  const resultTitle = document.getElementById("result-title");
  const legendEl = document.getElementById("legend");
  const chartMount = document.getElementById("chart-mount");
  const tooltipEl = document.getElementById("tooltip");
  const tableBody = document.querySelector("#data-table tbody");
  const tableWrap = document.querySelector(".table-wrap");

  let lastSales = null;

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const data = new FormData(form);
    const postcode = (data.get("postcode") || "").trim();
    if (!postcode) {
      setStatus("Enter a postcode.", true);
      return;
    }
    const street = (data.get("street") || "").trim();

    const params = new URLSearchParams({ postcode });
    if (street) params.set("street", street);

    setStatus("Loading from HM Land Registry…", false);
    resultCard.hidden = true;

    try {
      const resp = await fetch("/api/sales?" + params.toString());
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
      const title = postcode.toUpperCase() + (street ? " · " + street : "");
      renderResult(sales, title);
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

  function renderResult(sales, title) {
    resultTitle.textContent = title + " — " + sales.length + (sales.length === 1 ? " sale" : " sales");
    resultCard.hidden = false;

    sales.sort((a, b) => a.date.localeCompare(b.date));
    lastSales = sales;

    renderLegend(sales);
    renderTable(sales);
    renderChart(sales);
  }

  function typesPresent(sales) {
    const present = new Set(sales.map((s) => s.property_type || "Other"));
    const ordered = TYPE_ORDER.filter((t) => present.has(t));
    for (const t of present) {
      if (!TYPE_ORDER.includes(t)) ordered.push(t);
    }
    return ordered;
  }

  // ---- Legend (symbol + colour per property type) ----

  function renderLegend(sales) {
    legendEl.innerHTML = "";
    const types = typesPresent(sales);
    if (types.length < 2) {
      legendEl.setAttribute("aria-hidden", "true");
      return;
    }
    legendEl.removeAttribute("aria-hidden");
    for (const type of types) {
      const st = styleFor(type);
      const item = document.createElement("span");
      item.className = "legend-item";

      const swatch = document.createElementNS(NS, "svg");
      swatch.setAttribute("width", 14);
      swatch.setAttribute("height", 14);
      swatch.setAttribute("viewBox", "0 0 14 14");
      swatch.appendChild(makeMarker(st.shape, 7, 7, 5, cssVar(st.colorVar), "none"));

      const label = document.createElement("span");
      label.textContent = type;

      item.append(swatch, label);
      legendEl.appendChild(item);
    }
  }

  // ---- Chart: scatter plot, one marker shape per property type ----

  const NS = "http://www.w3.org/2000/svg";
  const MARGIN = { top: 16, right: 20, bottom: 36, left: 68 };

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

  function renderChart(sales) {
    chartMount.innerHTML = "";
    const width = Math.max(chartMount.clientWidth || 800, 320);
    const height = 380;
    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;

    const dates = sales.map((s) => new Date(s.date).getTime());
    const prices = sales.map((s) => s.price);
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
      label.textContent = formatPrice(tick);
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

    const hitTargets = [];

    sales.forEach((sale, index) => {
      const st = styleFor(sale.property_type || "Other");
      const color = cssVar(st.colorVar);
      const cx = xScale(new Date(sale.date).getTime());
      const cy = yScale(sale.price);

      const mark = makeMarker(st.shape, cx, cy, 4.5, color, surfaceColor);
      root.appendChild(mark);

      hitTargets.push({ cx, cy, sale, color, el: mark, index });
    });

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

    let highlighted = null;

    function clearHighlight() {
      if (highlighted) {
        highlighted.el.removeAttribute("transform");
        setRowHighlight(highlighted.index, false);
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

      if (highlighted && highlighted !== nearest) clearHighlight();

      if (highlighted !== nearest) {
        nearest.el.setAttribute("transform",
          `translate(${nearest.cx},${nearest.cy}) scale(1.35) translate(${-nearest.cx},${-nearest.cy})`);
        setRowHighlight(nearest.index, true);
        highlighted = nearest;
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

    chartMount.appendChild(svg);
  }

  // ---- Chart ↔ table linking ----

  function setRowHighlight(index, on) {
    const row = tableBody.querySelector(`tr[data-index="${index}"]`);
    if (!row) return;
    row.classList.toggle("is-hover", on);
    if (on) {
      const rowTop = row.offsetTop;
      const rowBottom = rowTop + row.offsetHeight;
      const viewTop = tableWrap.scrollTop;
      const viewBottom = viewTop + tableWrap.clientHeight;
      if (rowTop < viewTop || rowBottom > viewBottom) {
        tableWrap.scrollTop = rowTop - tableWrap.clientHeight / 2 + row.offsetHeight / 2;
      }
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

    tooltipEl.hidden = false;
    tooltipEl.style.left = (margin.left + hit.cx) + "px";
    tooltipEl.style.top = (margin.top + hit.cy - 10) + "px";
  }

  function renderTable(sales) {
    tableBody.innerHTML = "";
    sales.forEach((s, index) => {
      const tr = document.createElement("tr");
      tr.dataset.index = index;

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
    });
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
    if (lastSales && !resultCard.hidden) {
      renderChart(lastSales);
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
