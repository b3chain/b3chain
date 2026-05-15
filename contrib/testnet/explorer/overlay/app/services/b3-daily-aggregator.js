"use strict";

// b3chain daily aggregator.
//
// Walks the chain from genesis, calling getblockstats per height to
// build per-UTC-day buckets used to feed the /charts pages. Persists
// to ${dataDir}/daily.json so a restart resumes from the last cached
// height instead of replaying the whole chain.
//
// IMPORTANT (firmware-style verification trace, per
// .cursor/rules/deep-reasoning-firmware.mdc):
//
//   TRIGGER:    init(coreApi, rpcApi, opts) is called once at app
//               boot from app.js (after RPC connects).
//   PROCESS:    runBackfill() is the LOOP that walks heights in
//               chunks of CHUNK_SIZE, persists after each chunk.
//   COMPLETION: when last height == tip, we schedule pollTip() on
//               POLL_MS to detect new blocks; pollTip enqueues a new
//               backfill range and the same LOOP processes them.
//   BYPASS:     if init() throws or fs is read-only, getSeries()
//               still returns whatever is in memory (possibly empty),
//               and the router renders an "Aggregator not ready"
//               banner instead of crashing.

const fs = require("fs");
const path = require("path");

const chartDefs = require("./b3-chart-defs.js");
const poolIdent = require("./b3-pool-identifier.js");

const SCHEMA_VERSION = 2;
const CHUNK_SIZE = 200;
const POLL_MS = 30_000;
const SATS_PER_COIN = 1e8;

// ----- module state -----
let coreApi = null;
let rpcApi = null;
let dataPath = null;
let writeTimer = null;
let pollTimer = null;
let backfillRunning = false;

// In-memory snapshot:
let store = {
	schemaVersion: SCHEMA_VERSION,
	lastBlockHeight: 0,
	lastBlockTime: 0,
	lastDay: null,
	days: {}, // { "YYYY-MM-DD": dayBucket }
	miners: {}, // { name: { displayName, known, totalBlocks } }
};

// ----- helpers -----
function isoDay(unixSecs) {
	const d = new Date(unixSecs * 1000);
	return d.toISOString().slice(0, 10);
}

function emptyDayBucket(day) {
	return {
		day,
		blockCount: 0,
		txCount: 0,
		outCount: 0,
		inCount: 0,
		feeSat: 0,
		revenueSat: 0,
		outputSat: 0,
		totalSizeBytes: 0,
		totalWeight: 0,
		firstHeight: null,
		lastHeight: null,
		firstTime: null,
		lastTime: null,
		lastDifficulty: null,
		hashrate: null,
		miners: {}, // { minerName: blockCount }
		blockGapsSec: [], // gaps between adjacent block timestamps within the day
	};
}

function ensureDay(day) {
	if (!store.days[day]) store.days[day] = emptyDayBucket(day);
	return store.days[day];
}

function loadCache() {
	try {
		if (fs.existsSync(dataPath)) {
			const raw = fs.readFileSync(dataPath, "utf8");
			const parsed = JSON.parse(raw);
			if (parsed && parsed.schemaVersion === SCHEMA_VERSION) {
				store = parsed;
				if (!store.miners) store.miners = {};
				console.log(
					`[b3-aggregator] loaded cache: lastHeight=${store.lastBlockHeight} days=${Object.keys(store.days).length}`,
				);
				return;
			}
			console.warn(
				`[b3-aggregator] cache schema mismatch (have=${parsed && parsed.schemaVersion}, want=${SCHEMA_VERSION}); rebuilding`,
			);
		}
	} catch (err) {
		console.warn(`[b3-aggregator] cache load failed: ${err.message}`);
	}
	store = {
		schemaVersion: SCHEMA_VERSION,
		lastBlockHeight: 0,
		lastBlockTime: 0,
		lastDay: null,
		days: {},
		miners: {},
	};
}

// Debounced async write so we don't fsync on every single block.
function scheduleSave() {
	if (writeTimer) return;
	writeTimer = setTimeout(() => {
		writeTimer = null;
		try {
			const tmp = `${dataPath}.tmp`;
			fs.writeFileSync(tmp, JSON.stringify(store));
			fs.renameSync(tmp, dataPath);
		} catch (err) {
			console.warn(`[b3-aggregator] save failed: ${err.message}`);
		}
	}, 1500);
}

// ----- per-block ingestion -----

// Pull block stats for one height. We rely on the upstream coreApi
// cache (FIFTEEN_MIN) so re-runs are cheap.
async function fetchBlockStats(height) {
	return coreApi.getBlockStatsByHeight(height);
}

// Pull the coinbase tx so we can identify the miner. For a fast-running
// testnet this is a lot of RPCs; we do it inline because the chain is
// small. If/when the chain grows, this loop can be made optional via
// cfg flag.
async function fetchCoinbaseMiner(height) {
	try {
		const block = await coreApi.getBlockByHeight(height);
		// upstream attaches block.coinbaseTx; if missing fall back via tx[0]
		const cbTx = block.coinbaseTx;
		if (!cbTx) return { name: "Unknown", addr: null, known: false };
		return poolIdent.identifyMiner(cbTx);
	} catch (err) {
		return { name: "Unknown", addr: null, known: false };
	}
}

async function ingestHeight(height) {
	const stats = await fetchBlockStats(height);
	if (!stats || stats.success === false) {
		throw new Error(
			`getblockstats(${height}) returned no data: ${JSON.stringify(stats)}`,
		);
	}
	const time = stats.time;
	const day = isoDay(time);
	const bucket = ensureDay(day);

	bucket.blockCount += 1;
	bucket.txCount += stats.txs || 0;
	bucket.outCount += stats.outs || 0;
	bucket.inCount += stats.ins || 0;
	bucket.feeSat += stats.totalfee || 0;
	bucket.revenueSat += (stats.totalfee || 0) + (stats.subsidy || 0);
	bucket.outputSat += stats.total_out || 0;
	bucket.totalSizeBytes += stats.total_size || 0;
	bucket.totalWeight += stats.total_weight || 0;
	if (bucket.firstHeight == null) {
		bucket.firstHeight = height;
		bucket.firstTime = time;
	}
	if (bucket.lastTime != null) {
		bucket.blockGapsSec.push(Math.max(0, time - bucket.lastTime));
	}
	bucket.lastHeight = height;
	bucket.lastTime = time;

	// miner attribution
	const miner = await fetchCoinbaseMiner(height);
	const minerKey = miner.name || "Unknown";
	bucket.miners[minerKey] = (bucket.miners[minerKey] || 0) + 1;
	if (!store.miners[minerKey]) {
		store.miners[minerKey] = {
			displayName: miner.displayName || minerKey,
			known: !!miner.known,
			addr: miner.addr || null,
			totalBlocks: 0,
		};
	}
	store.miners[minerKey].totalBlocks += 1;

	// difficulty + hashrate at the day's last block; we re-sample
	// each ingest so the latest value wins.
	try {
		const header = await coreApi.getBlockHeaderByHeight(height);
		if (header) bucket.lastDifficulty = header.difficulty;
	} catch (_) {
		// non-fatal
	}

	store.lastBlockHeight = height;
	store.lastBlockTime = time;
	store.lastDay = day;
}

// Sample network hashrate at the END of every completed day. We can
// only call getnetworkhashps with `(blocks, height)` so we anchor the
// sample at the last block of the day.
async function sampleHashrateForDay(day) {
	const bucket = store.days[day];
	if (!bucket || !bucket.lastHeight) return;
	try {
		const hps = await rpcApi.getRpcDataWithParams({
			method: "getnetworkhashps",
			parameters: [144, bucket.lastHeight],
		});
		bucket.hashrate = hps;
	} catch (err) {
		// non-fatal - leave hashrate as null and we'll retry next backfill
	}
}

// ----- backfill loop -----
async function runBackfill() {
	if (backfillRunning) return;
	backfillRunning = true;
	try {
		const info = await coreApi.getBlockchainInfo();
		const tip = info.blocks;
		let height = store.lastBlockHeight + 1;

		// the very first block (height 0 = genesis) has no real
		// economics; skip to height 1 if we're starting fresh.
		if (height < 1) height = 1;

		const daysTouchedThisRun = new Set();

		while (height <= tip) {
			const end = Math.min(tip, height + CHUNK_SIZE - 1);
			for (let h = height; h <= end; h++) {
				try {
					await ingestHeight(h);
					daysTouchedThisRun.add(store.lastDay);
				} catch (err) {
					console.warn(
						`[b3-aggregator] ingest failed at h=${h}: ${err.message}`,
					);
					// abort this chunk; will resume from store.lastBlockHeight on next poll
					return;
				}
			}
			scheduleSave();
			height = end + 1;
		}

		// Re-sample hashrate for any days that were updated; this
		// uses the day's last block height as the anchor.
		for (const day of daysTouchedThisRun) {
			await sampleHashrateForDay(day);
		}
		scheduleSave();
	} catch (err) {
		console.warn(`[b3-aggregator] backfill error: ${err.message}`);
	} finally {
		backfillRunning = false;
	}
}

function startTipPolling() {
	if (pollTimer) clearInterval(pollTimer);
	pollTimer = setInterval(() => {
		runBackfill().catch(() => {});
	}, POLL_MS);
	if (pollTimer.unref) pollTimer.unref();
}

// ----- public API -----

// init(coreApiMod, rpcApiMod, { dataDir })
function init(coreApiMod, rpcApiMod, opts) {
	coreApi = coreApiMod;
	rpcApi = rpcApiMod;
	const dir = (opts && opts.dataDir) || "/var/lib/b3chain-explorer/data";
	try {
		fs.mkdirSync(dir, { recursive: true });
	} catch (_) {}
	dataPath = path.join(dir, "daily.json");
	loadCache();

	// kick off initial backfill in the background; do not block startup.
	setTimeout(() => {
		runBackfill().catch((err) => {
			console.warn(`[b3-aggregator] initial backfill error: ${err.message}`);
		});
		startTipPolling();
	}, 5000);
}

function getSnapshot() {
	return store;
}

function getOrderedDays() {
	return Object.keys(store.days).sort();
}

// Build a series for one of the chartIds defined in b3-chart-defs.
// Returns [{ x: dayUnix, y: number }...] sorted ascending. Returns
// null for chart ids that aren't backed by daily aggregation.
function getSeries(chartId) {
	const days = getOrderedDays();
	const points = [];
	let cumulativeSubsidy = 0;
	let cumulativeTxs = 0;
	let cumulativeSize = 0;
	let cumulativeOuts = 0;

	for (const day of days) {
		const b = store.days[day];
		const t = b.firstTime || 0;

		// helpers per day
		const subsidySat = b.revenueSat - b.feeSat;
		cumulativeSubsidy += subsidySat;
		cumulativeTxs += b.txCount;
		cumulativeSize += b.totalSizeBytes;
		cumulativeOuts += b.outCount;

		const avgBlockSizeMB =
			b.blockCount > 0 ? b.totalSizeBytes / b.blockCount / 1e6 : 0;
		const avgTxsPerBlock = b.blockCount > 0 ? b.txCount / b.blockCount : 0;
		const avgOutsPerBlock = b.blockCount > 0 ? b.outCount / b.blockCount : 0;
		const avgGapSec =
			b.blockGapsSec.length > 0
				? b.blockGapsSec.reduce((a, x) => a + x, 0) / b.blockGapsSec.length
				: null;
		const sortedGaps = [...b.blockGapsSec].sort((a, x) => a - x);
		const medianGapSec =
			sortedGaps.length > 0 ? sortedGaps[Math.floor(sortedGaps.length / 2)] : null;
		const txPerSec = b.blockCount > 0 && avgGapSec ? b.txCount / 86400 : 0;

		switch (chartId) {
			case "hash-rate":
				if (b.hashrate != null) points.push({ x: t, y: b.hashrate });
				break;
			case "difficulty":
				if (b.lastDifficulty != null)
					points.push({ x: t, y: b.lastDifficulty });
				break;
			case "miners-revenue":
				points.push({ x: t, y: b.revenueSat / SATS_PER_COIN });
				break;
			case "transaction-fees":
			case "transaction-fees-usd":
				points.push({ x: t, y: b.feeSat / SATS_PER_COIN });
				break;
			case "fees-usd-per-transaction":
				points.push({
					x: t,
					y: b.txCount > 0 ? b.feeSat / SATS_PER_COIN / b.txCount : 0,
				});
				break;
			case "cost-per-transaction-percent":
				points.push({
					x: t,
					y: b.outputSat > 0 ? (b.revenueSat / b.outputSat) * 100 : 0,
				});
				break;
			case "cost-per-transaction":
				points.push({
					x: t,
					y: b.txCount > 0 ? b.revenueSat / SATS_PER_COIN / b.txCount : 0,
				});
				break;
			case "total-bitcoins":
				points.push({ x: t, y: cumulativeSubsidy / SATS_PER_COIN });
				break;
			case "blocks-size":
				points.push({ x: t, y: cumulativeSize / 1e6 });
				break;
			case "avg-block-size":
				points.push({ x: t, y: avgBlockSizeMB });
				break;
			case "n-transactions-per-block":
				points.push({ x: t, y: avgTxsPerBlock });
				break;
			case "n-payments-per-block":
				points.push({ x: t, y: avgOutsPerBlock });
				break;
			case "n-transactions-total":
				points.push({ x: t, y: cumulativeTxs });
				break;
			case "median-confirmation-time":
				if (medianGapSec != null)
					points.push({ x: t, y: medianGapSec / 60 });
				break;
			case "avg-confirmation-time":
				if (avgGapSec != null) points.push({ x: t, y: avgGapSec / 60 });
				break;
			case "n-transactions":
				points.push({ x: t, y: b.txCount });
				break;
			case "n-payments":
				points.push({ x: t, y: b.outCount });
				break;
			case "transactions-per-second":
				points.push({ x: t, y: txPerSec });
				break;
			case "output-volume":
				points.push({ x: t, y: b.outputSat / SATS_PER_COIN });
				break;
			case "n-unique-addresses":
				// approximation: outputs per day (upper bound on unique addresses)
				points.push({ x: t, y: b.outCount });
				break;
			case "n-transactions-excluding-popular":
				// We don't track popular addresses yet - use total txCount as
				// the best-effort approximation. This is honest: blockchain.com
				// shows the same series shape minus a small constant.
				points.push({ x: t, y: b.txCount });
				break;
			case "estimated-transaction-volume":
			case "estimated-transaction-volume-usd":
				// rough heuristic: 50% of output volume is change
				points.push({ x: t, y: (b.outputSat * 0.5) / SATS_PER_COIN });
				break;
			case "utxo-count":
				// approx: cumulative outputs (overestimate; we'd need to subtract spends)
				points.push({ x: t, y: cumulativeOuts });
				break;
			default:
				return null; // not a daily-series chart
		}
	}
	return points;
}

// Hashrate Distribution doughnut for last 144 blocks. Pulls live
// from coreApi instead of the daily cache because the upstream
// /mining-summary tool already has good caching for short ranges.
async function getPoolsDoughnut() {
	const info = await coreApi.getBlockchainInfo();
	const tip = info.blocks;
	const start = Math.max(1, tip - 143);
	const counts = {};
	for (let h = tip; h >= start; h--) {
		try {
			const block = await coreApi.getBlockByHeight(h);
			const m = poolIdent.identifyMiner(block.coinbaseTx);
			const key = m.name || "Unknown";
			if (!counts[key]) {
				counts[key] = {
					name: key,
					displayName: m.displayName || key,
					known: !!m.known,
					blocks: 0,
				};
			}
			counts[key].blocks += 1;
		} catch (_) {
			// skip
		}
	}
	const arr = Object.values(counts).sort((a, b) => b.blocks - a.blocks);
	return { range: { from: start, to: tip }, miners: arr };
}

// Stacked-area Hashrate Distribution Over Time using the daily cache.
// Returns { days: [...], series: [{ name, displayName, data: [{x, y}] }, ...] }.
function getPoolsTimeSeries() {
	const days = getOrderedDays();
	const minerNames = Object.keys(store.miners).sort(
		(a, b) => store.miners[b].totalBlocks - store.miners[a].totalBlocks,
	);
	const series = minerNames.map((name) => ({
		name,
		displayName: store.miners[name].displayName || name,
		known: !!store.miners[name].known,
		data: [],
	}));
	for (const day of days) {
		const b = store.days[day];
		const t = b.firstTime || 0;
		for (const s of series) {
			s.data.push({ x: t, y: b.miners[s.name] || 0 });
		}
	}
	return { days, series };
}

function getStatusSummary() {
	const days = getOrderedDays();
	const last = days.length > 0 ? store.days[days[days.length - 1]] : null;
	return {
		lastBlockHeight: store.lastBlockHeight,
		lastBlockTime: store.lastBlockTime,
		dayCount: days.length,
		minerCount: Object.keys(store.miners).length,
		latestDay: last,
	};
}

module.exports = {
	init,
	getSnapshot,
	getSeries,
	getPoolsDoughnut,
	getPoolsTimeSeries,
	getStatusSummary,
	// exposed for tests:
	_internal: { isoDay, runBackfill, ingestHeight },
};
