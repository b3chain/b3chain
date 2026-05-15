"use strict";

// b3chain charts: single source of truth for every chart we render under
// /charts. The router and views read this list to build menus, headers,
// and to dispatch the daily aggregator series. URL slugs intentionally
// mirror blockchain.com (e.g. /charts/hash-rate) so external links from
// other Bitcoin docs land on a recognisable page.
//
// Fields:
//   id            URL slug (also series key in the aggregator)
//   title         Page title
//   shortLabel    Card-grid label
//   description   Subtitle / tooltip
//   category      One of: currency-stats | block-details | mining
//                 | network-activity | market-signals
//   unit          Y-axis unit string (B3C, sat, TH/s, %, MB, ...)
//   chartType     line | doughnut | stackedArea
//   logY          true to use logarithmic y-axis
//   placeholder   true if the chart needs data we don't have (USD price)
//   popular       true if it appears in the top "Popular Stats" row
//   summary       function(latest) -> { value, unit } for the headline number
//   sourceNote    optional explanatory footnote shown below the chart

const BIG = 1e9;

function fmtNum(n, dp = 0) {
	if (n == null || isNaN(n)) return "-";
	return Number(n).toLocaleString(undefined, {
		minimumFractionDigits: dp,
		maximumFractionDigits: dp,
	});
}

function fmtSat(sat, dp = 8) {
	if (sat == null) return "-";
	return (sat / 1e8).toLocaleString(undefined, {
		minimumFractionDigits: 0,
		maximumFractionDigits: dp,
	});
}

function fmtHashes(hps) {
	if (!hps) return "-";
	const units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"];
	let i = 0;
	let v = hps;
	while (v >= 1000 && i < units.length - 1) {
		v /= 1000;
		i++;
	}
	return `${v.toFixed(2)} ${units[i]}`;
}

const CHARTS = [
	// ---------- Mining Information ----------
	{
		id: "hash-rate",
		title: "Total Hash Rate (TH/s)",
		shortLabel: "Total Hash Rate (TH/s)",
		description:
			"The estimated hashes per second the b3chain network is performing in the last 24 hours.",
		category: "mining",
		unit: "H/s",
		chartType: "line",
		logY: true,
		popular: true,
		summary: (d) => ({ value: fmtHashes(d.hashrate), unit: "" }),
	},
	{
		id: "pools",
		title: "Hashrate Distribution",
		shortLabel: "Hashrate Distribution",
		description:
			"An estimation of hashrate distribution amongst the largest miners over the last 144 blocks.",
		category: "mining",
		unit: "%",
		chartType: "doughnut",
		summary: (d) => ({ value: `${d.poolCount || 0} miners`, unit: "" }),
	},
	{
		id: "pools-timeseries",
		title: "Hashrate Distribution Over Time",
		shortLabel: "Hashrate Distribution Over Time",
		description:
			"An estimation of hashrate distribution over time amongst the largest miners.",
		category: "mining",
		unit: "%",
		chartType: "stackedArea",
		summary: (d) => ({ value: `${d.poolCount || 0} miners`, unit: "" }),
	},
	{
		id: "difficulty",
		title: "Network Difficulty",
		shortLabel: "Network Difficulty",
		description:
			"A relative measure of how difficult it is to mine a new block for the b3chain blockchain.",
		category: "mining",
		unit: "",
		chartType: "line",
		logY: true,
		popular: true,
		summary: (d) => ({ value: fmtNum(d.difficulty, 4), unit: "" }),
	},
	{
		id: "miners-revenue",
		title: "Miners Revenue (B3C)",
		shortLabel: "Miners Revenue",
		description:
			"Total value in B3C of coinbase block rewards and transaction fees paid to miners.",
		category: "mining",
		unit: "B3C",
		chartType: "line",
		summary: (d) => ({ value: fmtSat(d.revenueSat, 4), unit: "B3C" }),
	},
	{
		id: "transaction-fees",
		title: "Total Transaction Fees (B3C)",
		shortLabel: "Total Transaction Fees (B3C)",
		description:
			"The total B3C value of all transaction fees paid to miners. This does not include coinbase block rewards.",
		category: "mining",
		unit: "B3C",
		chartType: "line",
		summary: (d) => ({ value: fmtSat(d.feeSat, 8), unit: "B3C" }),
	},
	{
		id: "transaction-fees-usd",
		title: "Total Transaction Fees (B3C)",
		shortLabel: "Total Transaction Fees (USD)",
		description:
			"On bitcoin's chart this is denominated in USD. b3chain has no exchange listing, so we render the equivalent series in B3C.",
		category: "mining",
		unit: "B3C",
		chartType: "line",
		sourceNote:
			"USD-denominated series unavailable: b3chain has no exchange listing. Showing same series in B3C.",
		summary: (d) => ({ value: fmtSat(d.feeSat, 8), unit: "B3C" }),
	},
	{
		id: "fees-usd-per-transaction",
		title: "Fees Per Transaction (B3C)",
		shortLabel: "Fees Per Transaction (USD)",
		description:
			"Average transaction fees per transaction. Bitcoin's chart is in USD; we show B3C since b3chain has no exchange listing.",
		category: "mining",
		unit: "B3C",
		chartType: "line",
		sourceNote: "USD-denominated series unavailable. Showing B3C.",
		summary: (d) => ({ value: fmtSat(d.feePerTxSat, 8), unit: "B3C" }),
	},
	{
		id: "cost-per-transaction-percent",
		title: "Cost % of Transaction Volume",
		shortLabel: "Cost % of Transaction Volume",
		description:
			"Miners revenue (subsidy + fees) as a percentage of total transaction volume.",
		category: "mining",
		unit: "%",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.costPercent, 3), unit: "%" }),
	},
	{
		id: "cost-per-transaction",
		title: "Cost Per Transaction (B3C)",
		shortLabel: "Cost Per Transaction",
		description:
			"Miners revenue divided by the number of transactions, denominated in B3C.",
		category: "mining",
		unit: "B3C",
		chartType: "line",
		summary: (d) => ({ value: fmtSat(d.revenuePerTxSat, 6), unit: "B3C" }),
	},

	// ---------- Currency Statistics ----------
	{
		id: "total-bitcoins",
		title: "Total Circulating B3C",
		shortLabel: "Total Circulating B3C",
		description:
			"The total number of mined B3C currently circulating on the network.",
		category: "currency-stats",
		unit: "B3C",
		chartType: "line",
		summary: (d) => ({ value: fmtSat(d.cumulativeSubsidySat, 0), unit: "B3C" }),
	},
	{
		id: "market-price",
		title: "Market Price (USD)",
		shortLabel: "Market Price (USD)",
		description:
			"The average USD market price across major exchanges. b3chain has no exchange listing yet.",
		category: "currency-stats",
		unit: "USD",
		chartType: "line",
		placeholder: true,
	},
	{
		id: "market-cap",
		title: "Market Capitalization (USD)",
		shortLabel: "Market Capitalization (USD)",
		description:
			"The total USD value of B3C in circulation. b3chain has no exchange listing yet.",
		category: "currency-stats",
		unit: "USD",
		chartType: "line",
		placeholder: true,
	},
	{
		id: "trade-volume",
		title: "Exchange Trade Volume (USD)",
		shortLabel: "Exchange Trade Volume (USD)",
		description:
			"The total USD value of trading volume on major exchanges. b3chain has no exchange listing yet.",
		category: "currency-stats",
		unit: "USD",
		chartType: "line",
		placeholder: true,
	},

	// ---------- Block Details ----------
	{
		id: "blocks-size",
		title: "Blockchain Size (MB)",
		shortLabel: "Blockchain Size (MB)",
		description:
			"The total size of the blockchain (sum of serialized block sizes) in megabytes.",
		category: "block-details",
		unit: "MB",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.chainSizeMB, 2), unit: "MB" }),
	},
	{
		id: "avg-block-size",
		title: "Average Block Size (MB)",
		shortLabel: "Average Block Size (MB)",
		description:
			"The average block size over the past 24 hours in megabytes.",
		category: "block-details",
		unit: "MB",
		chartType: "line",
		popular: true,
		summary: (d) => ({ value: fmtNum(d.avgBlockSizeMB, 4), unit: "MB" }),
	},
	{
		id: "n-transactions-per-block",
		title: "Average Transactions Per Block",
		shortLabel: "Average Transactions Per Block",
		description:
			"The average number of transactions per block over the past 24 hours.",
		category: "block-details",
		unit: "tx",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.avgTxsPerBlock, 2), unit: "" }),
	},
	{
		id: "n-payments-per-block",
		title: "Average Payments Per Block",
		shortLabel: "Average Payments Per Block",
		description:
			"The average number of outputs per block over the past 24 hours (used as a proxy for payments).",
		category: "block-details",
		unit: "out",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.avgOutsPerBlock, 2), unit: "" }),
	},
	{
		id: "n-transactions-total",
		title: "Total Number of Transactions",
		shortLabel: "Total Number of Transactions",
		description: "The total number of transactions on the blockchain.",
		category: "block-details",
		unit: "tx",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.cumulativeTxCount), unit: "" }),
	},
	{
		id: "median-confirmation-time",
		title: "Median Confirmation Time",
		shortLabel: "Median Confirmation Time",
		description:
			"Median time between block timestamps - a proxy for inter-block latency.",
		category: "block-details",
		unit: "min",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.medianBlockGapMin, 2), unit: "min" }),
	},
	{
		id: "avg-confirmation-time",
		title: "Average Confirmation Time",
		shortLabel: "Average Confirmation Time",
		description:
			"Average time between block timestamps - a proxy for inter-block latency.",
		category: "block-details",
		unit: "min",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.avgBlockGapMin, 2), unit: "min" }),
	},

	// ---------- Network Activity ----------
	{
		id: "n-unique-addresses",
		title: "Unique Output Addresses Per Day",
		shortLabel: "Unique Addresses Used",
		description:
			"The number of distinct output addresses observed on-chain per day (sample size scales with chain activity).",
		category: "network-activity",
		unit: "addr",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.uniqueAddrs), unit: "" }),
	},
	{
		id: "n-transactions",
		title: "Confirmed Transactions Per Day",
		shortLabel: "Confirmed Transactions Per Day",
		description: "The total number of confirmed transactions per day.",
		category: "network-activity",
		unit: "tx",
		chartType: "line",
		popular: true,
		summary: (d) => ({ value: fmtNum(d.txCount), unit: "" }),
	},
	{
		id: "n-payments",
		title: "Confirmed Payments Per Day",
		shortLabel: "Confirmed Payments Per Day",
		description: "The total number of confirmed outputs per day.",
		category: "network-activity",
		unit: "out",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.outCount), unit: "" }),
	},
	{
		id: "transactions-per-second",
		title: "Transaction Rate Per Second",
		shortLabel: "Transaction Rate Per Second",
		description:
			"The number of confirmed transactions added to the chain per second.",
		category: "network-activity",
		unit: "tx/s",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.txPerSec, 4), unit: "tx/s" }),
	},
	{
		id: "output-volume",
		title: "Output Value Per Day (B3C)",
		shortLabel: "Output Value Per Day",
		description:
			"The total value of all transaction outputs per day. Includes coins returned to the sender as change.",
		category: "network-activity",
		unit: "B3C",
		chartType: "line",
		summary: (d) => ({ value: fmtSat(d.outputSat, 4), unit: "B3C" }),
	},
	{
		id: "mempool-count",
		title: "Mempool Transaction Count",
		shortLabel: "Mempool Transaction Count",
		description:
			"The total number of unconfirmed transactions in the mempool (live).",
		category: "network-activity",
		unit: "tx",
		chartType: "line",
		live: true,
	},
	{
		id: "mempool-growth",
		title: "Mempool Size Growth",
		shortLabel: "Mempool Size Growth",
		description:
			"The rate at which the mempool is growing in bytes per second (live).",
		category: "network-activity",
		unit: "B/s",
		chartType: "line",
		live: true,
	},
	{
		id: "mempool-size",
		title: "Mempool Size (Bytes)",
		shortLabel: "Mempool Size (Bytes)",
		description:
			"The aggregate size in bytes of transactions waiting to be confirmed (live).",
		category: "network-activity",
		unit: "B",
		chartType: "line",
		popular: true,
		live: true,
	},
	{
		id: "mempool-state-by-fee-level",
		title: "Mempool Bytes Per Fee Level",
		shortLabel: "Mempool Bytes Per Fee Level",
		description:
			"The current state of the mempool organized by bytes per fee level (live).",
		category: "network-activity",
		unit: "B",
		chartType: "stackedArea",
		live: true,
	},
	{
		id: "utxo-count",
		title: "Unspent Transaction Outputs",
		shortLabel: "Unspent Transaction Outputs",
		description:
			"The cumulative number of valid unspent transaction outputs.",
		category: "network-activity",
		unit: "utxo",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.utxoCount), unit: "" }),
	},
	{
		id: "n-transactions-excluding-popular",
		title: "Transactions Excluding Popular Addresses",
		shortLabel: "Transactions Excluding Popular Addresses",
		description:
			"Confirmed transactions per day excluding the network's 100 most popular output addresses.",
		category: "network-activity",
		unit: "tx",
		chartType: "line",
		summary: (d) => ({ value: fmtNum(d.txCountExcludingPopular), unit: "" }),
	},
	{
		id: "estimated-transaction-volume",
		title: "Estimated Transaction Value (B3C)",
		shortLabel: "Estimated Transaction Value (B3C)",
		description:
			"The total estimated value in B3C of transactions on the blockchain (output volume minus change estimate).",
		category: "network-activity",
		unit: "B3C",
		chartType: "line",
		summary: (d) => ({ value: fmtSat(d.estimatedVolumeSat, 4), unit: "B3C" }),
	},
	{
		id: "estimated-transaction-volume-usd",
		title: "Estimated Transaction Value (B3C)",
		shortLabel: "Estimated Transaction Value (USD)",
		description:
			"On bitcoin's chart this is denominated in USD. b3chain has no exchange listing; rendered in B3C.",
		category: "network-activity",
		unit: "B3C",
		chartType: "line",
		sourceNote: "USD-denominated series unavailable. Showing B3C.",
		summary: (d) => ({ value: fmtSat(d.estimatedVolumeSat, 4), unit: "B3C" }),
	},

	// ---------- Market Signals (placeholders, need price feed) ----------
	{
		id: "mvrv",
		title: "Market Value to Realised Value",
		shortLabel: "Market Value to Realised Value",
		description:
			"MVRV requires a USD market price for B3C; b3chain has no exchange listing yet.",
		category: "market-signals",
		unit: "ratio",
		chartType: "line",
		placeholder: true,
	},
	{
		id: "nvt",
		title: "Network Value to Transactions",
		shortLabel: "Network Value to Transactions",
		description:
			"NVT requires a USD market price for B3C; b3chain has no exchange listing yet.",
		category: "market-signals",
		unit: "ratio",
		chartType: "line",
		placeholder: true,
	},
	{
		id: "nvts",
		title: "Network Value to Transactions Signal",
		shortLabel: "Network Value to Transactions Signal",
		description:
			"NVTS requires a USD market price for B3C; b3chain has no exchange listing yet.",
		category: "market-signals",
		unit: "ratio",
		chartType: "line",
		placeholder: true,
	},
];

const CATEGORIES = [
	{
		id: "currency-stats",
		title: "Currency Statistics",
	},
	{
		id: "block-details",
		title: "Block Details",
	},
	{
		id: "mining",
		title: "Mining Information",
	},
	{
		id: "network-activity",
		title: "Network Activity",
	},
	{
		id: "market-signals",
		title: "Market Signals",
	},
];

const byId = new Map(CHARTS.map((c) => [c.id, c]));
const byCategory = new Map();
for (const c of CHARTS) {
	if (!byCategory.has(c.category)) byCategory.set(c.category, []);
	byCategory.get(c.category).push(c);
}

module.exports = {
	CHARTS,
	CATEGORIES,
	getChart: (id) => byId.get(id),
	getByCategory: (catId) => byCategory.get(catId) || [],
	getPopular: () => CHARTS.filter((c) => c.popular),
	formatters: { fmtNum, fmtSat, fmtHashes },
};
