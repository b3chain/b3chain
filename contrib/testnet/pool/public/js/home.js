(function () {
  function fmtH(h) {
    if (!isFinite(h) || h <= 0) return "0 H/s";
    if (h >= 1e15) return (h/1e15).toFixed(2) + " PH/s";
    if (h >= 1e12) return (h/1e12).toFixed(2) + " TH/s";
    if (h >= 1e9)  return (h/1e9).toFixed(2)  + " GH/s";
    if (h >= 1e6)  return (h/1e6).toFixed(2)  + " MH/s";
    if (h >= 1e3)  return (h/1e3).toFixed(2)  + " kH/s";
    return h.toFixed(2) + " H/s";
  }

  var initialBuckets = (window.__poolBuckets || []).map(function (b) {
    return { x: new Date(b.bucket_at).getTime(), y: parseFloat(b.hashrate_hps) };
  });

  var canvas = document.getElementById("pool-chart");
  var chart = canvas && new Chart(canvas, {
    type: "line",
    data: {
      datasets: [{
        label: "Pool hashrate",
        data: initialBuckets,
        borderColor: "#1a4a8c",
        backgroundColor: "rgba(26,74,140,0.10)",
        fill: true,
        pointRadius: 0,
        tension: 0.2,
        borderWidth: 2,
      }],
    },
    options: {
      animation: false,
      responsive: true,
      scales: {
        x: { type: "linear", ticks: { callback: function (v) { return new Date(v).toLocaleTimeString(); } } },
        y: { ticks: { callback: function (v) { return fmtH(v); } } },
      },
      plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
    },
  });

  function pushPoint(t, y) {
    if (!chart) return;
    var ds = chart.data.datasets[0].data;
    ds.push({ x: t, y: y });
    var cutoff = Date.now() - 24 * 3600 * 1000;
    while (ds.length > 0 && ds[0].x < cutoff) ds.shift();
    chart.update("none");
  }

  var s = io({ path: "/socket.io/" });
  s.on("hashrate:update", function (msg) {
    var hashEl = document.getElementById("pool-hashrate");
    var minersEl = document.getElementById("pool-miners");
    var heightEl = document.getElementById("pool-height");
    if (hashEl) hashEl.textContent = fmtH(msg.hashrate);
    if (minersEl) minersEl.textContent = msg.miners;
    if (heightEl) heightEl.textContent = msg.height == null ? "—" : msg.height;
    pushPoint(msg.t, msg.hashrate);
  });
  s.on("block:found", function (msg) {
    var heightEl = document.getElementById("pool-height");
    if (heightEl) heightEl.textContent = msg.height;
  });
})();
