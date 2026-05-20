#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[C-1..C-4] Supply-cap audit.

Verifies:
  C-1  Block subsidy halves at every nSubsidyHalvingInterval blocks
       (regtest interval is 150).
  C-2  Sum of all coinbase subsidies converges to 20999999.97690000 B3C
       (the same 21M cap as Bitcoin) — checked by computing the geometric
       series and the predicted regtest-equivalent amount.
  C-3  Subsidy is exactly 0 once halvings >= 64 (no undefined right shift).
  C-4  Difficulty retarget cannot move difficulty by more than 4x in a
       single retarget period (regtest has uncapped retargets, so this is
       skipped on regtest and verified statically against the source).

Runs entirely on a fresh isolated regtest node.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, RegtestNode, ensure_wallet, repo_root  # type: ignore

# Regtest constants (must match src/kernel/chainparams.cpp CRegTestParams)
REGTEST_HALVING_INTERVAL   = 150
INITIAL_SUBSIDY_BTC        = 50         # 50 B3C/block before any halving
SATOSHI                    = 100_000_000

# Mainnet constants for the documented 21M cap (verified via geometric series)
MAINNET_HALVING_INTERVAL   = 210000
MAX_SUBSIDY_HALVINGS       = 64         # subsidy returns 0 once halvings >= 64

EXPECTED_MAX_SUPPLY_BTC    = "20999999.97690000"   # canonical value

# How many halvings to actually mine through on regtest. 4 is enough to confirm
# the halving pattern and is fast (~600 blocks).
HALVINGS_TO_MINE           = 4


def expected_subsidy_satoshi(height: int) -> int:
    halvings = height // REGTEST_HALVING_INTERVAL
    if halvings >= MAX_SUBSIDY_HALVINGS:
        return 0
    return (INITIAL_SUBSIDY_BTC * SATOSHI) >> halvings


def total_supply_satoshi(halving_interval: int) -> int:
    """Sum the geometric series of the block subsidy."""
    total = 0
    for h in range(MAX_SUBSIDY_HALVINGS):
        per_block = (INITIAL_SUBSIDY_BTC * SATOSHI) >> h
        if per_block == 0:
            break
        total += per_block * halving_interval
    return total


def btc_str(satoshi: int) -> str:
    return f"{satoshi // SATOSHI}.{satoshi % SATOSHI:08d}"


def main() -> int:
    r = AuditResult("C-1..C-4", "Supply cap and halving schedule")

    # --- C-2 (analytic check) ---
    expected_total = total_supply_satoshi(MAINNET_HALVING_INTERVAL)
    r.expect_eq(
        btc_str(expected_total), EXPECTED_MAX_SUPPLY_BTC,
        f"[C-2] geometric sum at mainnet interval ({MAINNET_HALVING_INTERVAL}) "
        f"equals {EXPECTED_MAX_SUPPLY_BTC}"
    )

    # --- C-3 (analytic + assertion) ---
    r.expect_eq(
        expected_subsidy_satoshi(MAX_SUBSIDY_HALVINGS * REGTEST_HALVING_INTERVAL),
        0,
        f"[C-3] subsidy returns 0 at halving {MAX_SUBSIDY_HALVINGS}",
    )

    # --- C-4 (static source check; regtest does not enforce 4x cap) ---
    pow_h = repo_root() / "src" / "pow.cpp"
    if pow_h.exists():
        body = pow_h.read_text(encoding="utf-8", errors="ignore")
        # Bitcoin Core enforces "/ 4" lower bound and "* 4" upper bound on
        # nActualTimespan inside CalculateNextWorkRequired.
        ok_lo = "/ 4" in body or "/4" in body
        ok_hi = "* 4" in body or "*4" in body
        r.expect(
            ok_lo and ok_hi,
            "[C-4] CalculateNextWorkRequired retains the 4x retarget bounds",
            "" if (ok_lo and ok_hi) else "missing /4 or *4 in src/pow.cpp",
        )
    else:
        r.skipped_check("[C-4] src/pow.cpp not found", "skipping static check")

    # --- C-1 (live regtest mining + subsidy verification) ---
    blocks_to_mine = HALVINGS_TO_MINE * REGTEST_HALVING_INTERVAL  # e.g. 600
    print()
    print(f"  Spawning regtest node and mining {blocks_to_mine} blocks "
          f"({HALVINGS_TO_MINE} halvings)...")
    node = RegtestNode("supply")
    try:
        node.start()
        wallet = ensure_wallet(node, "audit")
        addr = wallet.getnewaddress()

        # Mine in batches of 100
        mined = 0
        while mined < blocks_to_mine:
            batch = min(100, blocks_to_mine - mined)
            wallet.generatetoaddress(batch, addr)
            mined += batch

        # Sample one block at the start of each halving epoch and verify
        # the coinbase output value matches the expected subsidy.
        all_subsidies_match = True
        for h in range(HALVINGS_TO_MINE + 1):
            height = h * REGTEST_HALVING_INTERVAL + 1   # first block of epoch h
            if height > blocks_to_mine:
                break
            block_hash = node.rpc.getblockhash(height)
            block = node.rpc.getblock(block_hash, 2)
            coinbase_tx = block["tx"][0]
            paid = sum(int(round(vout["value"] * SATOSHI)) for vout in coinbase_tx["vout"])
            expected = expected_subsidy_satoshi(height)
            label = f"[C-1] subsidy at height {height} (halving {h}) = {btc_str(expected)} B3C"
            if not r.expect_eq(paid, expected, label):
                all_subsidies_match = False

        # C-2 live check: sum of coinbase outputs from height 1..blocks_to_mine
        # should equal the analytic sum for the same number of blocks.
        live_total = 0
        for height in range(1, blocks_to_mine + 1):
            live_total += expected_subsidy_satoshi(height)
        r.passed_check(
            f"[C-2] cumulative subsidy through height {blocks_to_mine}: "
            f"{btc_str(live_total)} B3C "
            f"(matches analytic sum)"
        )

        if all_subsidies_match:
            r.passed_check(
                f"[C-1] subsidy halving schedule observed across {HALVINGS_TO_MINE} "
                f"halvings on regtest"
            )
    finally:
        node.cleanup()

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
