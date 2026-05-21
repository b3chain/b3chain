#!/usr/bin/env bash
# Update btc-rpc-explorer for v1.1.5 testnet genesis + genesis coinbase fallback.
# Idempotent. Run as root on seed1 after a testnet genesis change.
export LC_ALL=C
set -euo pipefail

GEN="${B3_TESTNET_GENESIS_HASH:-ebc117cd39760da3c8a3687484858e8ea2cfbc88990fb587957b4ba956a661c6}"
TX="${B3_TESTNET_GENESIS_TXID:-6fefcc8f9ca9674e3948b2a74c381f8abb9f0e38349fad3d62794ed3895269dc}"

EXP_DIR=/var/lib/b3chain-explorer
COIN="$EXP_DIR/node_modules/btc-rpc-explorer/app/coins/btc.js"
RPC="$EXP_DIR/node_modules/btc-rpc-explorer/app/api/rpcApi.js"
BASEROUTER="$EXP_DIR/node_modules/btc-rpc-explorer/routes/baseRouter.js"

[ -f "$COIN" ] || { echo "missing $COIN"; exit 1; }

# genesisBlockHashesByNetwork["test"] — use python (sed range is unreliable here).
python3 <<PY
from pathlib import Path
import re
coin = Path("$COIN")
gen = "$GEN"
text = coin.read_text()
pattern = r'(genesisBlockHashesByNetwork:\{[^}]*"test":\s*")([0-9a-f]{64})(")'
new_text, n = re.subn(pattern, r"\1" + gen + r"\3", text, count=1, flags=re.S)
if n != 1:
    raise SystemExit(f"genesisBlockHashesByNetwork test pattern matched {n} times")
coin.write_text(new_text)
print(f"btc.js: test genesis hash -> {gen}")
PY

# genesisCoinbaseTransactionIdsByNetwork["test"] only.
sed -i -E '/genesisCoinbaseTransactionIdsByNetwork/,/genesisCoinbaseTransactionsByNetwork/{
    s|("test"[[:space:]]+)"4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"|\1"'"$TX"'"|
}' "$COIN"

# getBlockByHash: genesis coinbase is not getrawtransaction-able on b3chaind.
if [ -f "$RPC" ]; then
    python3 <<'PY'
from pathlib import Path
path = Path("/var/lib/b3chain-explorer/node_modules/btc-rpc-explorer/app/api/rpcApi.js")
text = path.read_text()

# Repair a prior broken patch that inserted an extra "})" before ".catch".
broken = "\t\t\t})\n\t\t\t}).catch(function() {\n\t\t\t\t// B3Chain-genesis-coinbase-fallback"
fixed = "\t\t\t}).catch(function() {\n\t\t\t\t// B3Chain-genesis-coinbase-fallback"
if broken in text:
    text = text.replace(broken, fixed, 1)
    path.write_text(text)
    print("rpcApi.js: repaired broken genesis coinbase fallback syntax")
elif "B3Chain-genesis-coinbase-fallback" not in text:
    needle = """\t\t\treturn getRawTransaction(block.tx[0], blockHash).then(function(tx) {
\t\t\t\tblock.coinbaseTx = tx;
\t\t\t\tblock.totalFees = utils.getBlockTotalFeesFromCoinbaseTxAndBlockHeight(tx, block.height);
\t\t\t\tblock.miner = utils.identifyMiner(tx, block.height);
\t\t\t\treturn block;
\t\t\t})"""
    repl = """\t\t\treturn getRawTransaction(block.tx[0], blockHash).then(function(tx) {
\t\t\t\tblock.coinbaseTx = tx;
\t\t\t\tblock.totalFees = utils.getBlockTotalFeesFromCoinbaseTxAndBlockHeight(tx, block.height);
\t\t\t\tblock.miner = utils.identifyMiner(tx, block.height);
\t\t\t\treturn block;
\t\t\t}).catch(function() {
\t\t\t\t// B3Chain-genesis-coinbase-fallback: b3chaind rejects getrawtransaction on genesis coinbase.
\t\t\t\tblock.coinbaseTx = null;
\t\t\t\tblock.totalFees = 0;
\t\t\t\treturn block;
\t\t\t})"""
    if needle not in text:
        raise SystemExit("rpcApi.js pattern not found; btc-rpc-explorer version changed?")
    path.write_text(text.replace(needle, repl, 1))
    print("rpcApi.js: genesis coinbase fallback patched")
else:
    print("rpcApi.js: genesis coinbase fallback already present")
PY
fi

# baseRouter: young chains have fewer blocks than recentBlocksCount (default 10).
if [ -f "$BASEROUTER" ] && ! grep -q 'B3Chain-negative-height-guard' "$BASEROUTER"; then
    sed -i 's|blockHeights.push(getblockchaininfo.blocks - i);|let _h = getblockchaininfo.blocks - i; if (_h >= 0) { blockHeights.push(_h); } // B3Chain-negative-height-guard|' "$BASEROUTER"
fi
if [ -f "$BASEROUTER" ] && ! grep -q 'B3Chain-null-blockstats-guard' "$BASEROUTER"; then
    sed -i 's|let blockstats = rawblockstats\[i\];|let blockstats = rawblockstats[i]; if (!blockstats) { continue; } // B3Chain-null-blockstats-guard|' "$BASEROUTER"
fi
if [ -f "$BASEROUTER" ] && ! grep -q 'B3Chain-latestBlocks-guard' "$BASEROUTER"; then
    sed -i 's|res.locals.blocksUntilDifficultyAdjustment = ((res.locals.difficultyPeriod + 1) \* coinConfig.difficultyAdjustmentBlockCount) - latestBlocks\[0\].height;|if (latestBlocks \&\& latestBlocks[0]) { res.locals.blocksUntilDifficultyAdjustment = ((res.locals.difficultyPeriod + 1) * coinConfig.difficultyAdjustmentBlockCount) - latestBlocks[0].height; } // B3Chain-latestBlocks-guard|' "$BASEROUTER"
fi

# rpcApi: pruned-block fallback must tolerate null getblockheader results.
if [ -f "$RPC" ] && ! grep -q 'B3Chain-null-blockheader-guard' "$RPC"; then
    sed -i 's|.then(function(block) { block.tx = \[\]; return block });|.then(function(block) { if (block) { block.tx = []; } return block; }); // B3Chain-null-blockheader-guard|' "$RPC"
fi

echo "==> genesis hash + coinbase txid in btc.js:"
grep -A1 'genesisBlockHashesByNetwork' "$COIN" | head -5
grep -A1 'genesisCoinbaseTransactionIdsByNetwork' "$COIN" | head -5

systemctl restart b3chain-explorer.service
sleep 5
if ! systemctl is-active --quiet b3chain-explorer.service; then
    echo "ERROR: b3chain-explorer failed to start" >&2
    journalctl -u b3chain-explorer -n 20 --no-pager >&2
    exit 1
fi
if curl -sf http://127.0.0.1:3002/ | grep -q 'Error building page'; then
    echo "WARN: homepage still shows Error building page" >&2
    journalctl -u b3chain-explorer -n 10 --no-pager >&2
    exit 1
fi
echo "OK: explorer homepage renders without Error building page"
