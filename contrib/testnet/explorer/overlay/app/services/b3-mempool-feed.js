"use strict";

// b3chain live mempool feed.
//
// Single source of truth for everything /live-mempool renders:
//   - the rolling list of unconfirmed transactions (newest first)
//   - the aggregate mempool info card-row (count, bytes, total fees)
//   - the "Mempool Bytes Per Fee Level" snapshot histogram
//
// Architecture (firmware-style verification trace, per
// .cursor/rules/deep-reasoning-firmware.mdc):
//
//   TRIGGER:    init(coreApi, rpcApi) is called once at app boot from
//               b3-bootstrap.js (after RPC connects).
//
//   PROCESS:    pollOnce() is the LOOP. Driven by setInterval(POLL_MS).
//               Each cycle:
//                 1. RPC `getrawmempool true` -> map keyed by txid.
//                 2. Diff against `prev` -> newTxids + removedTxids.
//                 3. For each new txid (bounded concurrency), call
//                    coreApi.getRawTransaction (15-min cached) and
//                    sum vout[].value to get outputSat.
//                 4. Prepend entries to `recent` (cap 200, newest
//                    first).
//                 5. Broadcast over SSE: `tx-added` per new entry,
//                    `tx-removed` once with the array, then `info`
//                    once with the new aggregates.
//                 6. Recompute bytesPerFeeBucket from current
//                    snapshot (fresh each cycle, not running).
//                 7. Save `prev = nextMap`.
//
//   COMPLETION: a new mempool tx reaches every connected SSE client
//               within POLL_MS + RPC latency (~3-4s on testnet).
//
//   BYPASS:     pollOnce() is wrapped in try/catch; one failed cycle
//               just logs and the next interval still runs.
//               If b3chaind is unreachable, recent/prev stay as they
//               were and the page renders whatever the buffer holds.
//               If a client connection drops, EventSource auto-
//               reconnects (default ~3s) and the next `hello` push
//               re-syncs state.
//               There is exactly one code path that broadcasts
//               (pollOnce -> _broadcast); no other path silently
//               skips updating clients.

const POLL_MS = parseInt(process.env.B3CHAIN_MEMPOOL_POLL_MS, 10) || 3000;
const HEARTBEAT_MS = 30_000;
const RING_MAX = 200;
const ENRICH_CONCURRENCY = 4;
const MAX_CLIENTS = 200;

// Fee-rate buckets in sat/vB. Last bucket is "100+".
const FEE_BUCKETS = [1, 2, 3, 5, 8, 12, 20, 30, 50, 75, 100];

// ----- module state -----
let coreApi = null;
let rpcApi = null;
let prev = new Map(); // txid -> rawEntry (verbose getrawmempool entry, with outputSat tacked on)
let recent = []; // newest-first ring (capped at RING_MAX)
const clients = new Set(); // active SSE response objects
let pollTimer = null;
let heartbeatTimer = null;
let lastPollMs = 0;
let lastError = null;
let bytesPerFeeBucket = null;
let aggregateInfo = { count: 0, bytes: 0, totalFeeSat: 0 };

// ----- helpers -----
function _safeJson(obj) {
	return JSON.stringify(obj, (k, v) => (typeof v === "bigint" ? v.toString() : v));
}

function _writeEvent(res, event, payload) {
	try {
		if (event) res.write(`event: ${event}\n`);
		res.write(`data: ${_safeJson(payload)}\n\n`);
	} catch (_err) {
		// res is gone; will be reaped on next 'close'
	}
}

function _broadcast(event, payload) {
	for (const res of clients) {
		_writeEvent(res, event, payload);
	}
}

function _bucketIndex(satPerVb) {
	for (let i = 0; i < FEE_BUCKETS.length; i++) {
		if (satPerVb < FEE_BUCKETS[i]) return i;
	}
	return FEE_BUCKETS.length;
}

function _bucketLabels() {
	const labels = [];
	let prevEdge = 0;
	for (const edge of FEE_BUCKETS) {
		labels.push(`${prevEdge}-${edge}`);
		prevEdge = edge;
	}
	labels.push(`${FEE_BUCKETS[FEE_BUCKETS.length - 1]}+`);
	return labels;
}

function _computeBytesPerFeeBucket() {
	const labels = _bucketLabels();
	const bytes = new Array(labels.length).fill(0);
	for (const entry of prev.values()) {
		const fee = (entry.fees && entry.fees.base) || 0; // BTC
		const vsize = entry.vsize || 1;
		const satPerVb = (fee * 1e8) / vsize;
		bytes[_bucketIndex(satPerVb)] += vsize;
	}
	return { labels, bytes };
}

function _computeAggregate() {
	let bytes = 0;
	let totalFeeSat = 0;
	for (const entry of prev.values()) {
		bytes += entry.vsize || 0;
		totalFeeSat += Math.round(((entry.fees && entry.fees.base) || 0) * 1e8);
	}
	return { count: prev.size, bytes, totalFeeSat };
}

async function _enrichWithOutputSat(txid) {
	try {
		const tx = await coreApi.getRawTransaction(txid);
		if (!tx || !Array.isArray(tx.vout)) return 0;
		let outBtc = 0;
		for (const o of tx.vout) {
			if (typeof o.value === "number") outBtc += o.value;
		}
		return Math.round(outBtc * 1e8);
	} catch (err) {
		// Tx may have been mined or replaced between getrawmempool and
		// our follow-up RPC. Not fatal; we just publish without the
		// output sum.
		return null;
	}
}

async function _enrichBatch(txids) {
	// Simple bounded-concurrency map.
	const results = new Map();
	let cursor = 0;
	async function worker() {
		while (cursor < txids.length) {
			const i = cursor++;
			const txid = txids[i];
			const outputSat = await _enrichWithOutputSat(txid);
			results.set(txid, outputSat);
		}
	}
	const workers = [];
	for (let i = 0; i < Math.min(ENRICH_CONCURRENCY, txids.length); i++) {
		workers.push(worker());
	}
	await Promise.all(workers);
	return results;
}

function _entryFromRaw(txid, raw, outputSat) {
	return {
		txid,
		time: raw.time || 0,
		vsize: raw.vsize || 0,
		weight: raw.weight || (raw.vsize ? raw.vsize * 4 : 0),
		feeSat: Math.round(((raw.fees && raw.fees.base) || 0) * 1e8),
		outputSat: outputSat == null ? null : outputSat,
	};
}

// ----- main loop -----
async function pollOnce() {
	if (!rpcApi) return;
	const t0 = Date.now();
	try {
		// Step 1: one verbose mempool RPC. `getrawmempool true` returns
		// a map keyed by txid; each value has time/vsize/weight/fees etc.
		const next = await rpcApi.getRpcDataWithParams({
			method: "getrawmempool",
			parameters: [true],
		});
		const nextMap = new Map(Object.entries(next || {}));

		// Step 2: diff. New = in next but not in prev. Removed = was in
		// prev but not in next.
		const newTxids = [];
		for (const txid of nextMap.keys()) {
			if (!prev.has(txid)) newTxids.push(txid);
		}
		const removedTxids = [];
		for (const txid of prev.keys()) {
			if (!nextMap.has(txid)) removedTxids.push(txid);
		}

		// Step 3: enrich new txids with output sum. Bounded concurrency.
		const outputSatByTxid = newTxids.length
			? await _enrichBatch(newTxids)
			: new Map();

		// Step 4: build entry objects + prepend to `recent`. We sort
		// new entries by time desc so the buffer order stays correct
		// even when multiple txs arrive in one cycle.
		const newEntries = newTxids.map((txid) =>
			_entryFromRaw(txid, nextMap.get(txid), outputSatByTxid.get(txid)),
		);
		newEntries.sort((a, b) => b.time - a.time);

		// Stash output sums on the per-cycle nextMap entries so the
		// aggregate / fee-bucket recomputation below can reuse them.
		for (const entry of newEntries) {
			const raw = nextMap.get(entry.txid);
			if (raw) raw.outputSat = entry.outputSat;
		}

		// Drop removed entries from `recent`.
		if (removedTxids.length) {
			const removedSet = new Set(removedTxids);
			recent = recent.filter((e) => !removedSet.has(e.txid));
		}

		// Prepend new entries (newest first).
		if (newEntries.length) {
			recent = newEntries.concat(recent);
			if (recent.length > RING_MAX) recent.length = RING_MAX;
		}

		// Step 5: broadcast diffs to all SSE clients. We emit per-tx
		// `tx-added` events (preserves animation order on the client),
		// then one `tx-removed`, then one `info` with refreshed
		// aggregates + fee histogram.
		prev = nextMap; // commit BEFORE broadcasting so any subscriber's
		// follow-up snapshot fetch sees the new state.
		aggregateInfo = _computeAggregate();
		bytesPerFeeBucket = _computeBytesPerFeeBucket();

		for (const entry of newEntries) _broadcast("tx-added", entry);
		if (removedTxids.length) _broadcast("tx-removed", removedTxids);
		if (newEntries.length || removedTxids.length) {
			_broadcast("info", {
				info: aggregateInfo,
				feeHistogram: bytesPerFeeBucket,
			});
		}

		lastPollMs = Date.now() - t0;
		lastError = null;
	} catch (err) {
		lastError = err && err.message ? err.message : String(err);
		// eslint-disable-next-line no-console
		console.error(`[b3-mempool-feed] pollOnce failed: ${lastError}`);
	}
}

function _heartbeat() {
	for (const res of clients) {
		try {
			res.write(":hb\n\n");
		} catch (_err) {
			// dropped; will be reaped on close
		}
	}
}

// ----- public API -----
function init(coreApiArg, rpcApiArg, opts = {}) {
	if (pollTimer) return; // idempotent
	coreApi = coreApiArg;
	rpcApi = rpcApiArg;

	// Kick off the loop AFTER an immediate first poll so /api/snapshot
	// returns useful data on the very first request.
	pollOnce().catch(() => {});
	pollTimer = setInterval(pollOnce, opts.pollMs || POLL_MS);
	heartbeatTimer = setInterval(_heartbeat, opts.heartbeatMs || HEARTBEAT_MS);

	// Don't let these timers keep node alive past intended shutdown.
	if (pollTimer.unref) pollTimer.unref();
	if (heartbeatTimer.unref) heartbeatTimer.unref();

	// eslint-disable-next-line no-console
	console.log(
		`[b3-mempool-feed] init: pollMs=${opts.pollMs || POLL_MS}, ringMax=${RING_MAX}`,
	);
}

function getSnapshot({ limit = 50 } = {}) {
	return {
		txs: recent.slice(0, Math.max(0, limit)),
		info: aggregateInfo,
		feeHistogram: bytesPerFeeBucket || _computeBytesPerFeeBucket(),
		lastPollMs,
		lastError,
		ts: Date.now(),
	};
}

function subscribe(req, res) {
	// Cap concurrent connections so a runaway client cannot DoS us.
	// Oldest client is dropped past the cap (least-recently-added).
	if (clients.size >= MAX_CLIENTS) {
		const oldest = clients.values().next().value;
		if (oldest) {
			try {
				oldest.end();
			} catch (_err) {
				/* ignore */
			}
			clients.delete(oldest);
		}
	}

	res.setHeader("Content-Type", "text/event-stream");
	res.setHeader("Cache-Control", "no-cache, no-transform");
	res.setHeader("Connection", "keep-alive");
	// nginx default proxy_buffering on would swallow the stream until
	// the socket closes; disable it for this response.
	res.setHeader("X-Accel-Buffering", "no");
	res.flushHeaders && res.flushHeaders();

	clients.add(res);

	// Initial sync event: snapshot of the current ring + aggregates.
	_writeEvent(res, "hello", getSnapshot({ limit: 50 }));

	const cleanup = () => {
		clients.delete(res);
		try {
			res.end();
		} catch (_err) {
			/* ignore */
		}
	};
	req.on("close", cleanup);
	req.on("aborted", cleanup);
	res.on("error", cleanup);
}

function getStatus() {
	return {
		lastPollMs,
		prevSize: prev.size,
		recentSize: recent.length,
		clients: clients.size,
		lastError,
		pollMs: POLL_MS,
	};
}

module.exports = {
	init,
	getSnapshot,
	subscribe,
	getStatus,
};
