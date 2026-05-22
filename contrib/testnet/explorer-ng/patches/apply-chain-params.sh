#!/usr/bin/env bash
#
# Apply B3Chain chain-params codemod to a stripped explorer-ng tree.
#
# Run after tools/strip-upstream-brand.sh has finished. Idempotent.
#
# Touches the runtime configurable surface only (frontend display network
# names, backend network detection, default config). Unit / coin labels
# stay BTC ("B3C" derives from the same satoshi-style fixed-point math —
# we simply override the user-visible ticker token).
#
# Inputs:
#   $1   path to a stripped clone of the upstream tree
#
# Reference values:
#   testnet: P2P 18533, RPC 18534, bech32_hrp=tb3, magic=b3 c1 02 0e
#   mainnet: P2P  8533,             bech32_hrp=b3,  magic=b3 c0 01 0d
#
# This script does targeted rewrites with perl. Where upstream paths have
# diverged, it fails soft (the operator gets a clear "skipped: <file>"
# line that they can chase down per release).
set -euo pipefail
export LC_ALL=C

ROOT="${1:-$(pwd)}"
cd "$ROOT"

skip() { echo "    skip: $1 ($2)"; }
edit() { echo "    edit: $1"; }

# --- 1. Frontend ticker / coin label override ------------------------------
# Upstream has a `currency` config in frontend; we set default ticker to B3C.
for f in frontend/src/app/shared/services/state.service.ts \
         frontend/src/app/services/state.service.ts \
         frontend/src/app/components/amount/amount.component.ts ; do
    if [ -f "$f" ]; then
        perl -i -pe '
            s/(const|let)\s+DEFAULT_CURRENCY\s*=\s*[\x27"]BTC[\x27"]/$1 DEFAULT_CURRENCY = "B3C"/g;
            s/[\x27"]btc[\x27"]\s*:\s*\{[^}]*name:\s*[\x27"]Bitcoin[\x27"]/"b3c": { name: "B3Chain"/g;
        ' -- "$f"
        edit "$f"
    fi
done

# --- 2. Frontend network constant: bech32 HRP + sample addresses -----------
for f in frontend/src/app/components/address/address.component.ts \
         frontend/src/app/shared/regex-utils.ts \
         frontend/src/app/shared/common.utils.ts ; do
    [ -f "$f" ] || { skip "$f" "missing"; continue; }
    perl -i -pe '
        s/\bbc1[a-z0-9]{8,}\b/b31qexamplesample0000000000000000000000example/g;
        s/\btb1[a-z0-9]{8,}\b/tb31qexamplesample0000000000000000000000example/g;
        s/\bbcrt1[a-z0-9]{8,}\b/b3rt1qexamplesample0000000000000000000000example/g;
    ' -- "$f"
    edit "$f"
done

# --- 3. Backend network identification -------------------------------------
for f in backend/src/api/bitcoin/bitcoin.routes.ts \
         backend/src/utils/dns-seeds.ts \
         backend/src/api/bitcoin/bitcoin-api.ts ; do
    [ -f "$f" ] || { skip "$f" "missing"; continue; }
    # Update default network labels in backend so the logger and openapi spec
    # report B3Chain rather than Bitcoin in their docstrings.
    perl -i -pe '
        s/Bitcoin Mainnet/B3Chain Mainnet/g;
        s/Bitcoin Testnet/B3Chain Testnet/g;
        s/Bitcoin Signet/B3Chain Signet/g;
    ' -- "$f"
    edit "$f"
done

# --- 4. Sample / default backend config: ports + RPC user/pass placeholders
for f in backend/explorer-ng-config.sample.json \
         explorer-ng-config.sample.json \
         backend/mempool-config.sample.json \
         mempool-config.sample.json ; do
    if [ -f "$f" ]; then
        perl -i -pe '
            s/"PORT":\s*8332/"PORT": 18534/g;
            s/"PORT":\s*18332/"PORT": 18534/g;
            s/"USERNAME":\s*"mempool"/"USERNAME": "b3chain"/g;
        ' -- "$f"
        edit "$f"
    fi
done

# --- 5. Genesis hash override (display-only) -------------------------------
# Where upstream hard-codes 000000000019d6689c... we replace with B3Chain
# testnet genesis ebc117cd...c6. Mainnet stays empty until P1 mainnet rebrand.
B3C_TESTNET_GENESIS="ebc117cd7d8f1c6e2b6a5b6d8f0c1d2a3b4c5d6e7f8091a2b3c4d5e6f708192c6"
B3C_MAINNET_GENESIS="b6cdeba0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0e6"

# These are placeholder constants; the backend reads the actual genesis hash
# from b3chaind via getblockhash 0 at startup, so the display value shown
# while pre-RPC bootstrap matches.
for f in frontend/src/app/shared/services/state.service.ts \
         backend/src/api/blocks.ts ; do
    [ -f "$f" ] || { skip "$f" "missing"; continue; }
    perl -i -pe "
        s/000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f/${B3C_MAINNET_GENESIS}/g;
        s/000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943/${B3C_TESTNET_GENESIS}/g;
    " -- "$f"
    edit "$f"
done

mkdir -p .b3chain
date -u +"%Y-%m-%dT%H:%M:%SZ" > .b3chain/apply-chain-params.last-run.txt
echo "==> chain-params codemod finished at $(cat .b3chain/apply-chain-params.last-run.txt)"
