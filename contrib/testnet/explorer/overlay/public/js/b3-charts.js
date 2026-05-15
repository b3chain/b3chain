/* global Chart */
// b3chain charts client helpers.
//
// Loaded by views/b3-charts/chart-detail.pug. Chart.js itself is
// already bundled by btc-rpc-explorer (used by /block-stats etc.) so
// we just call into the global `Chart` constructor.

(function (window) {
	"use strict";

	var COLORS = {
		blue: "#1a4dd6",
		blueSoft: "rgba(26, 77, 214, 0.10)",
		green: "#15a36e",
		amber: "#d97706",
		red: "#dc2626",
		grid: "rgba(15, 23, 42, 0.06)",
		text: "#5a6478",
	};

	var POOL_PALETTE = [
		"#1a4dd6", "#15a36e", "#d97706", "#dc2626", "#7c3aed",
		"#0891b2", "#db2777", "#65a30d", "#ea580c", "#475569",
	];

	var state = {
		chartId: null,
		chartType: "line",
		logY: false,
		unit: "",
		canvas: null,
		loadingEl: null,
		chart: null,
		fullSeries: null,
		fullPoolsTimeSeries: null,
		fullPools: null,
		rangeDays: 0, // 0 = all
		scale: "linear",
	};

	function fmtUnit(v) {
		if (v == null || isNaN(v)) return "-";
		if (state.unit === "H/s") {
			var units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"];
			var i = 0;
			var x = v;
			while (x >= 1000 && i < units.length - 1) {
				x /= 1000;
				i++;
			}
			return x.toFixed(2) + " " + units[i];
		}
		if (state.unit === "B") {
			if (v >= 1e9) return (v / 1e9).toFixed(2) + " GB";
			if (v >= 1e6) return (v / 1e6).toFixed(2) + " MB";
			if (v >= 1e3) return (v / 1e3).toFixed(2) + " kB";
			return v.toFixed(0) + " B";
		}
		if (state.unit === "B3C") return Number(v).toFixed(8) + " B3C";
		if (state.unit === "%") return Number(v).toFixed(3) + "%";
		if (state.unit === "MB") return Number(v).toFixed(2) + " MB";
		if (state.unit === "min") return Number(v).toFixed(2) + " min";
		if (state.unit === "tx/s") return Number(v).toFixed(4) + " tx/s";
		return Number(v).toLocaleString();
	}

	function showLoading(msg) {
		if (!state.loadingEl) return;
		state.loadingEl.classList.remove("is-hidden");
		state.loadingEl.querySelector("span").textContent = msg || "Loading...";
	}

	function hideLoading() {
		if (state.loadingEl) state.loadingEl.classList.add("is-hidden");
	}

	function filteredSeries() {
		if (!state.fullSeries || state.fullSeries.length === 0) return [];
		if (!state.rangeDays || state.rangeDays === 0) return state.fullSeries;
		var cutoff =
			state.fullSeries[state.fullSeries.length - 1].x -
			state.rangeDays * 86400;
		return state.fullSeries.filter(function (p) {
			return p.x >= cutoff;
		});
	}

	function buildLineConfig() {
		var data = filteredSeries().map(function (p) {
			return { x: new Date(p.x * 1000), y: p.y };
		});
		return {
			type: "line",
			data: {
				datasets: [
					{
						label: state.chartId,
						data: data,
						borderColor: COLORS.blue,
						borderWidth: 2,
						backgroundColor: COLORS.blueSoft,
						fill: true,
						pointRadius: 0,
						pointHoverRadius: 4,
						tension: 0.2,
					},
				],
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				animation: false,
				interaction: { intersect: false, mode: "index" },
				plugins: {
					legend: { display: false },
					tooltip: {
						callbacks: {
							label: function (ctx) {
								return fmtUnit(ctx.parsed.y);
							},
							title: function (items) {
								if (!items.length) return "";
								var d = new Date(items[0].parsed.x);
								return d.toISOString().slice(0, 10);
							},
						},
					},
				},
				scales: {
					x: {
						type: "time",
						time: { unit: "day" },
						grid: { color: COLORS.grid },
						ticks: { color: COLORS.text },
					},
					y: {
						type: state.scale === "log" || state.logY ? "logarithmic" : "linear",
						grid: { color: COLORS.grid },
						ticks: {
							color: COLORS.text,
							callback: function (value) {
								return fmtUnit(value);
							},
						},
					},
				},
			},
		};
	}

	function buildDoughnutConfig(pools) {
		var labels = [];
		var values = [];
		var colors = [];
		var i = 0;
		pools.miners.forEach(function (m) {
			labels.push(m.displayName || m.name);
			values.push(m.blocks);
			colors.push(POOL_PALETTE[i % POOL_PALETTE.length]);
			i++;
		});
		return {
			type: "doughnut",
			data: {
				labels: labels,
				datasets: [
					{
						data: values,
						backgroundColor: colors,
						borderColor: "#fff",
						borderWidth: 2,
					},
				],
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: { position: "right", labels: { color: COLORS.text } },
					tooltip: {
						callbacks: {
							label: function (ctx) {
								var total = values.reduce(function (a, b) {
									return a + b;
								}, 0);
								var pct = total ? (ctx.parsed / total) * 100 : 0;
								return ctx.label + ": " + ctx.parsed + " blocks (" + pct.toFixed(1) + "%)";
							},
						},
					},
				},
			},
		};
	}

	function buildStackedAreaConfig(timeSeries) {
		var datasets = timeSeries.series.map(function (s, i) {
			return {
				label: s.displayName || s.name,
				data: s.data.map(function (p) {
					return { x: new Date(p.x * 1000), y: p.y };
				}),
				borderColor: POOL_PALETTE[i % POOL_PALETTE.length],
				backgroundColor: POOL_PALETTE[i % POOL_PALETTE.length],
				fill: true,
				pointRadius: 0,
				borderWidth: 1,
				tension: 0.0,
			};
		});
		return {
			type: "line",
			data: { datasets: datasets },
			options: {
				responsive: true,
				maintainAspectRatio: false,
				animation: false,
				interaction: { intersect: false, mode: "index" },
				plugins: {
					legend: { position: "right", labels: { color: COLORS.text } },
					tooltip: {
						callbacks: {
							title: function (items) {
								if (!items.length) return "";
								var d = new Date(items[0].parsed.x);
								return d.toISOString().slice(0, 10);
							},
						},
					},
				},
				scales: {
					x: {
						type: "time",
						time: { unit: "day" },
						stacked: true,
						grid: { color: COLORS.grid },
						ticks: { color: COLORS.text },
					},
					y: {
						stacked: true,
						grid: { color: COLORS.grid },
						ticks: { color: COLORS.text },
						title: { display: true, text: "Blocks per day" },
					},
				},
			},
		};
	}

	function render() {
		if (!state.canvas) return;
		var cfg;
		if (state.chartType === "doughnut" && state.fullPools) {
			cfg = buildDoughnutConfig(state.fullPools);
		} else if (state.chartType === "stackedArea" && state.fullPoolsTimeSeries) {
			cfg = buildStackedAreaConfig(state.fullPoolsTimeSeries);
		} else {
			cfg = buildLineConfig();
		}
		var ctx = state.canvas.getContext("2d");
		if (state.chart) {
			state.chart.destroy();
		}
		state.chart = new Chart(ctx, cfg);
		hideLoading();
	}

	function fetchAndRender(opts) {
		state.chartId = opts.chartId;
		state.chartType = opts.chartType || "line";
		state.logY = !!opts.logY;
		state.scale = state.logY ? "log" : "linear";
		state.unit = opts.unit || "";
		state.canvas = opts.canvas;
		state.loadingEl = opts.loadingEl;

		if (opts.placeholder) {
			showLoading("No data available - placeholder chart.");
			return;
		}

		showLoading("Loading chart data...");

		var url = "./charts/api/" + state.chartId;
		fetch(url)
			.then(function (r) {
				if (!r.ok) throw new Error("HTTP " + r.status);
				return r.json();
			})
			.then(function (resp) {
				if (state.chartType === "doughnut") {
					state.fullPools = resp.pools || resp;
					if (!state.fullPools || !state.fullPools.miners || state.fullPools.miners.length === 0) {
						showLoading("No miner data yet (chain just started?)");
						return;
					}
				} else if (state.chartType === "stackedArea") {
					state.fullPoolsTimeSeries = resp;
					if (!resp.series || resp.series.length === 0) {
						showLoading("No miner timeseries yet - aggregator warming up.");
						return;
					}
				} else {
					var series = resp.series || [];
					if (series.length === 0) {
						showLoading(
							resp.placeholder
								? "Placeholder chart - no data."
								: "Aggregator is warming up. Refresh in a minute.",
						);
						return;
					}
					state.fullSeries = series;
				}
				render();
			})
			.catch(function (err) {
				showLoading("Error loading chart: " + err.message);
			});
	}

	function setRange(days) {
		state.rangeDays = days || 0;
		render();
	}

	function setScale(scale) {
		state.scale = scale;
		render();
	}

	window.B3Charts = {
		fetchAndRender: fetchAndRender,
		setRange: setRange,
		setScale: setScale,
	};
})(window);
