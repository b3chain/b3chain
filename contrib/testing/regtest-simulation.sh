#!/bin/bash
# =============================================================================
# B3Chain Multi-Node Regtest Simulation
# =============================================================================
# Tests: block propagation, wallet send/receive, mining 2000+ blocks,
#        difficulty adjustment, chain consistency across 3 nodes.
#
# Usage: bash contrib/testing/regtest-simulation.sh
# =============================================================================

# Auto-detect the build directory: prefer build/bin, fall back to build/src
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ -n "$BINDIR" ]; then
    : # Use caller-supplied BINDIR
elif [ -x "$REPO_ROOT/build/bin/b3chaind" ]; then
    BINDIR="$REPO_ROOT/build/bin"
elif [ -x "$REPO_ROOT/build/src/b3chaind" ]; then
    BINDIR="$REPO_ROOT/build/src"
else
    echo "ERROR: Cannot find b3chaind.  Set BINDIR or build first."
    exit 1
fi

DAEMON="$BINDIR/b3chaind"
CLI="$BINDIR/b3chain-cli"
TESTDIR="/tmp/b3chain_regtest_sim"
BLOCKS_TO_MINE=2016  # Full difficulty retarget period

# Node configurations (port, rpcport) - use high ports to avoid conflicts
NODE0_P2P=29100; NODE0_RPC=29101
NODE1_P2P=29102; NODE1_RPC=29103
NODE2_P2P=29104; NODE2_RPC=29105

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass_count=0
fail_count=0

pass() {
    echo -e "  ${GREEN}PASS${NC}: $1"
    ((pass_count++))
}

fail() {
    echo -e "  ${RED}FAIL${NC}: $1"
    ((fail_count++))
}

check() {
    # check "description" "actual" "expected"
    if [ "$2" = "$3" ]; then
        pass "$1 ($2)"
    else
        fail "$1 (got '$2', expected '$3')"
    fi
}

cli0() { $CLI -regtest -datadir=$TESTDIR/node0 -rpcport=$NODE0_RPC "$@"; }
cli1() { $CLI -regtest -datadir=$TESTDIR/node1 -rpcport=$NODE1_RPC "$@"; }
cli2() { $CLI -regtest -datadir=$TESTDIR/node2 -rpcport=$NODE2_RPC "$@"; }

cleanup() {
    echo ""
    echo "Stopping nodes..."
    cli0 stop 2>/dev/null || true
    cli1 stop 2>/dev/null || true
    cli2 stop 2>/dev/null || true
    sleep 2
    pkill -f "b3chaind.*regtest_sim" 2>/dev/null || true
}

trap cleanup EXIT

# =============================================================================
echo "============================================================"
echo " B3Chain Regtest Simulation ($BLOCKS_TO_MINE blocks, 3 nodes)"
echo "============================================================"
echo ""

# --- Setup ---
echo "[1/8] Setting up test environment..."
rm -rf $TESTDIR
mkdir -p $TESTDIR/node0 $TESTDIR/node1 $TESTDIR/node2

# Start 3 nodes
for i in 0 1 2; do
    eval "P2P=\$NODE${i}_P2P"
    eval "RPC=\$NODE${i}_RPC"
    PEERS=""
    for j in 0 1 2; do
        if [ $j -ne $i ]; then
            eval "PEER_P2P=\$NODE${j}_P2P"
            PEERS="$PEERS -addnode=127.0.0.1:$PEER_P2P"
        fi
    done
    $DAEMON -regtest -datadir=$TESTDIR/node$i -daemon \
        -port=$P2P -rpcport=$RPC \
        -rpcbind=127.0.0.1:$RPC -rpcallowip=127.0.0.0/8 \
        -bind=127.0.0.1:$P2P \
        -listenonion=0 -discover=0 -dnsseed=0 \
        -fallbackfee=0.0001 -maxtxfee=1 \
        $PEERS \
        2>/dev/null
done

echo "  Waiting for nodes to start..."
sleep 5

# Verify all nodes are running
for i in 0 1 2; do
    eval "RPC_PORT=\$NODE${i}_RPC"
    HEIGHT=$($CLI -regtest -datadir=$TESTDIR/node$i -rpcport=$RPC_PORT getblockchaininfo 2>&1 | grep '"blocks"' | grep -o '[0-9]*')
    if [ "$HEIGHT" = "0" ]; then
        pass "Node $i started at height 0"
    else
        fail "Node $i failed to start (height=$HEIGHT)"
        exit 1
    fi
done

# --- Create wallets ---
echo ""
echo "[2/8] Creating wallets..."
cli0 createwallet "miner" >/dev/null 2>&1
cli1 createwallet "wallet1" >/dev/null 2>&1
cli2 createwallet "wallet2" >/dev/null 2>&1

ADDR0=$(cli0 getnewaddress)
ADDR1=$(cli1 getnewaddress)
ADDR2=$(cli2 getnewaddress)

echo "  Node 0 (miner):  $ADDR0"
echo "  Node 1 (wallet): $ADDR1"
echo "  Node 2 (wallet): $ADDR2"

# Verify b3rt prefix
if [[ "$ADDR0" == b3rt1* ]]; then
    pass "Address uses b3rt prefix"
else
    fail "Address prefix wrong: $ADDR0"
fi

# --- Peer connectivity ---
echo ""
echo "[3/8] Testing peer connectivity..."
sleep 3  # Let peers connect

PEERS0=$(cli0 getpeerinfo 2>/dev/null | grep -c '"addr"' || echo 0)
if [ "$PEERS0" -ge 1 ]; then
    pass "Node 0 has $PEERS0 peer(s)"
else
    fail "Node 0 has no peers"
fi

# --- Mine initial blocks ---
echo ""
echo "[4/8] Mining $BLOCKS_TO_MINE blocks (full retarget period)..."

START_TIME=$(date +%s)

# Mine in batches of 100
MINED=0
while [ $MINED -lt $BLOCKS_TO_MINE ]; do
    BATCH=$((BLOCKS_TO_MINE - MINED))
    if [ $BATCH -gt 100 ]; then BATCH=100; fi
    cli0 generatetoaddress $BATCH "$ADDR0" >/dev/null 2>&1
    MINED=$((MINED + BATCH))
    if [ $((MINED % 500)) -eq 0 ] || [ $MINED -eq $BLOCKS_TO_MINE ]; then
        echo "  Mined $MINED / $BLOCKS_TO_MINE blocks..."
    fi
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo "  Mining took ${DURATION}s"

# Verify height
HEIGHT0=$(cli0 getblockchaininfo | grep '"blocks"' | grep -o '[0-9]*')
check "Node 0 at height $BLOCKS_TO_MINE" "$HEIGHT0" "$BLOCKS_TO_MINE"

# Wait for sync
echo "  Waiting for block propagation..."
sleep 5

HEIGHT1=$(cli1 getblockchaininfo | grep '"blocks"' | grep -o '[0-9]*')
HEIGHT2=$(cli2 getblockchaininfo | grep '"blocks"' | grep -o '[0-9]*')
check "Node 1 synced to $BLOCKS_TO_MINE" "$HEIGHT1" "$BLOCKS_TO_MINE"
check "Node 2 synced to $BLOCKS_TO_MINE" "$HEIGHT2" "$BLOCKS_TO_MINE"

# Verify same tip
HASH0=$(cli0 getbestblockhash)
HASH1=$(cli1 getbestblockhash)
HASH2=$(cli2 getbestblockhash)
check "All nodes agree on tip" "$HASH0" "$HASH1"
check "All nodes agree on tip (node2)" "$HASH0" "$HASH2"

# --- Check mining rewards ---
echo ""
echo "[5/8] Verifying mining rewards and subsidy..."

# After 100 maturity, miner should have balance
# First 2016 blocks at 50 B3C each, minus 100 immature
BALANCE0=$(cli0 getbalance)
echo "  Miner balance: $BALANCE0 B3C"
if [ "$(echo "$BALANCE0 > 0" | bc -l 2>/dev/null || python3 -c "print(1 if float('$BALANCE0') > 0 else 0)")" = "1" ]; then
    pass "Miner has positive balance ($BALANCE0 B3C)"
else
    fail "Miner balance is 0"
fi

# Check block subsidy at height 1
BLOCK1_HASH=$(cli0 getblockhash 1)
BLOCK1=$(cli0 getblock "$BLOCK1_HASH" 2)
COINBASE_VALUE=$(echo "$BLOCK1" | python3 -c "import json,sys; b=json.load(sys.stdin); print('{:.8f}'.format(b['tx'][0]['vout'][0]['value']))")
check "Block 1 subsidy" "$COINBASE_VALUE" "50.00000000"

# --- Wallet send/receive ---
echo ""
echo "[6/8] Testing wallet send/receive..."

# Send from node 0 to node 1
TXID1=$(cli0 sendtoaddress "$ADDR1" 10.5)
echo "  Sent 10.5 B3C to node 1 (txid: ${TXID1:0:16}...)"

# Send from node 0 to node 2
TXID2=$(cli0 sendtoaddress "$ADDR2" 5.25)
echo "  Sent 5.25 B3C to node 2 (txid: ${TXID2:0:16}...)"

# Mine a block to confirm
cli0 generatetoaddress 1 "$ADDR0" >/dev/null 2>&1
sleep 3

# Check balances
BAL1=$(cli1 getbalance)
BAL2=$(cli2 getbalance)
echo "  Node 1 balance: $BAL1"
echo "  Node 2 balance: $BAL2"

if [ "$(python3 -c "print(1 if float('$BAL1') >= 10.5 else 0)")" = "1" ]; then
    pass "Node 1 received 10.5 B3C"
else
    fail "Node 1 balance wrong ($BAL1)"
fi

if [ "$(python3 -c "print(1 if float('$BAL2') >= 5.25 else 0)")" = "1" ]; then
    pass "Node 2 received 5.25 B3C"
else
    fail "Node 2 balance wrong ($BAL2)"
fi

# Cross-send: node 1 sends to node 2
TXID3=$(cli1 sendtoaddress "$ADDR2" 2.0)
echo "  Node 1 sent 2.0 B3C to node 2 (txid: ${TXID3:0:16}...)"

# Wait for tx to propagate to miner node's mempool
for attempt in $(seq 1 10); do
    MPOOL=$(cli0 getrawmempool 2>/dev/null)
    if echo "$MPOOL" | grep -q "$TXID3"; then
        echo "  Tx in miner mempool after ${attempt}s"
        break
    fi
    sleep 1
done

cli0 generatetoaddress 1 "$ADDR0" >/dev/null 2>&1
sleep 5  # Wait for block propagation to node 2

BAL2_AFTER=$(cli2 getbalance)
echo "  Node 2 balance after: $BAL2_AFTER"
if [ "$(python3 -c "print(1 if float('$BAL2_AFTER') >= 7.25 else 0)")" = "1" ]; then
    pass "Cross-node send succeeded"
else
    fail "Cross-node send failed ($BAL2_AFTER)"
fi

# --- Chain consistency ---
echo ""
echo "[7/8] Verifying chain consistency..."

FINAL_HEIGHT=$(cli0 getblockchaininfo | grep '"blocks"' | grep -o '[0-9]*')
echo "  Final height: $FINAL_HEIGHT"

# Check chain work
CHAINWORK0=$(cli0 getblockchaininfo | grep '"chainwork"' | grep -o '"[0-9a-f]*"' | tail -1 | tr -d '"')
CHAINWORK1=$(cli1 getblockchaininfo | grep '"chainwork"' | grep -o '"[0-9a-f]*"' | tail -1 | tr -d '"')
check "Chain work matches across nodes" "$CHAINWORK0" "$CHAINWORK1"

# Check genesis block
GENESIS=$(cli0 getblockhash 0)
check "Genesis hash correct" "$GENESIS" "8c19b11553c449cfe6f8b00c830b8e34249529fd9521cb4825541df9b0372de4"

# Verify a random block in the middle
MID=$((BLOCKS_TO_MINE / 2))
MIDHASH0=$(cli0 getblockhash $MID)
MIDHASH1=$(cli1 getblockhash $MID)
check "Block $MID hash consistent" "$MIDHASH0" "$MIDHASH1"

# Check difficulty (should be minimal on regtest)
DIFF=$(cli0 getblockchaininfo | grep '"difficulty"' | head -1 | grep -o '[0-9.e+-]*')
echo "  Difficulty: $DIFF"

# --- UTXO set integrity ---
echo ""
echo "[8/8] Verifying UTXO set..."

UTXO_INFO0=$(cli0 gettxoutsetinfo 2>/dev/null)
UTXO_HASH0=$(echo "$UTXO_INFO0" | grep '"hash_serialized_3"' | grep -o '"[0-9a-f]*"' | tr -d '"')
UTXO_TXOUTS0=$(echo "$UTXO_INFO0" | grep '"txouts"' | grep -o '[0-9]*')

UTXO_INFO1=$(cli1 gettxoutsetinfo 2>/dev/null)
UTXO_HASH1=$(echo "$UTXO_INFO1" | grep '"hash_serialized_3"' | grep -o '"[0-9a-f]*"' | tr -d '"')

echo "  UTXO set: $UTXO_TXOUTS0 outputs"
check "UTXO hash matches across nodes" "$UTXO_HASH0" "$UTXO_HASH1"

# =============================================================================
echo ""
echo "============================================================"
echo " RESULTS: $pass_count passed, $fail_count failed"
echo "============================================================"

if [ $fail_count -eq 0 ]; then
    echo -e " ${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e " ${RED}$fail_count test(s) failed${NC}"
    exit 1
fi
