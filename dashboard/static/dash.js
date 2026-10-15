// Charts and date presets for the dashboard. Every chart is one series in the
// accent blue, so it needs no legend: the card title names what is plotted.
(function () {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const baht = new Intl.NumberFormat("th-TH", { style: "currency", currency: "THB", maximumFractionDigits: 0 });
  const baht2 = new Intl.NumberFormat("th-TH", { style: "currency", currency: "THB", minimumFractionDigits: 2 });
  const count = new Intl.NumberFormat("th-TH");
  const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

  function draw(canvas) {
    const horizontal = canvas.dataset.chart === "hbar";
    const money = canvas.dataset.format === "money";
    const labels = JSON.parse(canvas.dataset.labels);
    const values = JSON.parse(canvas.dataset.values);
    const fmtTick = (v) => (money ? "฿" : "") + compact.format(v);
    const fmtFull = (v) => (money ? baht2.format(v) : count.format(v));
    const valueAxis = {
      beginAtZero: true,
      grid: { color: css("--grid"), lineWidth: 1, drawTicks: false },
      border: { display: false },
      ticks: { color: css("--muted"), callback: fmtTick, padding: 6, maxTicksLimit: 6 },
    };
    // Long item names would push the plot off the card; the tooltip shows the full name.
    const short = (s) => (s.length > 24 ? s.slice(0, 23) + "…" : s);
    const catAxis = {
      grid: { display: false },
      border: { color: css("--line") },
      ticks: {
        color: css("--text-2"), autoSkip: !horizontal, maxRotation: 0,
        callback: function (v) { return short(String(this.getLabelForValue(v))); },
      },
    };
    valueAxis.ticks.maxRotation = 0;
    if (horizontal) valueAxis.ticks.maxTicksLimit = 4;
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: css("--series-1"),
          hoverBackgroundColor: css("--accent"),
          borderRadius: { topLeft: horizontal ? 0 : 4, topRight: 4, bottomRight: horizontal ? 4 : 0, bottomLeft: 0 },
          borderSkipped: "start",
          maxBarThickness: 24,
          categoryPercentage: 0.8,
          barPercentage: 0.9,
        }],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: css("--surface"),
            titleColor: css("--text"),
            bodyColor: css("--text-2"),
            borderColor: css("--line"),
            borderWidth: 1,
            padding: 10,
            displayColors: false,
            callbacks: { label: (ctx) => fmtFull(ctx.parsed[horizontal ? "x" : "y"]) },
          },
        },
        scales: horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis },
      },
    });
  }

  function drawAll() {
    if (!window.Chart) return;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    document.querySelectorAll("canvas[data-chart]").forEach((c) => {
      const old = Chart.getChart(c);
      if (old) old.destroy();
      draw(c);
    });
  }
  drawAll();
  // Redraw with the other palette when the OS switches light/dark.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawAll);

  // Picking a store applies it straight away.
  const shopSelect = document.querySelector("select[name=shop]");
  if (shopSelect) shopSelect.addEventListener("change", () => shopSelect.form.submit());

  // Date presets: fill the range relative to the last day that has data, then submit.
  const presets = document.querySelector(".presets");
  if (presets) {
    const form = presets.closest("form");
    const last = new Date(presets.dataset.last + "T00:00:00");
    const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    presets.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      let from, to = new Date(last);
      if (b.dataset.days) {
        from = new Date(last); from.setDate(from.getDate() - Number(b.dataset.days) + 1);
      } else if (b.dataset.month === "this") {
        from = new Date(last.getFullYear(), last.getMonth(), 1);
      } else if (b.dataset.month === "last") {
        from = new Date(last.getFullYear(), last.getMonth() - 1, 1);
        to = new Date(last.getFullYear(), last.getMonth(), 0);
      } else {
        from = new Date(presets.dataset.first + "T00:00:00");
      }
      form.elements.from.value = iso(from);
      form.elements.to.value = iso(to);
      form.submit();
    });
  }
})();
