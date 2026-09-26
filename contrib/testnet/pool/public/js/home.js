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

  function toPoints(rows) {
    return (rows || []).map(function (b) {
      return { x: new Date(b.bucket_at).getTime(), y: parseFloat(b.hashrate_hps) };
    });
  }

  var copyBtn = document.getElementById("copy-pool-url");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var el = document.getElementById("pool-url");
      if (!el || !navigator.clipboard) return;
      navigator.clipboard.writeText(el.textContent || "").then(function () {
        copyBtn.textContent = "Copied";
        setTimeout(function () { copyBtn.textContent = "Copy"; }, 1500);
      }).catch(function () {});
    });
  }

  var bucketNode = document.getElementById("pool-buckets");
  var initialBuckets = [];
  try { initialBuckets = JSON.parse(bucketNode ? bucketNode.textContent || "[]" : "[]"); } catch (e) { initialBuckets = []; }

  var canvas = document.getElementById("pool-chart");
  var chart = canvas && new Chart(canvas, {
    type: "line",
    data: {
      datasets: [{
        label: "Pool hashrate",
        data: toPoints(initialBuckets),
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
        x: { type: "linear", title: { display: true, text: "Time" }, ticks: { callback: function (v) { return new Date(v).toLocaleTimeString(); } } },
        y: { title: { display: true, text: "Hashrate (H/s)" }, ticks: { callback: function (v) { return fmtH(v); } } },
      },
      plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
    },
  });

  function selectRange(range) {
    document.querySelectorAll(".range-row button").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-range") === range ? "true" : "false");
    });
  }
  document.querySelectorAll(".range-row button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var range = btn.getAttribute("data-range");
      selectRange(range);
      fetch("/api/pool/buckets?range=" + encodeURIComponent(range))
        .then(function (r) { return r.json(); })
        .then(function (rows) {
          if (!chart) return;
          chart.data.datasets[0].data = toPoints(rows);
          chart.update("none");
        })
        .catch(function () {});
    });
  });

  var s = io({ path: "/socket.io/" });
  var live = document.getElementById("live-status");
  function showDisconnected() {
    if (!live) return;
    live.hidden = false;
    live.textContent = "Live updates disconnected.";
  }
  function clearDisconnected() {
    if (!live) return;
    live.hidden = true;
    live.textContent = "";
  }
  s.on("connect", clearDisconnected);
  s.on("disconnect", showDisconnected);
  s.on("connect_error", showDisconnected);
  s.on("hashrate:update", function (msg) {
    var note = document.getElementById("share-note");
    if (note) {
      var miners = Number(msg.miners) || 0;
      var rate = Number(msg.hashrate) || 0;
      if (miners > 0 && rate <= 0) {
        var text = "No shares in the last 5 minutes.";
        if (msg.assignedDifficultyText && msg.networkDifficultyText) {
          text += " Assigned difficulty " + msg.assignedDifficultyText + ". Network difficulty " + msg.networkDifficultyText + ".";
        }
        note.hidden = false;
        note.textContent = text;
      } else {
        note.hidden = true;
        note.textContent = "";
      }
    }
    var hashEl = document.getElementById("pool-hashrate");
    var minersEl = document.getElementById("pool-miners");
    var heightEl = document.getElementById("pool-height");
    var blocksEl = document.getElementById("pool-blocks");
    if (hashEl) hashEl.textContent = fmtH(msg.hashrate);
    if (minersEl) minersEl.textContent = msg.miners;
    if (heightEl) heightEl.textContent = msg.height == null ? "—" : msg.height;
    if (blocksEl && msg.blocksFound != null) blocksEl.textContent = msg.blocksFound;
  });
  s.on("block:found", function (msg) {
    var heightEl = document.getElementById("pool-height");
    if (heightEl && msg.height != null) heightEl.textContent = msg.height;
    var blocksEl = document.getElementById("pool-blocks");
    if (blocksEl) blocksEl.textContent = String((parseInt(blocksEl.textContent, 10) || 0) + 1);
    var empty = document.getElementById("no-blocks");
    var table = document.getElementById("blocks-table");
    var body = document.getElementById("recent-blocks");
    var wrap = document.getElementById("blocks-table-wrap");
    if (empty) empty.hidden = true;
    if (wrap) wrap.hidden = false;
    if (table) table.hidden = false;
    if (!body || !msg.hash) return;
    var hash = String(msg.hash).replace(/[^0-9a-f]/gi, "");
    if (!hash) return;
    var when = msg.foundAt || new Date(msg.t).toISOString();
    var tr = document.createElement("tr");
    function cell(text, className) {
      var td = document.createElement("td");
      if (className) td.className = className;
      td.textContent = text;
      return td;
    }
    tr.appendChild(cell(String(msg.height)));
    var hashCell = document.createElement("td");
    hashCell.className = "mono";
    var link = document.createElement("a");
    link.href = "/blocks/" + hash;
    link.textContent = hash.slice(0, 16) + "…";
    hashCell.appendChild(link);
    tr.appendChild(hashCell);
    tr.appendChild(cell(msg.reward != null ? Number(msg.reward).toFixed(4) + " B3C" : "", "num"));
    var need = document.body.getAttribute("data-confirmations") || "100";
    tr.appendChild(cell("0/" + need, "num"));
    var whenCell = document.createElement("td");
    whenCell.className = "muted";
    var time = document.createElement("time");
    time.setAttribute("data-ts", when);
    time.textContent = when;
    whenCell.appendChild(time);
    tr.appendChild(whenCell);
    body.insertBefore(tr, body.firstChild);
    while (body.rows.length > 10) body.removeChild(body.lastChild);
    if (window.formatRelativeTimes) window.formatRelativeTimes();
  });
})();
