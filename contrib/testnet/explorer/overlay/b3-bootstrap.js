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
		const baseUrl = config.baseUrl || "/";
		const mount =
			(baseUrl.endsWith("/") ? baseUrl : baseUrl + "/") + "charts";

		// Mount the charts router BEFORE the base router (we are called
		// from app.js right before baseActionsRouter is registered).
		expressApp.use(mount, b3ChartsRouter);

		// Kick off the daily aggregator. It self-schedules a backfill +
		// 30s tip-poll loop and persists to ${dataDir}/daily.json.
		const aggregator = require("./app/services/b3-daily-aggregator.js");
		const coreApi = require("./app/api/coreApi.js");
		const rpcApi = require("./app/api/rpcApi.js");
		const dataDir =
			process.env.B3CHAIN_CHARTS_DATA_DIR ||
			"/var/lib/b3chain-explorer/data";
		aggregator.init(coreApi, rpcApi, { dataDir });

		console.log(
			`[b3-bootstrap] /charts mounted at "${mount}", aggregator dataDir=${dataDir}`,
		);
	} catch (err) {
		console.error(
			`[b3-bootstrap] failed to wire up b3chain charts overlay: ${err.message}`,
		);
		console.error(err.stack);
	}
};
