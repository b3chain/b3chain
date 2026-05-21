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
new_inner = """\t\t\t// B3Chain-young-chain-all-blocks: show genesis..tip when tip < recentBlocksCount
\t\t\tconst _b3Tip = getblockchaininfo.blocks;
\t\t\tconst _b3Want = config.site.homepage.recentBlocksCount + 1;
\t\t\tif (_b3Tip + 1 < _b3Want) {
\t\t\t\tfor (let _h = 0; _h <= _b3Tip; _h++) {
\t\t\t\t\tblockHeights.push(_h);
\t\t\t\t}
\t\t\t} else {
\t\t\t\tfor (let i = 0; i < _b3Want; i++) {
\t\t\t\t\tlet _h = _b3Tip - i;
\t\t\t\t\tif (_h >= 0) { blockHeights.push(_h); } // B3Chain-negative-height-guard
\t\t\t\t}
\t\t\t}"""
old_blocks = [
    """\t\tif (getblockchaininfo.blocks) {
\t\t\t// +1 to page size here so we have the next block to calculate T.T.M.
\t\t\tfor (let i = 0; i < (config.site.homepage.recentBlocksCount + 1); i++) {
\t\t\t\tblockHeights.push(getblockchaininfo.blocks - i);
\t\t\t}
\t\t}""",
    """\t\tif (getblockchaininfo.blocks) {
\t\t\t// +1 to page size here so we have the next block to calculate T.T.M.
\t\t\tfor (let i = 0; i < (config.site.homepage.recentBlocksCount + 1); i++) {
\t\t\t\tlet _h = getblockchaininfo.blocks - i; if (_h >= 0) { blockHeights.push(_h); } // B3Chain-negative-height-guard
\t\t\t}
\t\t}""",
    # Legacy bare loop (pre-if-wrapper installs)
    """\t\tfor (let i = 0; i < (config.site.homepage.recentBlocksCount + 1); i++) {
\t\t\tblockHeights.push(getblockchaininfo.blocks - i);
\t\t}""",
    """\t\tfor (let i = 0; i < (config.site.homepage.recentBlocksCount + 1); i++) {
\t\t\tlet _h = getblockchaininfo.blocks - i; if (_h >= 0) { blockHeights.push(_h); } // B3Chain-negative-height-guard
\t\t}""",
]
new_blocks = [
    """\t\tif (getblockchaininfo.blocks) {
\t\t\t// +1 to page size here so we have the next block to calculate T.T.M.
""" + new_inner + """
\t\t}""",
] * 4  # same replacement for all variants
if "B3Chain-young-chain-all-blocks" not in text:
    patched = False
    for old_loop, new_loop in zip(old_blocks, new_blocks):
        if old_loop in text:
            text = text.replace(old_loop, new_loop, 1)
            patched = True
            print("baseRouter.js: young-chain block list patched")
            break
    if not patched:
        raise SystemExit("baseRouter.js: blockHeights loop pattern not found")
else:
    print("baseRouter.js: young-chain block list already patched")

# 2) After homepage awaitPromises: supply, hashrate fallback, smart fees on empty mempool.
import re
if "B3Chain-homepage-metrics" not in text:
    m = re.search(
        r"(\t\tawait utils\.awaitPromises\(promises\);\s*\n)(\t\tlet eraStartBlockHeader = res\.locals\.difficultyPeriodFirstBlockHeader)",
        text,
    )
    if not m:
        raise SystemExit("baseRouter.js: awaitPromises marker not found")
    inject = m.group(1) + """\t\t// B3Chain-homepage-metrics: young testnet display fixes
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

""" + m.group(2)
    text = text[: m.start()] + inject + text[m.end() :]
    print("baseRouter.js: homepage metrics patched")
else:
    print("baseRouter.js: homepage metrics already patched")

path.write_text(text)
PY

# --- index-network-summary.pug: difficulty, coins, hashrate labels ---
if [ -f "$NETSUM" ] && ! grep -q 'B3Chain-small-difficulty' "$NETSUM"; then
    python3 <<PY
from pathlib import Path
import os, re

exp = os.environ["EXP_DIR"]
path = Path(exp) / "node_modules/btc-rpc-explorer/views/includes/index-network-summary.pug"
text = path.read_text()

else_pat = re.compile(
    r"(?P<ind>\t+)else\n(?P=ind)\tspan #\{new Decimal\(getblockchaininfo\.difficulty\)\.toDP\(3\)\}\n",
    re.MULTILINE,
)
else_repl = (
    r"\1else if (getblockchaininfo.difficulty > 0)\n"
    r"\1\t// B3Chain-small-difficulty: toDP(3) rounds young testnet difficulty to 0.000\n"
    r"\1\tspan.border-dotted(title=parseFloat(getblockchaininfo.difficulty).toLocaleString(), "
    r'data-bs-toggle="tooltip") #{new Decimal(getblockchaininfo.difficulty).toExponential(3)}\n'
    r"\n\1else\n\1\tspan 0\n"
)

if "B3Chain-small-difficulty" not in text:
    text2, n = else_pat.subn(else_repl, text, count=1)
    if n != 1:
        raise SystemExit("index-network-summary.pug: difficulty else branch not found")
    text = text2
    print("index-network-summary.pug: difficulty patched")

coins_pat = re.compile(
    r"(?P<ind>\t+)- var estimatedSupply = utils\.estimatedSupply\(getblockchaininfo\.blocks\);\n"
    r"\n"
    r"(?P=ind)span #\{parseInt\(estimatedSupply\)\.toLocaleString\(\)\}",
    re.MULTILINE,
)

def coins_repl(m):
    ind = m.group("ind")
    return (
        f"{ind}if (b3chainCirculatingSupply)\n"
        f"{ind}\t- var estimatedSupply = b3chainCirculatingSupply;\n"
        f"{ind}else\n"
        f"{ind}\t- var estimatedSupply = utils.estimatedSupply(getblockchaininfo.blocks);\n"
        f"\n"
        f"{ind}span #{{parseInt(estimatedSupply).toLocaleString()}}"
    )

# Repair a prior broken patch (if/else body not indented under if).
broken_coins = re.compile(
    r"(?P<ind>\t+)if \(b3chainCirculatingSupply\)\n"
    r"(?P=ind)- var estimatedSupply = b3chainCirculatingSupply;\n"
    r"(?P<ind2>\t*)else\n"
    r"(?P=ind2)\t- var estimatedSupply = utils\.estimatedSupply\(getblockchaininfo\.blocks\);\n"
    r"\n"
    r"(?P=ind2)\tspan #\{parseInt\(estimatedSupply\)\.toLocaleString\(\)\}",
    re.MULTILINE,
)

def coins_repair(m):
    ind = m.group("ind")
    return coins_repl(m)  # same as correct structure using ind from if line

text2, n = broken_coins.subn(coins_repl, text, count=1)
if n == 1:
    text = text2
    print("index-network-summary.pug: coins patch repaired")
elif "b3chainCirculatingSupply" not in text:
    text2, n = coins_pat.subn(coins_repl, text, count=1)
    if n != 1:
        raise SystemExit("index-network-summary.pug: coins block not found")
    text = text2
    print("index-network-summary.pug: coins patched")
else:
    print("index-network-summary.pug: coins already patched")

path.write_text(text)
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
    old_v115 = """\t\t\t}).catch(function() {
\t\t\t\t// B3Chain-genesis-coinbase-fallback: b3chaind rejects getrawtransaction on genesis coinbase.
\t\t\t\tblock.coinbaseTx = null;
\t\t\t\tblock.totalFees = 0;
\t\t\t\treturn block;
\t\t\t})"""
    new_v115 = """\t\t\t}).catch(function() {
\t\t\t\t// B3Chain-genesis-block-coinbase: b3chaind may not serve genesis coinbase via getrawtransaction
\t\t\t\tif (block.height === 0 && coins[config.coin].genesisCoinbaseTransactionsByNetwork[global.activeBlockchain]) {
\t\t\t\t\tblock.coinbaseTx = JSON.parse(JSON.stringify(coins[config.coin].genesisCoinbaseTransactionsByNetwork[global.activeBlockchain]));
\t\t\t\t\tblock.coinbaseTx.time = block.time;
\t\t\t\t\tblock.coinbaseTx.blocktime = block.time;
\t\t\t\t\tblock.coinbaseTx.blockhash = block.hash;
\t\t\t\t\tblock.totalFees = 0;
\t\t\t\t\tblock.miner = utils.identifyMiner(block.coinbaseTx, block.height);
\t\t\t\t} else {
\t\t\t\t\tblock.coinbaseTx = null;
\t\t\t\t\tblock.totalFees = 0;
\t\t\t\t}
\t\t\t\treturn block;
\t\t\t})"""
    if "B3Chain-genesis-block-coinbase" not in text and old_v115 in text:
        text = text.replace(old_v115, new_v115, 1)
        print("rpcApi.js: upgraded v115 genesis coinbase fallback")
    elif old not in text and "B3Chain-genesis-coinbase-fallback" in text:
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
