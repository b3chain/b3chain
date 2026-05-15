"use strict";

// Express router mounted at /charts by app.js.
//
// Routes:
//   GET /charts                  -> category index (mirrors blockchain.com)
//   GET /charts/:id              -> single chart detail page
//   GET /charts/api/:id          -> raw JSON time-series for the chart
//   GET /charts/api/_status      -> aggregator status (debug)
//   GET /charts/api/pools        -> live last-144 doughnut data
//   GET /charts/api/pools-timeseries -> stacked-area data

const express = require("express");
const asyncHandler = require("express-async-handler");

const chartDefs = require("../app/services/b3-chart-defs.js");
const aggregator = require("../app/services/b3-daily-aggregator.js");
const coreApi = require("../app/api/coreApi.js");

const router = express.Router();

router.get(
	"/",
	asyncHandler(async (req, res) => {
		const info = await coreApi.getBlockchainInfo();
		const mempool = await coreApi.getMempoolInfo().catch(() => null);
		const status = aggregator.getStatusSummary();

		res.locals.activeBlockchain = global.activeBlockchain;
		res.locals.tip = info.blocks;
		res.locals.tipDifficulty = info.difficulty;
		res.locals.mempool = mempool;
		res.locals.aggregatorStatus = status;
		res.locals.categories = chartDefs.CATEGORIES;
		res.locals.byCategory = Object.fromEntries(
			chartDefs.CATEGORIES.map((c) => [
				c.id,
				chartDefs.getByCategory(c.id),
			]),
		);
		res.locals.popular = chartDefs.getPopular();

		// Pull the latest day's bucket for "Popular Stats"
		const latestDay = status.latestDay || {};
		res.locals.latestDay = latestDay;

		res.render("b3-charts/index");
	}),
);

router.get(
	"/api/_status",
	asyncHandler(async (req, res) => {
		res.json(aggregator.getStatusSummary());
	}),
);

router.get(
	"/api/pools",
	asyncHandler(async (req, res) => {
		const data = await aggregator.getPoolsDoughnut();
		res.json(data);
	}),
);

router.get(
	"/api/pools-timeseries",
	asyncHandler(async (req, res) => {
		const data = aggregator.getPoolsTimeSeries();
		res.json(data);
	}),
);

router.get(
	"/api/:id",
	asyncHandler(async (req, res) => {
		const def = chartDefs.getChart(req.params.id);
		if (!def) {
			res.status(404).json({ error: "unknown chart id" });
			return;
		}
		if (def.placeholder) {
			res.json({
				placeholder: true,
				note: def.description,
				series: [],
			});
			return;
		}
		if (def.id === "pools") {
			const data = await aggregator.getPoolsDoughnut();
			res.json({ pools: data });
			return;
		}
		if (def.id === "pools-timeseries") {
			res.json(aggregator.getPoolsTimeSeries());
			return;
		}
		const series = aggregator.getSeries(def.id);
		if (series == null) {
			res.json({
				placeholder: true,
				note: "Live-only chart; rendered client-side.",
				series: [],
			});
			return;
		}
		res.json({ series, def });
	}),
);

router.get(
	"/:id",
	asyncHandler(async (req, res) => {
		const def = chartDefs.getChart(req.params.id);
		if (!def) {
			res.status(404);
			res.locals.userMessage = `Unknown chart id: ${req.params.id}`;
			res.render("error");
			return;
		}
		const status = aggregator.getStatusSummary();

		res.locals.def = def;
		res.locals.aggregatorStatus = status;
		res.locals.categories = chartDefs.CATEGORIES;
		res.locals.allCharts = chartDefs.CHARTS;

		res.render("b3-charts/chart-detail");
	}),
);

module.exports = router;
