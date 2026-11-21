(function (root) {
  "use strict";

  const number = new Intl.NumberFormat("de-CH", { maximumFractionDigits: 1 });
  const compact = new Intl.NumberFormat("de-CH", { notation: "compact", maximumFractionDigits: 1 });
  const red = "#c91d30";
  const comparisonColor = "#65717b";
  const color = { grid: "#e9e9e4", text: "#626661" };

  function niceStep(span, target) {
    const rough = span / target;
    const power = 10 ** Math.floor(Math.log10(rough));
    return [1, 2, 2.5, 5, 10].find((factor) => factor * power >= rough) * power;
  }

  function createChart(wrap, canvas, tip, readout, formatMoney, formatAge) {
    const context = canvas.getContext("2d");
    let data;
    let activeMonth = null;
    let plot;

    function draw() {
      if (!context || !data) return;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (!width || !height) return;
      const scale = root.devicePixelRatio || 1;
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      context.setTransform(scale, 0, 0, scale, 0, 0);

      const { main, comparison, weak, strong, endAge, startAge, events, showRange, comparisonLabel } = data;
      const last = main.length - 1;
      const series = showRange ? [main, comparison, weak, strong] : [main, comparison];
      const values = series.flatMap((points) => points.map((point) => point.net));
      const floor = Math.min(0, ...values);
      const ceiling = Math.max(0, ...values);
      const step = niceStep(Math.max(1, ceiling - floor), 5);
      const lower = Math.floor(floor / step) * step;
      const upper = Math.ceil(Math.max(ceiling, lower + step) / step) * step;
      const axisLabel = (value) => Math.abs(value) >= 1000 ? compact.format(value) : number.format(value);
      context.font = '12px "Segoe UI", system-ui, sans-serif';
      const left = Math.max(42, Math.ceil(Math.max(context.measureText(axisLabel(lower)).width,
        context.measureText(axisLabel(upper)).width)) + 11);
      const right = width - 15;
      const top = 25;
      const bottom = height - 33;
      const x = (month) => left + (right - left) * month / last;
      const y = (value) => bottom - (bottom - top) * (value - lower) / (upper - lower);
      plot = { left, right, last };

      context.textBaseline = "middle";
      context.textAlign = "right";
      context.fillStyle = color.text;
      context.fillText("CHF", left - 8, 9);

      for (let i = 0; i <= Math.round((upper - lower) / step); i += 1) {
        const value = lower + i * step;
        const line = y(value);
        context.strokeStyle = value === 0 ? "#d6d7d0" : color.grid;
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(left, line);
        context.lineTo(right, line);
        context.stroke();
        context.fillText(axisLabel(value), left - 8, line);
      }

      const yearSpan = endAge - startAge;
      const sections = Math.min(yearSpan, width < 450 ? 4 : 5);
      context.textAlign = "center";
      for (let part = 0; part <= sections; part += 1) {
        const age = startAge + Math.round(yearSpan * part / sections);
        context.fillText(String(age), x((age - startAge) * 12), bottom + 16);
      }
      context.textAlign = "right";
      context.fillText("Alter", right, bottom + 30);

      if (showRange) {
        context.beginPath();
        strong.forEach((point, month) => context.lineTo(x(month), y(Math.max(point.net, weak[month].net))));
        for (let month = last; month >= 0; month -= 1) {
          context.lineTo(x(month), y(Math.min(weak[month].net, strong[month].net)));
        }
        context.closePath();
        context.fillStyle = "rgba(201,29,48,.105)";
        context.fill();
      }

      const eventMonths = new Set(events.map((event) => (event.age - startAge) * 12 + 1));
      for (const month of eventMonths) {
        if (month > last) continue;
        context.strokeStyle = "#e7c1c6";
        context.lineWidth = 1;
        context.setLineDash([3, 4]);
        context.beginPath();
        context.moveTo(x(month), bottom);
        context.lineTo(x(month), y(main[month].net));
        context.stroke();
      }

      function drawSeries(points, stroke, lineWidth, dash) {
        context.strokeStyle = stroke;
        context.lineWidth = lineWidth;
        context.lineJoin = "round";
        context.setLineDash(dash);
        context.beginPath();
        points.forEach((point, month) => context.lineTo(x(month), y(point.net)));
        context.stroke();
        context.setLineDash([]);
      }
      drawSeries(comparison, comparisonColor, 1.8, [6, 5]);
      drawSeries(main, red, 2.7, []);

      function marker(month, value, fill, radius) {
        context.beginPath();
        context.arc(x(month), y(value), radius, 0, Math.PI * 2);
        context.fillStyle = fill;
        context.fill();
        context.strokeStyle = "white";
        context.lineWidth = 1.5;
        context.stroke();
      }
      for (const month of eventMonths) {
        if (month <= last) marker(month, main[month].net, red, 4);
      }
      marker(last, main[last].net, red, 4.5);

      if (activeMonth === null) {
        tip.hidden = true;
        return;
      }
      const month = Math.min(activeMonth, last);
      const position = x(month);
      const first = main[month].net;
      const second = comparison[month].net;
      context.strokeStyle = "#a4a39e";
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(position, top);
      context.lineTo(position, bottom);
      context.stroke();
      marker(month, second, comparisonColor, 4);
      marker(month, first, red, 5);

      const title = document.createElement("strong");
      title.textContent = formatAge(month, startAge);
      const plan = document.createElement("span");
      plan.textContent = "Mit Sparplan & Ereignissen · " + formatMoney(first);
      const alternate = document.createElement("span");
      alternate.textContent = comparisonLabel + " · " + formatMoney(second);
      tip.replaceChildren(title, plan, alternate);
      tip.hidden = false;
      const tipX = position + tip.offsetWidth + 16 > width ? position - tip.offsetWidth - 10 : position + 10;
      tip.style.left = Math.max(0, tipX) + "px";
      tip.style.top = Math.max(1, Math.min(y(Math.max(first, second)) - tip.offsetHeight - 8,
        bottom - tip.offsetHeight)) + "px";
    }

    function clearSelection() {
      if (activeMonth === null) return;
      activeMonth = null;
      readout.textContent = "";
      draw();
    }

    canvas.addEventListener("pointermove", (event) => {
      if (!plot || event.pointerType === "touch") return;
      selectPointerMonth(event);
    });
    canvas.addEventListener("pointerdown", (event) => {
      if (plot) selectPointerMonth(event);
    });
    function selectPointerMonth(event) {
      const position = event.clientX - canvas.getBoundingClientRect().left;
      const month = Math.max(0, Math.min(plot.last, Math.round(
        (position - plot.left) / (plot.right - plot.left) * plot.last,
      )));
      if (month === activeMonth) return;
      activeMonth = month;
      draw();
    }
    canvas.addEventListener("pointerleave", clearSelection);
    canvas.addEventListener("blur", clearSelection);
    canvas.addEventListener("keydown", (event) => {
      if (!plot) return;
      const jump = event.shiftKey ? 12 : 1;
      const month = activeMonth ?? 0;
      const next = { ArrowLeft: month - jump, ArrowRight: month + jump, Home: 0, End: plot.last }[event.key];
      if (event.key === "Escape") clearSelection();
      if (typeof next !== "number") return;
      event.preventDefault();
      activeMonth = Math.max(0, Math.min(next, plot.last));
      draw();
      readout.textContent = tip.innerText;
    });
    new ResizeObserver(draw).observe(wrap);

    return {
      update(next) {
        data = next;
        activeMonth = null;
        readout.textContent = "";
        draw();
      },
    };
  }

  root.createWealthChart = createChart;
})(globalThis);
