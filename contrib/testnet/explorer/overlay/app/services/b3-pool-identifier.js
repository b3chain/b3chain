"use strict";

// b3chain miner identification.
//
// btc-rpc-explorer's upstream pool-identification scrapes
// raw.githubusercontent.com for Bitcoin-specific JSONs (which we strip in
// the b3chain installer). For b3chain we do something simpler:
//
//   1. Look at the coinbase outputs and extract the largest payout
//      address (the address receiving the subsidy).
//   2. Look up that address in our static `KNOWN_MINERS` map for a
//      friendly label (e.g. "b3chain testnet pool").
//   3. Fallback: tag the block as `address-only:<addr>` so each unique
//      payout address ends up as its own bucket - which means the
//      Hashrate Distribution doughnut still shows real, useful data
//      even before any pool registers a friendly name.
//
// Operators can edit the KNOWN_MINERS table below to attach friendly
// labels to their payout addresses.

const KNOWN_MINERS = {
	// b3chain testnet pool faucet/payout addresses go here. Example:
	// "tb31qexamplepayoutaddress00000000000000000": {
	//     name: "b3chain testnet pool",
	//     link: "https://pool.b3chain.org",
	// },
};

function shortAddr(addr) {
	if (!addr) return "Unknown";
	if (addr.length <= 16) return addr;
	return addr.slice(0, 8) + "..." + addr.slice(-6);
}

// Identify the miner of a block given its full coinbase tx (from
// getrawtransaction or getblock verbosity=2). Returns:
//   { name, addr, known: bool }
function identifyMiner(coinbaseTx) {
	if (!coinbaseTx || !coinbaseTx.vout || coinbaseTx.vout.length === 0) {
		return { name: "Unknown", addr: null, known: false };
	}

	// Pick the vout with the largest value: the subsidy goes there.
	let best = null;
	for (const v of coinbaseTx.vout) {
		if (!best || (v.value || 0) > (best.value || 0)) best = v;
	}
	if (!best || !best.scriptPubKey) {
		return { name: "Unknown", addr: null, known: false };
	}

	// Bitcoin Core 22+ exposes a single `.address`; older versions exposed
	// `.addresses[0]`. Support both for robustness.
	let addr = best.scriptPubKey.address;
	if (!addr && Array.isArray(best.scriptPubKey.addresses)) {
		addr = best.scriptPubKey.addresses[0];
	}
	if (!addr) {
		return { name: "Unknown", addr: null, known: false };
	}

	const known = KNOWN_MINERS[addr];
	if (known) {
		return { name: known.name, addr, known: true, link: known.link };
	}

	// Use a stable display name based on the address so daily
	// aggregations group correctly across runs.
	return {
		name: `address-only:${addr}`,
		displayName: shortAddr(addr),
		addr,
		known: false,
	};
}

module.exports = {
	KNOWN_MINERS,
	identifyMiner,
	shortAddr,
};
