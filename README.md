B3Chain Core
============

https://b3chain.org

B3Chain is a conservative Proof-of-Work Layer 1 blockchain built in the
spirit of Bitcoin Core. It replaces Bitcoin's SHA-256d mining algorithm
with **B3PoW-Scratch v1.1**, a memory-hard BLAKE3-based PoW designed to
be **FPGA-economical and GPU-hostile**, while keeping everything else
as close to Bitcoin as possible.

What is B3Chain?
----------------

B3Chain Core connects to the B3Chain peer-to-peer network to download
and fully validate blocks and transactions. It includes a wallet and
graphical user interface, which can be optionally built.

### Key differences from Bitcoin Core

| Feature | Bitcoin | B3Chain |
|---------|---------|---------|
| PoW algorithm | Double SHA-256 | **B3PoW-Scratch v1.1** (1 MB scratchpad, 8 lanes, 2 048 iterations, BLAKE3 primitive) |
| Block identity hash | Double SHA-256 | Double SHA-256 (unchanged) |
| Bech32 HRP | `bc` | `b3` |
| Default P2P port | 8333 | 8533 |
| Default RPC port | 8332 | 8534 |
| Data directory | `.bitcoin` | `.b3chain` |
| Config file | `bitcoin.conf` | `b3chain.conf` |
| Binary names | `bitcoind`, `bitcoin-cli` | `b3chaind`, `b3chain-cli` |

### What stays the same

- UTXO model
- 21 million supply cap
- 10-minute block target
- 210,000 block halving interval (50 → 25 → 12.5 → ...)
- 2016-block difficulty retarget
- Segwit, Taproot, and all Bitcoin script opcodes
- Transaction format, merkle trees, P2P protocol structure

### What B3PoW-Scratch is — and is not

- **Is**: a memory-hard, sequential, data-dependent PoW with a 1 MB
  on-chip working set, designed so the most economical implementation
  is an FPGA with on-chip BRAM (not a SHA-256d ASIC, not a consumer
  GPU). 16 384 sequential read–modify–write rounds per hash. Reference
  implementation, RTL, formal spec, and consensus vectors all ship
  in-tree.
- **Is not**: "ASIC-proof", "perfectly decentralized", or
  permanently resistant to specialized hardware. No PoW is. The design
  goal is to shift the economic frontier toward small, low-power FPGA
  cards (B3Miner-1, ~10 W) and away from the SHA-256d ASIC monoculture.
  Custom B3PoW ASICs are possible; the algorithm is calibrated so an
  ASIC's economic advantage over an FPGA is small enough to leave room
  for hobbyists and small operators.

See the formal spec at
[`contrib/miner/b3miner-rtl/SPEC.md`](contrib/miner/b3miner-rtl/SPEC.md)
and the FPGA / ASIC economic analysis (forthcoming) at
[`doc/analysis/`](doc/analysis/).

Further information is available in the [doc folder](/doc), including:
- [B3PoW-Scratch whitepaper](doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md)
- [Repository map](doc/REPO-MAP.md)
- [PoW design document](doc/b3chain-pow-design.md)
- [Mining documentation](doc/mining.md)
- [Stratum / pool implementer guide](doc/stratum.md)
- [Contributing guide](CONTRIBUTING.md) and [code of conduct](CODE_OF_CONDUCT.md)
- [Project changelog](doc/CHANGELOG.md)

Building
--------

Build instructions are the same as Bitcoin Core. See `doc/build-*.md` for
your platform:

```bash
mkdir build && cd build
cmake ..
cmake --build . -j$(nproc)
```

Binaries are output as `b3chaind`, `b3chain-cli`, `b3chain-tx`, `b3chain-wallet`,
and `b3chain-qt`.

Testing
-------

### Unit tests

```bash
cd build
ctest --output-on-failure
```

**Current results:** 148 passed, 0 failed, 1 skipped

### Functional tests

```bash
cd build
python3 ../test/functional/test_runner.py
```

**Current results:** 258 passed, 0 failed, 19 skipped

### Regtest simulation

A 3-node regtest network simulation is provided:

```bash
bash contrib/testing/regtest-simulation.sh
```

Mines 2016 blocks, tests wallet send/receive, verifies chain consistency
across all nodes. **Current results:** 19/19 checks passed.

### B3PoW-Scratch verification

Standalone test-vector and (optional) live-node verification (no build required):

```bash
pip3 install blake3
python3 contrib/testing/verify-b3pow.py                  # vectors only
python3 contrib/testing/verify-b3pow.py --rpc-port=18545 # + live blocks
```

The script imports the canonical Python reference
[`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](contrib/miner/b3miner-rtl/ref/b3pow_ref.py)
and re-derives every entry in
[`src/test/data/b3pow_consensus_vectors.json`](src/test/data/b3pow_consensus_vectors.json).

See [contrib/testing/README.md](contrib/testing/README.md) for full details.

Mining
------

B3Chain uses `getblocktemplate` (BIP 22/23) for mining. A reference
CPU miner is provided for protocol validation and small-scale solo
mining:

```bash
pip3 install blake3
python3 contrib/miner/b3chain-cpuminer.py --regtest --coinbaseaddr b3rt1q...
```

**The reference CPU miner is a correctness reference, not a production
miner.** Pure-Python B3PoW-Scratch achieves a handful of hashes per
second per core — useful for testing the end-to-end stack and for
verifying pool implementations byte-for-byte, but not competitive on
mainnet. Production miners run the algorithm on
[B3Miner-1](contrib/miner/b3miner-firmware/README.md) or equivalent
FPGA hardware (see [`contrib/miner/b3miner-rtl/`](contrib/miner/b3miner-rtl/)).

The legacy double-BLAKE3 GPU kernels in
[`contrib/miner/b3chain-gpuminer/`](contrib/miner/b3chain-gpuminer/)
target the pre-Scratch PoW and **do not produce valid B3Chain mainnet
shares**. They are retained as a reference for the previous algorithm
only.

See [doc/mining.md](doc/mining.md) for the full mining specification
and [doc/stratum.md](doc/stratum.md) for the pool-implementer contract
(PoW computation, test vectors, and the B3PoW-Scratch specification
reference).

Based on Bitcoin Core
---------------------

B3Chain is forked from [Bitcoin Core 30.2.0](https://github.com/bitcoin/bitcoin).
The fork changes only what must change (PoW algorithm, chain identity, genesis
blocks, branding) and preserves everything else.

Upstream security fixes and non-consensus improvements from Bitcoin Core are
cherry-picked periodically.

License
-------

B3Chain Core is released under the terms of the MIT license. See
[COPYING](COPYING) for more information or see
https://opensource.org/license/MIT.

Links
-----

- **Website:** https://b3chain.org
- **Testing & Verification:** https://b3chain.org/testing.html
- **Core repo:** https://github.com/b3chain/b3chain
- **Website repo:** https://github.com/b3chain/b3chain-website
