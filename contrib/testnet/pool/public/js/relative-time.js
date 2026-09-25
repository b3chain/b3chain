(function () {
  function rel(iso) {
    var t = new Date(iso).getTime();
    if (!isFinite(t)) return iso;
    var sec = Math.round((Date.now() - t) / 1000);
    if (sec < 0) sec = 0;
    if (sec < 60) return sec + "s ago";
    var min = Math.round(sec / 60);
    if (min < 60) return min + " min ago";
    var hr = Math.round(min / 60);
    if (hr < 48) return hr + "h ago";
    var day = Math.round(hr / 24);
    return day + "d ago";
  }
  function formatRelativeTimes() {
    document.querySelectorAll("[data-ts]").forEach(function (el) {
      var raw = el.getAttribute("data-ts");
      if (!raw) return;
      el.textContent = rel(raw);
      el.setAttribute("title", new Date(raw).toLocaleString());
    });
  }
  window.formatRelativeTimes = formatRelativeTimes;
  formatRelativeTimes();
  setInterval(formatRelativeTimes, 30000);
})();
