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
| 6 | Mining (2016 blocks) | B3PoW-Scratch v1.1 mining works via `generatetoaddress` |
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

### verify-b3pow.py

**Standalone B3PoW-Scratch v1.1 verification.** Recomputes every entry
in [`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json)
through the Python reference at
[`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../miner/b3miner-rtl/ref/b3pow_ref.py)
and optionally connects to a running node to verify live blocks.

The reference implementation is the single source of truth and is
byte-for-byte equivalent to the C++ port at
[`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp);
the consensus-vectors JSON file is what pins them together.

**Usage:**

```bash
# Verify the consensus vectors (no node needed)
python3 contrib/testing/verify-b3pow.py

# Verify vectors + live blocks from a running regtest node
python3 contrib/testing/verify-b3pow.py --rpc-port=18545
```

`verify-blake3-pow.py` still exists as a thin deprecation shim that
forwards to `verify-b3pow.py`. It will be removed in the next release.

## Related Resources

| Resource | Location |
|----------|----------|
| B3PoW-Scratch v1.1 normative spec | `contrib/miner/b3miner-rtl/SPEC.md` |
| Python reference implementation | `contrib/miner/b3miner-rtl/ref/b3pow_ref.py` |
| Consensus-grade vectors (JSON) | `src/test/data/b3pow_consensus_vectors.json` |
| C++ port of the PoW | `src/crypto/b3pow_scratch.cpp` / `b3pow_cache.cpp` |
| Reference CPU miner | `contrib/miner/b3chain-cpuminer.py` |
| Genesis block miners | `contrib/genesis/` |
| Mining documentation | `doc/mining.md` |
| Stratum / pool implementer guide | `doc/stratum.md` |
| C++ unit tests | `src/test/` (run via `ctest`) |
| Python functional tests | `test/functional/` (run via `test_runner.py`) |

## Verified Results

The most recent published end-to-end run is mirrored at
[`b3chain.org/testing/test-results.html`](https://b3chain.org/testing/test-results.html);
machine-readable per-script results live under `contrib/testing/results/`.
