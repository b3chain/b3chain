B3Chain Core
============

https://b3chain.org

B3Chain is a conservative Proof-of-Work Layer 1 blockchain built in the spirit
of Bitcoin Core. It replaces Bitcoin's SHA-256d mining algorithm with
**double BLAKE3-256** while keeping everything else as close to Bitcoin as possible.

What is B3Chain?
----------------

B3Chain Core connects to the B3Chain peer-to-peer network to download and fully
validate blocks and transactions. It includes a wallet and graphical user
interface, which can be optionally built.

### Key differences from Bitcoin Core

| Feature | Bitcoin | B3Chain |
|---------|---------|---------|
| PoW algorithm | Double SHA-256 | Double BLAKE3-256 |
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

Further information is available in the [doc folder](/doc), including:
- [PoW design document](doc/b3chain-pow-design.md)
- [Mining documentation](doc/mining.md)
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

### BLAKE3 PoW verification

Standalone test vector verification (no node required):

```bash
pip3 install blake3
python3 contrib/testing/verify-blake3-pow.py
```

**Current results:** 9/9 vectors passed.

See [contrib/testing/README.md](contrib/testing/README.md) for full details.

Mining
------

B3Chain uses `getblocktemplate` (BIP 22/23) for mining. A reference CPU miner
is provided:

```bash
pip3 install blake3
python3 contrib/miner/b3chain-cpuminer.py --regtest --coinbaseaddr b3rt1q...
```

See [doc/mining.md](doc/mining.md) for the full mining specification, test
vectors, and stratum protocol notes.

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
