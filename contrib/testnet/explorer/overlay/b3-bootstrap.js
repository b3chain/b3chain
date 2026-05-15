"use strict";

// Single entry point for all b3chain explorer overlay code.
// app.js calls:
//
//   require("./b3-bootstrap.js")(expressApp, config);
//
// from one sed-injected line, so the patch surface in app.js is
// minimised. Everything we add (router, aggregator init, etc.) is
// wired up here.

module.exports = function bootstrap(expressApp, config) {
	try {
		const b3ChartsRouter = require("./routes/b3-charts-router.js");
		const b3MempoolRouter = require("./routes/b3-mempool-router.js");
		const baseUrl = config.baseUrl || "/";
		const prefix = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
		const chartsMount = prefix + "charts";
		const liveMempoolMount = prefix + "live-mempool";

		// Mount the overlay routers BEFORE the base router (we are
		// called from app.js right before baseActionsRouter is
		// registered).
		expressApp.use(chartsMount, b3ChartsRouter);
		expressApp.use(liveMempoolMount, b3MempoolRouter);

		// Kick off the daily aggregator. It self-schedules a backfill +
		// 30s tip-poll loop and persists to ${dataDir}/daily.json.
		const aggregator = require("./app/services/b3-daily-aggregator.js");
		const coreApi = require("./app/api/coreApi.js");
		const rpcApi = require("./app/api/rpcApi.js");
		const dataDir =
			process.env.B3CHAIN_CHARTS_DATA_DIR ||
			"/var/lib/b3chain-explorer/data";
		aggregator.init(coreApi, rpcApi, { dataDir });

		// Kick off the live mempool feed. Polls `getrawmempool true`
		// every B3CHAIN_MEMPOOL_POLL_MS (default 3000) and broadcasts
		// diffs to /live-mempool/api/stream SSE subscribers.
		const mempoolFeed = require("./app/services/b3-mempool-feed.js");
		mempoolFeed.init(coreApi, rpcApi);

		console.log(
			`[b3-bootstrap] /charts at "${chartsMount}", /live-mempool at "${liveMempoolMount}", aggregator dataDir=${dataDir}`,
		);
	} catch (err) {
		console.error(
			`[b3-bootstrap] failed to wire up b3chain overlay: ${err.message}`,
		);
		console.error(err.stack);
	}
};
