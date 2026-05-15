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

  var initial = (window.__userBuckets || []).map(function (b) {
    return { x: new Date(b.bucket_at).getTime(), y: parseFloat(b.hashrate_hps) };
  });
  var stats = window.__userInitial || {};

  var hashEl = document.getElementById("user-hashrate");
  var workersEl = document.getElementById("user-workers");
  var balanceEl = document.getElementById("user-balance");
  if (hashEl) hashEl.textContent = fmtH(parseFloat(stats.h || 0));
  if (workersEl) workersEl.textContent = stats.w || 0;
  if (balanceEl) balanceEl.textContent = parseFloat(stats.balance || 0).toFixed(8);

  var canvas = document.getElementById("user-chart");
  var chart = canvas && new Chart(canvas, {
    type: "line",
    data: {
      datasets: [{
        label: "Your hashrate",
        data: initial,
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

  var s = io("/me", { path: "/socket.io/" });
  s.on("hashrate:update", function (msg) {
    if (hashEl) hashEl.textContent = fmtH(msg.hashrate);
    if (workersEl) workersEl.textContent = msg.activeWorkers;
    if (balanceEl) balanceEl.textContent = (msg.balance || 0).toFixed(8);
    pushPoint(msg.t, msg.hashrate);
  });
  s.on("block:found", function (msg) {
    var n = document.createElement("div");
    n.className = "flash flash-success";
    n.textContent = "You just found block #" + msg.height + "!";
    document.querySelector("main.wrap").prepend(n);
  });
  s.on("payout:sent", function (msg) {
    var n = document.createElement("div");
    n.className = "flash flash-success";
    n.textContent = "Payout sent: " + msg.amount + " B3C (txid " + msg.txid.slice(0, 16) + "…)";
    document.querySelector("main.wrap").prepend(n);
  });
})();
