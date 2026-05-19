# B3Chain Phase 11 Security Audit Scripts

This directory contains the automated audit scripts that back the master
checklist in [`doc/SECURITY-AUDIT.md`](../../../doc/SECURITY-AUDIT.md).

Every script is self-contained and prints a final `PASS` or `FAIL` line and
exits with the corresponding exit code (0 = pass).

## Layout

| File | Purpose |
|------|---------|
| `lib/audit_common.py`   | Shared utilities: RPC client, node lifecycle, result formatter |
| `lib/audit_common.sh`   | Bash equivalents of the same helpers (color, pass/fail counters) |
| `audit-supply-cap.py`   | C-1..C-4 — block subsidy halving and 21M cap |
| `audit-b3pow-isolation.py`| H-1 — GetPoWHash (B3PoW-Scratch v1.1) vs GetHash isolation |
| `audit-b3pow-budget.py`   | H-1.1 — B3PoW verifier wall-clock budget enforcement |
| `audit-b3pow-cache.py`    | H-1.2 — `b3pow::Cache` LRU scratchpad cache wiring |
| `audit-b3pow-headers-cap.py` | H-1.3 — `MAX_B3POW_VERIFY_PER_BATCH` HEADERS-cap enforcement |
| `audit-network-isolation.py` | N-1 — Bitcoin magic / DNS seed rejection |
| `audit-address-rejection.py` | W-1 — Bitcoin address format rejection |
| `audit-simd-blake3.py`  | B-1 — SIMD vs portable C BLAKE3 *primitive* differential test (BLAKE3 is the inner round function of B3PoW-Scratch) |
| `audit-rebranding.sh`   | B-2 — forbidden-pattern grep + regression rerun |
| `audit-hd-coin-type.py` | W-2 — BIP44 coin_type 9333 derivation check |
| `audit-51-attack-sim.py`| A-1 — live double-spend reorg demo |
| `audit-b3pow-miner-e2e.py`| M-1d — Internal miner end-to-end PoW check |
| `audit-pow-isolation.py` <br/> `audit-internal-miner-e2e.py` <br/> `../verify-blake3-pow.py` | DEPRECATED shims that forward to the new B3PoW-named entry points (will be removed in the next release) |
| `run-all.sh`            | Run every audit and print a summary table |

## Prerequisites

- B3Chain Core built (`b3chaind`, `b3chain-cli` in `build/bin/` or `build/src/`)
- Python 3.10+
- `pip3 install blake3` (for SIMD differential testing)
- Linux or WSL2

## Quick start

```bash
# Run everything
bash contrib/testing/audit/run-all.sh

# Run one audit
python3 contrib/testing/audit/audit-supply-cap.py
```

## Adding a new audit

1. Drop the script in this directory.
2. Have it import `lib/audit_common.py` (or source `lib/audit_common.sh`).
3. Print a final `AUDIT RESULT: PASS` or `AUDIT RESULT: FAIL` line.
4. Add it to `run-all.sh` and to `doc/SECURITY-AUDIT.md`.
