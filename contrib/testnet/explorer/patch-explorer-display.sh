#!/usr/bin/env bash
# Fix btc-rpc-explorer homepage/explorer display issues on young b3chain testnet:
# - Show all blocks (0..tip) when chain shorter than recentBlocksCount
# - Correct circulating supply (not estimatedSupply underestimate)
# - Non-zero difficulty / hashrate on homepage summary
# - Smart fee "0" instead of "?" when estimates unavailable
# - Genesis coinbase timestamps match v1.1.5 block time
# Idempotent. Run as root on seed1 after install or v1.1.5 cutover.
export LC_ALL=C
set -euo pipefail

EXP_DIR=${EXP_DIR:-/var/lib/b3chain-explorer}
BASEROUTER="$EXP_DIR/node_modules/btc-rpc-explorer/routes/baseRouter.js"
RPC="$EXP_DIR/node_modules/btc-rpc-explorer/app/api/rpcApi.js"
NETSUM="$EXP_DIR/node_modules/btc-rpc-explorer/views/includes/index-network-summary.pug"
GENESIS_TIME=${B3_TESTNET_GENESIS_TIME:-1739145601}

[ -f "$BASEROUTER" ] || { echo "missing $BASEROUTER"; exit 1; }

# --- baseRouter.js: young-chain block list + homepage metrics ---
export EXP_DIR
python3 <<'PY'
from pathlib import Path
import os

exp = os.environ.get("EXP_DIR", "/var/lib/b3chain-explorer")
path = Path(exp) / "node_modules/btc-rpc-explorer/routes/baseRouter.js"
text = path.read_text()

# 1) List blocks 0..tip when the chain is shorter than the homepage window.
old_loop = """\t\tfor (let i = 0; i < (config.site.homepage.recentBlocksCount + 1); i++) {
\t\t\tblockHeights.push(getblockchaininfo.blocks - i);
\t\t}"""
new_loop = """\t\t// B3Chain-young-chain-all-blocks: show genesis..tip when tip < recentBlocksCount
\t\tconst _b3Tip = getblockchaininfo.blocks;
\t\tconst _b3Want = config.site.homepage.recentBlocksCount + 1;
\t\tif (_b3Tip + 1 < _b3Want) {
\t\t\tfor (let _h = 0; _h <= _b3Tip; _h++) {
\t\t\t\tblockHeights.push(_h);
\t\t\t}
\t\t} else {
\t\t\tfor (let i = 0; i < _b3Want; i++) {
\t\t\t\tlet _h = _b3Tip - i;
\t\t\t\tif (_h >= 0) { blockHeights.push(_h); }
\t\t\t}
\t\t}"""
if "B3Chain-young-chain-all-blocks" not in text:
    if old_loop not in text:
        # Already has negative-height guard only — replace that variant
        old_loop = """\t\tfor (let i = 0; i < (config.site.homepage.recentBlocksCount + 1); i++) {
\t\t\tlet _h = getblockchaininfo.blocks - i; if (_h >= 0) { blockHeights.push(_h); } // B3Chain-negative-height-guard
\t\t}"""
        new_loop = new_loop.replace("\t\t\tfor (let i = 0; i < _b3Want; i++) {",
            "\t\t\tfor (let i = 0; i < _b3Want; i++) { // B3Chain-negative-height-guard")
    if old_loop in text:
        text = text.replace(old_loop, new_loop, 1)
        print("baseRouter.js: young-chain block list patched")
    else:
        raise SystemExit("baseRouter.js: blockHeights loop pattern not found")
else:
    print("baseRouter.js: young-chain block list already patched")

# 2) After awaitPromises: supply, hashrate fallback, smart fees on empty mempool.
marker = "\tawait utils.awaitPromises(promises);\n\n\tlet eraStartBlockHeader"
inject = """\tawait utils.awaitPromises(promises);

\t\t// B3Chain-homepage-metrics: young testnet display fixes
\t\ttry {
\t\t\tconst _b3Subsidy = coinConfig.blockRewardFunction(getblockchaininfo.blocks, global.activeBlockchain);
\t\t\tres.locals.b3chainCirculatingSupply = new Decimal((getblockchaininfo.blocks + 1) * _b3Subsidy);
\t\t\tif (!res.locals.hashrate7d || res.locals.hashrate7d <= 0) {
\t\t\t\tres.locals.hashrate7d = getblockchaininfo.difficulty * Math.pow(2, 32) / coinConfig.targetBlockTimeSeconds;
\t\t\t}
\t\t\tif (res.locals.smartFeeEstimates) {
\t\t\t\tfor (const k of Object.keys(res.locals.smartFeeEstimates)) {
\t\t\t\t\tif (res.locals.smartFeeEstimates[k] === "?") {
\t\t\t\t\t\tres.locals.smartFeeEstimates[k] = 0;
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t} catch (_) {}

\t\tlet eraStartBlockHeader"""
if "B3Chain-homepage-metrics" not in text:
    if marker not in text:
        raise SystemExit("baseRouter.js: awaitPromises marker not found")
    text = text.replace(marker, inject, 1)
    print("baseRouter.js: homepage metrics patched")
else:
    print("baseRouter.js: homepage metrics already patched")

path.write_text(text)
PY

# --- index-network-summary.pug: difficulty, coins, hashrate labels ---
if [ -f "$NETSUM" ] && ! grep -q 'B3Chain-small-difficulty' "$NETSUM"; then
    python3 <<PY
from pathlib import Path
import os
exp = os.environ["EXP_DIR"]
path = Path(exp) / "node_modules/btc-rpc-explorer/views/includes/index-network-summary.pug"
text = path.read_text()
old = """\t\tif (getblockchaininfo.difficulty > 1000)
\t\t\tspan.border-dotted(title=parseFloat(getblockchaininfo.difficulty).toLocaleString(), data-bs-toggle="tooltip")
\t\t\t\tspan #{difficultyData[0]}
\t\t\t\tspan x 10
\t\t\t\t\tsup #{difficultyData[1].exponent}

\t\telse
\t\t\tspan #{new Decimal(getblockchaininfo.difficulty).toDP(3)}"""
new = """\t\tif (getblockchaininfo.difficulty > 1000)
\t\t\tspan.border-dotted(title=parseFloat(getblockchaininfo.difficulty).toLocaleString(), data-bs-toggle="tooltip")
\t\t\t\tspan #{difficultyData[0]}
\t\t\t\tspan x 10
\t\t\t\t\tsup #{difficultyData[1].exponent}

\t\telse if (getblockchaininfo.difficulty > 0)
\t\t\t// B3Chain-small-difficulty: toDP(3) rounds 2.5e-5 to 0.000 on young testnet
\t\t\tspan.border-dotted(title=parseFloat(getblockchaininfo.difficulty).toLocaleString(), data-bs-toggle="tooltip") #{new Decimal(getblockchaininfo.difficulty).toExponential(3)}

\t\telse
\t\t\tspan 0"""
if old not in text:
    raise SystemExit("index-network-summary.pug: difficulty block not found")
text = text.replace(old, new, 1)

old2 = """\t\t- var estimatedSupply = utils.estimatedSupply(getblockchaininfo.blocks);

\t\tspan #{parseInt(estimatedSupply).toLocaleString()}"""
new2 = """\t\tif (b3chainCirculatingSupply)
\t\t\t- var estimatedSupply = b3chainCirculatingSupply;
\t\telse
\t\t\t- var estimatedSupply = utils.estimatedSupply(getblockchaininfo.blocks);

\t\tspan #{parseInt(estimatedSupply).toLocaleString()}"""
if "b3chainCirculatingSupply" not in text:
    if old2 not in text:
        raise SystemExit("index-network-summary.pug: coins block not found")
    text = text.replace(old2, new2, 1)

path.write_text(text)
print("index-network-summary.pug: difficulty + coins patched")
PY
fi

# --- rpcApi.js: genesis coinbase time + getBlockByHash fallback ---
if [ -f "$RPC" ]; then
    python3 <<PY
from pathlib import Path
import re

path = Path("$RPC")
text = path.read_text()
genesis_time = int("$GENESIS_TIME")

# getRawTransaction genesis template: use correct block time
needle = """\t\t\t\tlet result = coins[config.coin].genesisCoinbaseTransactionsByNetwork[global.activeBlockchain];
\t\t\t\tresult.confirmations = blockchainInfoResult.blocks;"""
repl = f"""\t\t\t\tlet result = JSON.parse(JSON.stringify(coins[config.coin].genesisCoinbaseTransactionsByNetwork[global.activeBlockchain]));
\t\t\t\tresult.confirmations = blockchainInfoResult.blocks;
\t\t\t\t// B3Chain-genesis-time: upstream template carries Bitcoin-era timestamps
\t\t\t\tif (global.activeBlockchain == "test") {{
\t\t\t\t\tresult.time = {genesis_time};
\t\t\t\t\tresult.blocktime = {genesis_time};
\t\t\t\t}}"""
if "B3Chain-genesis-time" not in text:
    if needle not in text:
        raise SystemExit("rpcApi.js: genesis getRawTransaction pattern not found")
    text = text.replace(needle, repl, 1)
    print("rpcApi.js: genesis coinbase time patched")
else:
    print("rpcApi.js: genesis coinbase time already patched")

# getBlockByHash: after failed getrawtransaction, use genesis template for height 0
if "B3Chain-genesis-block-coinbase" not in text:
    old = """\t\treturn getRawTransaction(block.tx[0], blockHash).then(function(tx) {
\t\t\tblock.coinbaseTx = tx;
\t\t\tblock.totalFees = utils.getBlockTotalFeesFromCoinbaseTxAndBlockHeight(tx, block.height);
\t\t\tblock.miner = utils.identifyMiner(tx, block.height);
\t\t\treturn block;
\t\t})"""
    new = """\t\treturn getRawTransaction(block.tx[0], blockHash).then(function(tx) {
\t\t\tblock.coinbaseTx = tx;
\t\t\tblock.totalFees = utils.getBlockTotalFeesFromCoinbaseTxAndBlockHeight(tx, block.height);
\t\t\tblock.miner = utils.identifyMiner(tx, block.height);
\t\t\treturn block;
\t\t}).catch(function() {
\t\t\t// B3Chain-genesis-block-coinbase: b3chaind may not serve genesis coinbase via getrawtransaction
\t\t\tif (block.height === 0 && coins[config.coin].genesisCoinbaseTransactionsByNetwork[global.activeBlockchain]) {
\t\t\t\tblock.coinbaseTx = JSON.parse(JSON.stringify(coins[config.coin].genesisCoinbaseTransactionsByNetwork[global.activeBlockchain]));
\t\t\t\tblock.coinbaseTx.time = block.time;
\t\t\t\tblock.coinbaseTx.blocktime = block.time;
\t\t\t\tblock.coinbaseTx.blockhash = block.hash;
\t\t\t\tblock.totalFees = 0;
\t\t\t\tblock.miner = utils.identifyMiner(block.coinbaseTx, block.height);
\t\t\t}
\t\t\treturn block;
\t\t})"""
    if old not in text and "B3Chain-genesis-coinbase-fallback" in text:
        print("rpcApi.js: getBlockByHash uses existing B3Chain-genesis-coinbase-fallback")
    elif old in text:
        text = text.replace(old, new, 1)
        print("rpcApi.js: getBlockByHash genesis coinbase patched")
    else:
        print("rpcApi.js: skip getBlockByHash patch (pattern changed)")

path.write_text(text)
PY
fi

systemctl restart b3chain-explorer.service
sleep 5
if ! systemctl is-active --quiet b3chain-explorer.service; then
    echo "ERROR: b3chain-explorer failed to start" >&2
    journalctl -u b3chain-explorer -n 30 --no-pager >&2
    exit 1
fi

if curl -sf http://127.0.0.1:3002/ | grep -q 'Error building page'; then
    echo "ERROR: homepage shows Error building page" >&2
    exit 1
fi
echo "OK: explorer display patch applied and homepage renders"
