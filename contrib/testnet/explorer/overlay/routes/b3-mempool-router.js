"use strict";

// Express router mounted at /live-mempool by b3-bootstrap.js.
//
// Routes:
//   GET /live-mempool                       -> render the live page (Pug)
//   GET /live-mempool/api/snapshot          -> JSON snapshot of the feed
//                                              (initial load + polling
//                                              fallback if SSE blocked)
//   GET /live-mempool/api/stream            -> SSE stream of tx-added /
//                                              tx-removed / info events
//   GET /live-mempool/api/_status           -> debug status of the
//                                              feed service
//
// All /api/* endpoints fall under btc-rpc-explorer's existing
// rate-limit skip for "/api/" (see install.sh "Rate-limiter skip
// list" patch).

const express = require("express");
const asyncHandler = require("express-async-handler");

const feed = require("../app/services/b3-mempool-feed.js");
const aggregator = require("../app/services/b3-daily-aggregator.js");
const coreApi = require("../app/api/coreApi.js");

const router = express.Router();

router.get(
	"/",
	asyncHandler(async (req, res) => {
		const info = await coreApi.getBlockchainInfo().catch(() => null);
		const mempool = await coreApi.getMempoolInfo().catch(() => null);
		const status = aggregator.getStatusSummary();
		const snap = feed.getSnapshot({ limit: 50 });

		res.locals.activeBlockchain = global.activeBlockchain;
		res.locals.tip = info ? info.blocks : null;
		res.locals.mempool = mempool;
		res.locals.aggregatorStatus = status;
		res.locals.latestDay = status.latestDay || {};
		res.locals.initialSnapshot = snap;

		res.render("b3-mempool/live");
	}),
);

router.get(
	"/api/snapshot",
	asyncHandler(async (req, res) => {
		const limit = parseInt(req.query.limit, 10);
		res.set("Cache-Control", "no-store");
		res.json(feed.getSnapshot({ limit: Number.isFinite(limit) ? limit : 50 }));
	}),
);

router.get(
	"/api/stream",
	asyncHandler(async (req, res) => {
		feed.subscribe(req, res);
	}),
);

router.get(
	"/api/_status",
	asyncHandler(async (req, res) => {
		res.json(feed.getStatus());
	}),
);

module.exports = router;
