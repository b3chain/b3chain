# B3Chain Testing Scripts

Public verification and testing tools for the B3Chain network.
These scripts allow anyone to independently verify that B3Chain works correctly.

## Prerequisites

- B3Chain Core compiled (`b3chaind` and `b3chain-cli` in `build/bin/`)
- Python 3.10+ with `blake3` package (`pip3 install blake3`)
- Linux or WSL2 environment

## Scripts

### regtest-simulation.sh

**Multi-node regtest network simulation.** Launches 3 interconnected B3Chain
nodes on localhost, mines a full difficulty retarget period (2016 blocks),
and verifies end-to-end correctness.

**Tests performed (19 checks):**

| # | Test | What it verifies |
|---|------|-----------------|
| 1-3 | Node startup | All 3 nodes start at height 0 |
| 4 | Address prefix | Regtest addresses use `b3rt1` prefix |
| 5 | Peer connectivity | Nodes discover and connect to each other |
| 6 | Mining (2016 blocks) | BLAKE3 PoW mining works via `generatetoaddress` |
| 7-8 | Block sync | Blocks propagate to all nodes |
| 9-10 | Tip consensus | All 3 nodes agree on the same chain tip |
| 11 | Miner balance | Miner receives block rewards (50 B3C/block) |
| 12 | Block subsidy | Block 1 coinbase pays exactly 50.00000000 B3C |
| 13-14 | Wallet send | Node 0 sends B3C to nodes 1 and 2 |
| 15 | Cross-node send | Node 1 sends B3C to node 2 (full P2P relay) |
| 16 | Chain work | Cumulative chain work is identical across nodes |
| 17 | Genesis hash | Genesis block matches expected hash |
| 18 | Mid-chain hash | Block hash at height 1008 is identical across nodes |
| 19 | UTXO set | UTXO set hash is identical across all nodes |

**Usage:**

```bash
# From the repository root
bash contrib/testing/regtest-simulation.sh

# Or with a custom binary path
BINDIR=/path/to/build/bin bash contrib/testing/regtest-simulation.sh
```

**Expected output:**

```
============================================================
 B3Chain Regtest Simulation (2016 blocks, 3 nodes)
============================================================
...
============================================================
 RESULTS: 19 passed, 0 failed
============================================================
 All tests passed!
```

**Runtime:** ~70 seconds on modern hardware.

### verify-blake3-pow.py

**Standalone BLAKE3 PoW verification.** Verifies the double BLAKE3-256
hash algorithm against known test vectors, and optionally connects to a
running node to verify live blocks.

**Usage:**

```bash
# Verify test vectors only (no node needed)
python3 contrib/testing/verify-blake3-pow.py

# Verify test vectors + live blocks from a running regtest node
python3 contrib/testing/verify-blake3-pow.py --rpc-port=18545
```

## Related Resources

| Resource | Location |
|----------|----------|
| Reference CPU miner | `contrib/miner/b3chain-cpuminer.py` |
| Genesis block miners | `contrib/genesis/` |
| PoW design document | `doc/b3chain-pow-design.md` |
| Mining documentation | `doc/mining.md` |
| Stratum / pool implementer guide | `doc/stratum.md` |
| C++ unit tests | `src/test/` (run via `ctest`) |
| Python functional tests | `test/functional/` (run via `test_runner.py`) |

## Verified Results

As of the initial release, the following test results have been achieved:

- **C++ unit tests:** 148 passed, 0 failed, 1 skipped
- **Python functional tests:** 258 passed, 0 failed, 19 skipped
- **Regtest simulation:** 19/19 checks passed (2016 blocks, 3 nodes)
- **BLAKE3 benchmark:** ~1.4 MH/s single-thread on modern CPU
