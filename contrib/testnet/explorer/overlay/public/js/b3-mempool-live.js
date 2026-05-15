/* global Chart */
"use strict";

// Client-side controller for /live-mempool.
//
// Wiring (matches the trace in b3-mempool-feed.js):
//
//   DOMContentLoaded
//     -> apply server-rendered `initial` snapshot if present
//     -> GET /live-mempool/api/snapshot (catch-up: first load may have
//        run before the server's first poll cycle landed)
//     -> open EventSource('/live-mempool/api/stream')
//          event: hello       -> full re-sync (same shape as snapshot)
//          event: tx-added    -> prepend row, animate, trim to 50
//          event: tx-removed  -> remove rows by txid
//          event: info        -> refresh aggregate cards + fee chart
//          onerror            -> show "reconnecting..." status; the
//                                browser's EventSource auto-reconnects
//                                on a default ~3s backoff
//     -> if SSE is blocked / never opens, fall back to polling
//        /api/snapshot every 4 s.

(function (root) {
	const MAX_ROWS = 50;
	const POLL_FALLBACK_MS = 4000;
	const ANIMATION_MS = 400;

	const state = {
		opts: null,
		seenTxids: new Set(), // currently rendered, oldest-first arbitrary
		feedListEl: null,
		feedStatusEl: null,
		feedEmptyEl: null,
		chart: null,
		gotFirstSseEvent: false,
		sse: null,
		fallbackTimer: null,
	};

	function shortHash(txid) {
		if (!txid || txid.length < 8) return txid || "";
		return txid.slice(0, 4) + "-" + txid.slice(-4);
	}

	function pad2(n) {
		return n < 10 ? "0" + n : "" + n;
	}

	function formatTime(unixSecs) {
		if (!unixSecs) return "";
		const d = new Date(unixSecs * 1000);
		// M/D/YYYY, HH:MM:SS to match the blockchain.com layout exactly.
		return (
			d.getMonth() +
			1 +
			"/" +
			d.getDate() +
			"/" +
			d.getFullYear() +
			", " +
			pad2(d.getHours()) +
			":" +
			pad2(d.getMinutes()) +
			":" +
			pad2(d.getSeconds())
		);
	}

	function formatB3c(sat) {
		if (sat == null || isNaN(sat)) return "-";
		const b3c = sat / 1e8;
		return b3c.toLocaleString(undefined, {
			minimumFractionDigits: 8,
			maximumFractionDigits: 8,
		});
	}

	function formatInt(n) {
		if (n == null || isNaN(n)) return "-";
		return Number(n).toLocaleString();
	}

	function bind(name, value) {
		const els = document.querySelectorAll('[data-bind="' + name + '"]');
		for (let i = 0; i < els.length; i++) els[i].textContent = value;
	}

	function setStatus(text, state_) {
		if (!state.feedStatusEl) return;
		state.feedStatusEl.textContent = text;
		state.feedStatusEl.setAttribute("data-state", state_ || "ok");
	}

	function renderRow(entry) {
		const li = document.createElement("li");
		li.className = "b3-live-feed__row";
		li.setAttribute("data-txid", entry.txid);

		const a = document.createElement("a");
		a.href = state.opts.txUrlBase + entry.txid;
		a.className = "b3-live-feed__link";

		const hash = document.createElement("span");
		hash.className = "b3-live-feed__hash";
		hash.textContent = "Hash " + shortHash(entry.txid);

		const time = document.createElement("span");
		time.className = "b3-live-feed__time";
		time.textContent = formatTime(entry.time);

		const amount = document.createElement("span");
		amount.className = "b3-live-feed__amount";
		amount.textContent =
			(entry.outputSat == null ? "-" : formatB3c(entry.outputSat)) + " B3C";

		a.appendChild(hash);
		a.appendChild(time);
		a.appendChild(amount);
		li.appendChild(a);
		return li;
	}

	function trimRows() {
		const list = state.feedListEl;
		if (!list) return;
		while (list.children.length > MAX_ROWS) {
			const node = list.lastElementChild;
			if (!node) break;
			const txid = node.getAttribute("data-txid");
			if (txid) state.seenTxids.delete(txid);
			list.removeChild(node);
		}
	}

	function updateEmptyState() {
		if (!state.feedListEl || !state.feedEmptyEl) return;
		state.feedEmptyEl.style.display = state.feedListEl.children.length
			? "none"
			: "";
	}

	function applyTxAdded(entry) {
		if (!entry || !entry.txid) return;
		if (state.seenTxids.has(entry.txid)) return;
		state.seenTxids.add(entry.txid);
		const li = renderRow(entry);
		li.classList.add("b3-fade-in");
		state.feedListEl.insertBefore(li, state.feedListEl.firstChild);
		// Remove the animation class once it's done so re-paints don't
		// re-run the keyframes when the row is moved around.
		setTimeout(function () {
			li.classList.remove("b3-fade-in");
		}, ANIMATION_MS + 50);
		trimRows();
		updateEmptyState();
	}

	function applyTxRemoved(txids) {
		if (!Array.isArray(txids) || txids.length === 0) return;
		for (let i = 0; i < txids.length; i++) {
			const txid = txids[i];
			if (!state.seenTxids.has(txid)) continue;
			const node = state.feedListEl.querySelector(
				'[data-txid="' + txid + '"]',
			);
			if (node) state.feedListEl.removeChild(node);
			state.seenTxids.delete(txid);
		}
		updateEmptyState();
	}

	function renderInitialList(txs) {
		const list = state.feedListEl;
		if (!list) return;
		list.innerHTML = "";
		state.seenTxids.clear();
		if (Array.isArray(txs)) {
			for (let i = 0; i < txs.length && i < MAX_ROWS; i++) {
				const entry = txs[i];
				if (!entry || state.seenTxids.has(entry.txid)) continue;
				state.seenTxids.add(entry.txid);
				list.appendChild(renderRow(entry));
			}
		}
		updateEmptyState();
	}

	function renderFeeChart(feeHistogram) {
		const canvas = document.getElementById("feeLevelChart");
		if (!canvas || typeof Chart === "undefined") return;
		const labels = (feeHistogram && feeHistogram.labels) || [];
		const data = (feeHistogram && feeHistogram.bytes) || [];

		if (state.chart) {
			state.chart.data.labels = labels;
			state.chart.data.datasets[0].data = data;
			state.chart.update("none");
			return;
		}
		state.chart = new Chart(canvas.getContext("2d"), {
			type: "bar",
			data: {
				labels: labels,
				datasets: [
					{
						data: data,
						backgroundColor: labels.map(function (_, i) {
							return "hsl(" + (210 + i * 12) + ", 70%, 55%)";
						}),
					},
				],
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: { legend: { display: false } },
				scales: {
					x: { ticks: { autoSkip: false, font: { size: 10 } } },
					y: { beginAtZero: true, ticks: { font: { size: 10 } } },
				},
			},
		});
	}

	function applyInfo(payload) {
		if (!payload) return;
		const info = payload.info || {};
		bind("mempoolCount", formatInt(info.count));
		bind("mempoolBytes", formatInt(info.bytes));
		bind("mempoolFees", formatB3c(info.totalFeeSat));

		// "Total Transactions" card = today's confirmed + current
		// unconfirmed count. We refresh on every info event so the
		// number tracks the mempool live.
		const latestDay = state.opts.latestDay || {};
		const totalTx = (latestDay.txCount || 0) + (info.count || 0);
		bind("totalTx", formatInt(totalTx));

		if (payload.feeHistogram) renderFeeChart(payload.feeHistogram);
	}

	function applyDailyCards(latestDay) {
		if (!latestDay) return;
		bind("avgTxTime", latestDay.avgBlockGapMin == null
			? "-"
			: Number(latestDay.avgBlockGapMin).toLocaleString(undefined, {
				maximumFractionDigits: 1,
			}));
		bind("confirmationsPerDay", formatInt(latestDay.txCount));
		bind("totalTx", formatInt(latestDay.txCount));
		if (latestDay.txCount != null && latestDay.blockCount) {
			const avg = latestDay.txCount / latestDay.blockCount;
			bind("avgTxPerBlock", avg.toLocaleString(undefined, {
				maximumFractionDigits: 2,
			}));
		} else {
			bind("avgTxPerBlock", "-");
		}
	}

	function applySnapshot(snap) {
		if (!snap) return;
		renderInitialList(snap.txs || []);
		applyInfo({ info: snap.info, feeHistogram: snap.feeHistogram });
	}

	function fetchSnapshot() {
		return fetch(state.opts.snapshotUrl, { credentials: "same-origin" })
			.then(function (r) {
				if (!r.ok) throw new Error("HTTP " + r.status);
				return r.json();
			})
			.then(applySnapshot)
			.catch(function (err) {
				/* eslint-disable no-console */
				console.warn("[b3-live-mempool] snapshot fetch failed:", err);
				/* eslint-enable no-console */
			});
	}

	function startFallbackPolling() {
		if (state.fallbackTimer) return;
		setStatus("polling (no live stream)", "polling");
		state.fallbackTimer = setInterval(fetchSnapshot, POLL_FALLBACK_MS);
	}

	function stopFallbackPolling() {
		if (state.fallbackTimer) {
			clearInterval(state.fallbackTimer);
			state.fallbackTimer = null;
		}
	}

	function openStream() {
		if (typeof EventSource === "undefined") {
			startFallbackPolling();
			return;
		}
		try {
			state.sse = new EventSource(state.opts.streamUrl);
		} catch (err) {
			startFallbackPolling();
			return;
		}

		state.sse.addEventListener("hello", function (evt) {
			state.gotFirstSseEvent = true;
			stopFallbackPolling();
			setStatus("live", "ok");
			try {
				applySnapshot(JSON.parse(evt.data));
			} catch (_e) {}
		});
		state.sse.addEventListener("tx-added", function (evt) {
			state.gotFirstSseEvent = true;
			stopFallbackPolling();
			setStatus("live", "ok");
			try {
				applyTxAdded(JSON.parse(evt.data));
			} catch (_e) {}
		});
		state.sse.addEventListener("tx-removed", function (evt) {
			try {
				applyTxRemoved(JSON.parse(evt.data));
			} catch (_e) {}
		});
		state.sse.addEventListener("info", function (evt) {
			try {
				applyInfo(JSON.parse(evt.data));
			} catch (_e) {}
		});
		state.sse.onerror = function () {
			setStatus("reconnecting...", "reconnecting");
			// If we never got a single event (e.g. nginx buffering, CSP,
			// or a corporate proxy), fall back to polling so the page
			// still updates.
			if (!state.gotFirstSseEvent) {
				startFallbackPolling();
			}
		};
	}

	function init(opts) {
		state.opts = opts || {};
		state.feedListEl = document.getElementById("feedList");
		state.feedStatusEl = document.getElementById("feedStatus");
		state.feedEmptyEl = document.getElementById("feedEmpty");

		applyDailyCards(state.opts.latestDay);

		const initial = state.opts.initial;
		if (initial && Array.isArray(initial.txs)) {
			applySnapshot(initial);
		} else {
			// Server-side rendered snapshot was empty; fetch one now so
			// the page isn't blank while we wait for SSE to deliver
			// `hello`.
			fetchSnapshot();
		}

		openStream();

		// Belt-and-braces: if SSE never delivers an event within ~8s,
		// start the polling fallback. This complements the onerror
		// handler for the case where the connection opens but no event
		// ever arrives (rare but possible behind some proxies).
		setTimeout(function () {
			if (!state.gotFirstSseEvent) startFallbackPolling();
		}, 8000);
	}

	root.B3LiveMempool = { init: init };

	// In case the script loads after DOMContentLoaded the inline
	// initialiser in live.pug guards itself by reading B3LiveMempool;
	// no separate ready handler is needed here.
})(typeof window !== "undefined" ? window : this);
