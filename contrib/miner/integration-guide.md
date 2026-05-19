# B3PoW-Scratch Integration Guide for Mining-Software Authors

**Audience.** Maintainers of existing mining tools (cpuminer-multi,
BFGMiner, ckpool/ckminer, custom in-house miners) and mining-OS distros
(HiveOS, MinerStat, MinerOS) who want to add B3Chain support to a
shipping codebase.

**Status.** Draft for review by external maintainers. The on-wire
contract, the consensus vectors, and the four in-tree reference
implementations are stable; this document is what an integrator needs
to map them into their own tool.

**Companion docs.**

- [`doc/stratum.md`](../../doc/stratum.md) — pool implementer contract (share-validation rules, target maths, default ports).
- [`doc/mining.md`](../../doc/mining.md) — miner workflow, `getblocktemplate` walkthrough, reference CPU miner.
- [`doc/pool-operator-guide.md`](../../doc/pool-operator-guide.md) — pool-operator deployment guide (the other half of this launch package).
- [`contrib/miner/b3miner-rtl/SPEC.md`](b3miner-rtl/SPEC.md) — normative algorithm specification.
- [`doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../../doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md) — design rationale.

---

## 1. Why this document

B3Chain's PoW is **B3PoW-Scratch v1.1**: a memory-hard BLAKE3 variant
over a 1 MiB scratchpad with 8 lanes and 2 048 read-modify-write
iterations per hash. The block header layout, Stratum framing, coinbase
splice, and difficulty maths are byte-identical to Bitcoin; the only
thing that changes is the proof-of-work hash function. This guide
gives an integrator the inner-loop pseudocode, the pad-cache pattern
the algorithm requires, the CI gate they must pass, and templated PRs
they can adapt for upstream.

---

## 2. Algorithm definition — single source of truth

The normative specification lives at
[`contrib/miner/b3miner-rtl/SPEC.md`](b3miner-rtl/SPEC.md). Read it
before anything else.

The CI gate for every port is the consensus vector set at
[`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json).
At launch the file ships 7 vectors covering genesis templates,
mainnet/regtest target boundaries, non-zero `prev_block_hash`, and a
cache-pair (two nonces sharing one parent). The set will grow over
time; treat it as authoritative on whatever version your tree pins.

**Every miner that claims B3PoW-Scratch v1.1 compliance MUST produce
byte-identical 32-byte output to
[`b3pow_ref.b3pow_scratch`](b3miner-rtl/ref/b3pow_ref.py) for every
input.** If your port does not pass every vector in
`b3pow_consensus_vectors.json`, it is wrong, and shares it produces will
not be accepted by a B3Chain pool or node. There is no grace period
and no "close enough".

---

## 3. Reference implementations

Four in-tree implementations are CI-gated against the same vector set.
Use whichever is closest to your language and porting target.

| Language | Path | Role |
|---|---|---|
| Python | [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](b3miner-rtl/ref/b3pow_ref.py) | Canonical reference. Pure-Python, deliberately verbose; doubles as the executable spec. |
| C++ | [`src/crypto/b3pow_scratch.{h,cpp}`](../../src/crypto/) | Production consensus validator inside `b3chaind`. Has a wall-clock budget hook (default 50 ms per header). |
| TypeScript | [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../testnet/pool/src/lib/b3pow-scratch.ts) | Pool-side validator; runs in Node and the browser. Uses `@noble/hashes/blake3`. |
| SystemVerilog | [`contrib/miner/b3miner-rtl/rtl/`](b3miner-rtl/rtl/) | KU5P FPGA RTL; `params_pkg.sv` exposes the same constants. |

Each is small (a few hundred to ~1 500 LOC) and reads end-to-end. The
Python reference is the one to copy when porting to a new high-level
language; the C++ port is the one to copy when porting to a tight
inner-loop language. The RTL is the one to copy if you are building
hardware — but the data flow is identical to the Python.

---

## 4. Block header layout (unchanged from Bitcoin)

The 80-byte header is byte-identical to Bitcoin. Only the hash function
applied to it differs.

```
+--------+----------------------------------+----------------------+
| offset |  field                           |  size & encoding     |
+--------+----------------------------------+----------------------+
|  0     |  version                         |  4  bytes,  u32 LE   |
|  4     |  prev_block_hash                 | 32  bytes,  internal |
|        |                                  |     (little-endian   |
|        |                                  |      uint256)        |
| 36     |  merkle_root                     | 32  bytes,  internal |
| 68     |  ntime                           |  4  bytes,  u32 LE   |
| 72     |  nbits  (compact target)         |  4  bytes,  u32 LE   |
| 76     |  nonce                           |  4  bytes,  u32 LE   |
+--------+----------------------------------+----------------------+
total                                          80 bytes
```

`prev_block_hash` and `merkle_root` are stored in **internal /
little-endian byte order** (the same convention as Bitcoin). Block
explorers, `b3chain-cli`, and `getblocktemplate` display them in
**big-endian**; byte-reverse before placing them in the header.

The B3PoW-Scratch function takes **two** inputs: the 80-byte header and
the 32-byte `prev_block_hash` (the same bytes that appear at offset
4…36 in the header). The `prev_block_hash` is also the salt for the
scratchpad-init step, which is what binds each PoW attempt to a
specific parent.

---

## 5. The PoW computation

The top-level function is five lines. Full byte-level semantics are in
[`SPEC.md`](b3miner-rtl/SPEC.md) §6.

```
def b3pow_scratch(header, prev_block_hash):
    seed  = blake3(header)                                # 32 B
    pad   = init_scratchpad(prev_block_hash)              # 1 MiB
    lanes = init_lanes(seed)                              # 8 × 32 B

    for r in range(2048):                                 # ITERATIONS
        addr  = derive_addresses(lanes, r)                # 8 × 11 bits
        block = parallel_read(pad, addr)                  # 8 × 64 B
        lanes, new_block = mix(lanes, block)              # 2 BLAKE3 rounds
        parallel_write(pad, addr, xor(block, new_block))  # RMW

    return blake3(serialize(lanes) || header[76:80])      # 32 B
```

Substeps map to spec sections as follows:

| Step                | Reference        | Cost (CPU, single core)   |
|---------------------|------------------|--------------------------|
| `init_scratchpad`   | SPEC §6.1        | ~5 ms (16 384 × BLAKE3-XOF) |
| `init_lanes`        | SPEC §6.2        | < 100 µs                  |
| `derive_addresses`  | SPEC §6.3        | a few µs / iteration      |
| `parallel_read`     | SPEC §6.4        | dominated by cache misses |
| `mix` (2-round)     | SPEC §6.5        | the main inner-loop cost  |
| `parallel_write`    | SPEC §6.6        | (writes back XOR result)  |
| Final BLAKE3        | SPEC §6.7        | < 100 µs                  |

The 2 048-iteration loop body is the entire PoW work; the
scratchpad-init cost is amortised across every nonce that shares
`prev_block_hash` (see §6).

---

## 6. The pad-caching contract (mandatory)

**`b3pow_scratch` mutates its `pad` argument.** This is by design — the
RMW writeback at step `parallel_write` is what makes the iterations
data-dependent and prevents trivial parallelisation across nonces.

For mining (or pool validation), the consequence is:

1. The pristine `init_scratchpad(prev_block_hash)` output is what is
   actually amortisable across nonces. It is identical for every header
   that shares the same parent block.
2. **You must keep a pristine copy and `memcpy` it into a fresh
   working pad on every PoW call.** Passing the same `pad` to two
   sequential calls without re-copying it will produce wrong results
   on the second call.
3. The init step is ~5–10 ms; the per-nonce copy is ~50–100 µs. For
   any worker doing more than one nonce per parent (i.e. effectively
   all of them), the cache pays for itself within the first nonce.

The in-tree implementations enforce this pattern:

- TypeScript: [`contrib/testnet/pool/src/lib/pad-cache.ts`](../testnet/pool/src/lib/pad-cache.ts) (`PadCache.getFresh(prevHashLE)`).
- Python: [`contrib/miner/b3chain-cpuminer.py`](b3chain-cpuminer.py) class `PadCache` (search for `_pristine` / `get_fresh`).
- C++: [`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp) — the consensus `Hash()` overload takes a `PadPtr` (`shared_ptr<const Pad>`) and `memcpy`s into a local heap `Pad` on every call.

### 6.1 Python pad-cache pattern

```python
import struct, sys
sys.path.insert(0, 'contrib/miner/b3miner-rtl/ref')
from b3pow_ref import b3pow_scratch, init_scratchpad

class PadCache:
    def __init__(self, capacity=4):
        self._capacity = capacity
        self._pristine = {}     # prev_le -> bytes (immutable pristine init)
        self._order = []        # LRU ordering

    def get_fresh(self, prev_le: bytes) -> bytearray:
        assert len(prev_le) == 32
        p = self._pristine.get(prev_le)
        if p is None:
            p = bytes(init_scratchpad(prev_le))          # ~10 ms
            self._pristine[prev_le] = p
            self._order.append(prev_le)
            while len(self._order) > self._capacity:
                self._pristine.pop(self._order.pop(0), None)
        else:
            self._order.remove(prev_le)
            self._order.append(prev_le)
        return bytearray(p)                              # ~100 us memcpy

cache = PadCache()
def pow_hash(header: bytes, prev_le: bytes) -> bytes:
    pad = cache.get_fresh(prev_le)
    return b3pow_scratch(header, prev_le, pad=pad).pow_hash
```

### 6.2 TypeScript pad-cache pattern

Lifted from [`pad-cache.ts`](../testnet/pool/src/lib/pad-cache.ts) and
[`b3pow-scratch.ts`](../testnet/pool/src/lib/b3pow-scratch.ts):

```typescript
import { initScratchpad, b3powScratch, SCRATCH_BYTES } from "./b3pow-scratch";

class PadCache {
    private readonly capacity: number;
    private readonly map = new Map<string, Uint8Array>(); // hex key -> pristine pad

    constructor(capacity = 4) { this.capacity = capacity; }

    getFresh(prevHashLE: Uint8Array): Uint8Array {
        const key = Buffer.from(prevHashLE).toString("hex");
        let pristine = this.map.get(key);
        if (!pristine) {
            pristine = initScratchpad(prevHashLE);               // ~10 ms
            this.map.set(key, pristine);
            while (this.map.size > this.capacity) {
                const oldest = this.map.keys().next().value!;
                this.map.delete(oldest);
            }
        } else {
            this.map.delete(key);                                // bump LRU
            this.map.set(key, pristine);
        }
        const copy = new Uint8Array(SCRATCH_BYTES);
        copy.set(pristine, 0);                                    // ~100 us
        return copy;
    }
}

const cache = new PadCache();
function powHash(header: Uint8Array, prevLE: Uint8Array): Uint8Array {
    const pad = cache.getFresh(prevLE);
    return b3powScratch(header, prevLE, pad).powHash;
}
```

### 6.3 Cache sizing

For a Stratum-V1 worker (one parent at a time), capacity 2 is enough
(tip + one stale tip during a reorg). For a pool's share validator,
capacity 4–8 is appropriate (tip + a handful of stale or sibling
parents that might still produce late shares). Each entry is 1 MiB; do
not let the cache grow unbounded.

---

## 7. Stratum V1 wire protocol

B3Chain pools speak standard Stratum V1. The full protocol is documented
in [`doc/stratum.md`](../../doc/stratum.md); this section covers only
the per-hash inner loop an integrator needs.

`mining.notify` payload (positional, identical to Bitcoin):

```
[ job_id, prev_hash_be_hex, coinb1_hex, coinb2_hex,
  merkle_branches_be_hex_list,
  "0x" + version_hex, "0x" + nbits_hex, "0x" + ntime_hex,
  clean_jobs_bool ]
```

`mining.submit` payload (positional):

```
[ worker_name, job_id, extranonce2_hex, ntime_hex, nonce_hex ]
```

`mining.set_difficulty` payload: `[ share_difficulty_float ]`.

The per-share inner loop is identical to a Bitcoin Stratum miner up to
the hash function call:

```python
# pool sent us: job, en1 (extranonce1), share_difficulty
prev_le = bytes.fromhex(job.prev_be_hex)[::-1]
share_target = floor(POOL_DIFF1_TARGET / share_difficulty)
net_target   = nbits_to_target(job.nbits)

for en2 in extranonce2_slice:                       # split across workers
    coinbase = job.coinb1 + en1 + en2 + job.coinb2
    cb_txid_le = sha256d(coinbase)
    merkle_root_le = fold_merkle_branches(cb_txid_le, job.branches_be)

    for nonce in range(0, 0x1_0000_0000):
        if clean_epoch_changed: break               # abandon stale job

        header = serialize_header(job.version, prev_le, merkle_root_le,
                                  job.ntime, job.nbits, nonce)
        pow_le = b3pow_scratch(header, prev_le, pad=cache.get_fresh(prev_le)).pow_hash
        pow_int = int.from_bytes(pow_le, "little")

        if pow_int <= share_target:
            submit_share(job_id, en2, ntime=job.ntime, nonce=nonce)
            # keep scanning; only clean_epoch_changed breaks the loop
```

A complete working implementation of this is at
[`contrib/miner/b3chain-cpuminer.py`](b3chain-cpuminer.py). It is
pure-Python and slow on purpose (single-digit H/s/core) — read it for
correctness, not for inner-loop ideas.

### 7.1 Things an integrator commonly gets wrong

1. **Forgetting to byte-reverse `prev_hash_be_hex` before
   `prev_le`.** The Stratum wire field is big-endian display hex; the
   header field (and the input to `b3pow_scratch`) is little-endian
   bytes. Reverse before use.
2. **Re-using a mutated `pad` across two nonces.** See §6. Without
   the per-call `memcpy`, the second nonce gets a wrong pow_hash and
   the share rejects.
3. **Comparing `pow_hash` as big-endian.** The comparison is
   little-endian uint256 against the target integer; see §9. A
   big-endian compare will silently accept the wrong shares.
4. **Building `coinbase` without splicing the two extranonces.** The
   pool pre-cuts the coinbase around an `extranonce1 || extranonce2`
   placeholder. The full coinbase is `coinb1 || en1 || en2 || coinb2`.
5. **Not breaking the inner nonce loop on `clean_jobs=true`.** Stale
   shares for the previous tip will be rejected (`stale`) and waste
   worker CPU.

---

## 8. Stratum V2 considerations

The B3Chain pool exposes Stratum V2 in addition to V1 (see
[`contrib/testnet/pool/src/sv2/`](../testnet/pool/src/sv2/)). The wire
protocol — Noise NX handshake, frame layout, message types
(`SetupConnection`, `OpenStandardMiningChannel`,
`NewMiningJob`/`NewExtendedMiningJob`, `SubmitSharesStandard`) — is
unchanged from the upstream SV2 specification. The only B3Chain
difference is the proof-of-work function applied to the assembled
header inside `SubmitSharesStandard`.

If your tool already supports SV2 for Bitcoin, integration consists of:

1. Swapping `sha256d` for `b3pow_scratch` in the inner share-build step.
2. Maintaining a `PadCache` keyed on the parent hash (§6); SV2 jobs
   change parents on every `NewMiningJob`, so cache invalidation is
   driven by the same event.
3. **Static key for the Noise NX handshake.** SV2 NX requires the
   responder (the pool) to authenticate via a static X25519 key
   bundled in a signed certificate; see
   [`contrib/testnet/pool/src/sv2/lib/noise.ts`](../testnet/pool/src/sv2/lib/noise.ts).
   The initiator (the miner) MAY also offer a static key; in practice
   software miners pass an ephemeral key and FPGA miners (B3Miner-1)
   load the static key from an ATECC608B secure element on first
   boot. Both modes are accepted by the reference pool.

Upstream SV2 specification: <https://github.com/stratum-mining/sv2-spec>.

---

## 9. Difficulty / target maths

Identical to Bitcoin. Compact `nbits` decodes to a 256-bit target via:

```python
def nbits_to_target(nbits: int) -> int:
    size = (nbits >> 24) & 0xff
    word = nbits & 0x007fffff
    if size <= 3:
        return word >> (8 * (3 - size))
    return word << (8 * (size - 3))
```

The PoW comparison is **little-endian uint256** against the target:

```python
def meets_target(pow_le_bytes: bytes, target_int: int) -> bool:
    return int.from_bytes(pow_le_bytes, "little") <= target_int
```

Canonical implementations:

- Python: [`b3pow_ref.nbits_to_target`](b3miner-rtl/ref/b3pow_ref.py) and `check_pow`.
- C++: [`src/pow.cpp`](../../src/pow.cpp) `CheckProofOfWorkImpl` (consensus).
- TypeScript: [`b3pow-scratch.ts`](../testnet/pool/src/lib/b3pow-scratch.ts) `nbitsToTarget` and `checkPow`.

Share difficulty maths is the standard Bitcoin/Stratum convention. The
pool's diff-1 target is `0x00000000ffff0000…0000`; share target =
`floor(diff1_target / share_difficulty)`. The reference values are in
[`contrib/testnet/pool/src/lib/difficulty-math.ts`](../testnet/pool/src/lib/difficulty-math.ts)
and the Python miner mirrors them at the top of
[`b3chain-cpuminer.py`](b3chain-cpuminer.py).

---

## 10. Test vectors

The canonical vector file is
[`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json).
Schema: `schema_version=1`, `spec_version="0x00010101"`. Each entry
has `header_hex` (80 bytes), `prev_block_hash_hex` (32 bytes),
`expected_pow_hash_hex` (32 bytes, raw LE), `nbits_hex`, and
`expected_check_pow`.

### Worked example — vector `genesis_mainnet_template`

```
name              : genesis_mainnet_template
header_hex        : 01000000 0000000000000000000000000000000000000000000000000000000000000000
                    0000000000000000000000000000000000000000000000000000000000000000
                    8041a967 ffff7f1d 286d5105
prev_block_hash_hex : 0000000000000000000000000000000000000000000000000000000000000000
nbits_hex           : 0x1d7fffff
expected_pow_hash_hex : 50c8c8def866529c7637868d175ec80dafcc59ed5a375abb8b2fdb5b53a15c77
expected_check_pow    : false
```

Reading the header byte-by-byte:

```
01000000                                                     -> version  = 1
0000000000000000000000000000000000000000000000000000000000000000  -> prev_hash = 0×32 (LE)
0000000000000000000000000000000000000000000000000000000000000000  -> merkle    = 0×32 (LE)
8041a967                                                     -> ntime    = 0x67a94180
ffff7f1d                                                     -> nbits    = 0x1d7fffff
286d5105                                                     -> nonce    = 0x0551 6d28
```

If your port hashes that 80-byte header against an all-zero
`prev_block_hash` and emits any value other than the
`expected_pow_hash_hex`, it is broken.

### 10.1 Validating against the full vector set

The fastest path is to re-use the in-tree verifier:

```bash
pip3 install blake3
python3 contrib/testing/verify-b3pow.py
```

This walks every entry in `b3pow_consensus_vectors.json`, recomputes
the hash through the Python reference, and prints PASS/FAIL per entry.
It also (with `--rpc-port=PORT`) re-derives PoW for every recent block
on a live node.

For ports in other languages, the integrator's CI script SHOULD load
the JSON directly and assert byte-equality on each entry. See
[`src/test/b3pow_scratch_tests.cpp`](../../src/test/b3pow_scratch_tests.cpp)
for the C++ pattern and
[`contrib/testnet/pool/tests/`](../testnet/pool/tests/) for the
TypeScript pattern.

---

## 11. Performance expectations

Per-hash cost on a 2026-era Ryzen 7950X core:

| Implementation                 | H/s/core (approx.)        | Source                                   |
|--------------------------------|----------------------------|------------------------------------------|
| Python reference (unoptimised) | single-digit (~3–8 H/s)    | `contrib/testing/bench/results/r0/`     |
| C++ consensus (`b3pow_scratch.cpp`) | ~30 H/s                | `contrib/testing/bench/results/r0/` (target — bench bring-up ongoing) |
| Hand-tuned SIMD C++ (hypothetical) | ~50–150 H/s             | algebraic estimate, not measured        |
| B3Miner-1 (KU5P FPGA, single card) | ~8 MH/s (target)        | `doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md` §6, `contrib/testing/bench/results/r0/bench-b3pow-fpga.csv` |

Empty cells in the bench tree are the honest answer: at launch we do
not have a measured FPGA number on production silicon yet. Watch
[`contrib/testing/bench/results/r0/`](../testing/bench/results/r0/)
and [`HARDWARE.md`](../testing/bench/results/r0/HARDWARE.md) for
methodology and the first measured runs.

Expected hardware ranking, in descending H/s/$:

1. **B3Miner-1 (KU5P FPGA)** — native target, ~10 W card.
2. **Custom B3PoW ASIC** — feasible; small per-hash advantage over (1)
   because the algorithm is memory-bandwidth bound, not compute-bound.
3. **Modern CPU** — usable for verification and reference mining; not
   competitive on cost per hash.
4. **GPU** — B3PoW-Scratch is **GPU-hostile by design**. The
   in-tree CUDA miner at
   [`contrib/miner/b3chain-gpuminer/`](b3chain-gpuminer/) is
   deprecated and targets the retired double-BLAKE3 PoW; it will not
   produce valid B3Chain shares. See its
   [`README.md`](b3chain-gpuminer/README.md) for the deprecation
   banner.

---

## 12. Hardware-targeted ports

If your port targets custom hardware (ASIC, GPU, different FPGA
family), additional reading:

- [`doc/analysis/FPGA-FEASIBILITY.md`](../../doc/analysis/FPGA-FEASIBILITY.md) — KU5P resource usage, MMCM timing, BRAM occupancy, ASIC port estimate. (Forthcoming, Phase 3.5.)
- [`doc/analysis/ASIC-ECONOMICS.md`](../../doc/analysis/ASIC-ECONOMICS.md) — what a custom ASIC would look like, NRE cost estimate, breakeven hashrate. (Forthcoming, Phase 3.5.)
- [`contrib/miner/b3miner-rtl/docs/architecture.md`](b3miner-rtl/docs/architecture.md) — block diagram of the reference FPGA implementation.
- [`contrib/miner/b3miner-rtl/docs/HWLOOP.md`](b3miner-rtl/docs/HWLOOP.md) — cycle-level inner-loop walk-through.

B3PoW-Scratch is GPU-hostile by design, not GPU-resistant by accident:
the 1 MiB sequential data-dependent scratchpad exceeds consumer GPU L1
and the address sequence prevents speculative prefetch across nonces.
We publish numbers honestly and encourage independent verification
rather than relying on the bench rows alone — if your GPU port
substantially outperforms the bench, please open an issue. Either the
bench methodology is wrong or you have found something interesting.

---

## 13. CI gate

The minimum bar for a B3PoW-Scratch v1.1 port to be considered
correct:

1. **Vector parity.** Pass every entry in
   [`b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json):
   the recomputed `pow_hash` matches `expected_pow_hash_hex`
   byte-for-byte, and the recomputed `int_le(pow_hash) <= target`
   boolean matches `expected_check_pow`.
2. **Fuzz parity.** For at least 1 000 random 80-byte headers paired
   with random or sweep-derived 32-byte `prev_block_hash`, the port
   produces byte-identical output to `b3pow_ref.b3pow_scratch`. A
   minimal driver:

   ```python
   import os, sys, struct
   sys.path.insert(0, 'contrib/miner/b3miner-rtl/ref')
   from b3pow_ref import b3pow_scratch
   from your_port import b3pow_scratch as port_b3pow

   for _ in range(1000):
       hdr  = os.urandom(80)
       prev = os.urandom(32)
       ref  = b3pow_scratch(hdr, prev).pow_hash
       got  = port_b3pow(hdr, prev)
       assert ref == got, (hdr.hex(), prev.hex(), ref.hex(), got.hex())
   print("OK: 1000 random headers")
   ```
3. **Malformed input.** A port MUST cleanly fail (raise / return error
   / refuse to mine) on `len(header) != 80` or
   `len(prev_block_hash) != 32`, rather than silently returning a
   wrong-shape buffer.

In-tree CI examples to crib from:

- [`contrib/miner/b3miner-rtl/ref/tests/`](b3miner-rtl/ref/tests/) — Python pytest parity tests.
- [`src/test/b3pow_scratch_tests.cpp`](../../src/test/b3pow_scratch_tests.cpp) — C++ Boost test consuming the JSON vectors.
- [`contrib/testnet/pool/tests/b3pow-scratch.test.ts`](../testnet/pool/tests/b3pow-scratch.test.ts) — TypeScript port parity.

---

## 14. Issue reporting and contact

- **GitHub issues:** <https://github.com/b3chain/b3chain/issues> —
  tag `mining-integration` and `pow:b3pow-scratch`. Include your
  port's language, the failing vector name (or fuzz input that
  diverged), the expected hash, and the hash you got.
- **Email:** `dev@b3chain.org` — for sensitive reports (vector
  divergence that may indicate a real bug in the spec, not a port
  bug), please email first.
- **Discord / Matrix:** planned; channel addresses will be published
  on <https://b3chain.org> when launched. Until then GitHub issues are
  the canonical channel.
- **Security disclosures:** [`SECURITY.md`](../../SECURITY.md) is the
  canonical contact; please follow the responsible-disclosure window
  before public posts.

---

## 15. Draft PR templates

These are templates for integrator-side pull requests to upstream
mining tools. **None of the PRs below have been opened.** The B3Chain
project does not unilaterally open PRs to external upstreams; the
integrator is the right person to do that, because they will end up
maintaining the integration. We are happy to provide review, CI
artefacts, and benchmark numbers when an integrator chooses to land
the work.

### 15.1 `cpuminer-multi` — add `-a b3pow_scratch`

**Title.** `Add b3pow_scratch algorithm (B3Chain mainnet/testnet)`

**Body (templated).**

```markdown
This PR adds support for **B3PoW-Scratch v1.1**, the proof-of-work
algorithm used by B3Chain (https://b3chain.org). B3PoW-Scratch is a
memory-hard BLAKE3 variant over a 1 MiB scratchpad with 8 lanes and
2 048 read-modify-write iterations per hash. The chain's Stratum
framing, coinbase splice, and difficulty maths are byte-identical to
Bitcoin; only the PoW hash function changes.

### What this PR does

- Adds `algo/b3pow_scratch.c` + header, ported from the reference
  Python at https://github.com/b3chain/b3chain/blob/main/contrib/miner/b3miner-rtl/ref/b3pow_ref.py
  and the C++ consensus at https://github.com/b3chain/b3chain/blob/main/src/crypto/b3pow_scratch.cpp.
- Wires `-a b3pow_scratch` into `algo-gate.{c,h}` and the CLI parser.
- Adds the standard pad-cache pattern (mandatory; see "Pad caching"
  below).
- Adds CI vector parity against
  https://github.com/b3chain/b3chain/blob/main/src/test/data/b3pow_consensus_vectors.json
  in `tests/test_b3pow_scratch.c`.

### Pad caching (mandatory)

`b3pow_scratch(header, prev_block_hash, pad)` mutates `pad`. Miners
hashing many nonces against the same `prev_block_hash` MUST keep a
pristine copy and `memcpy` it into a fresh working pad on every PoW
call. Without the cache, each PoW pays a ~5 ms init; with the cache,
the per-nonce cost is one ~50 µs `memcpy` plus the 2 048-iteration
mix loop.

Reference implementations of the pattern:
- TypeScript: https://github.com/b3chain/b3chain/blob/main/contrib/testnet/pool/src/lib/pad-cache.ts
- Python: https://github.com/b3chain/b3chain/blob/main/contrib/miner/b3chain-cpuminer.py (search `class PadCache`)
- C++:    https://github.com/b3chain/b3chain/blob/main/src/crypto/b3pow_scratch.cpp (`Hash()` overload taking `PadPtr`)

### CI / vector check

A minimum CI check should pass every entry in
`b3pow_consensus_vectors.json`. See `tests/test_b3pow_scratch.c` for
the cpuminer-multi-flavoured runner.

### Benchmark

(measured H/s/core on `<your CPU>`):

| Threads | H/s   | Notes |
|---------|-------|-------|
| 1       | __ H/s | __ |
| 4       | __ H/s | __ |
| n       | __ H/s | scales linearly until BLAKE3 SIMD throughput saturates |

This is hash-rate-only; the chain itself is designed so the most
economical hardware is an FPGA (B3Miner-1, ~10 W). cpuminer-multi
support is for testnet / regtest / pool integration testing, not
mainnet competitive mining.

### References

- Spec: https://github.com/b3chain/b3chain/blob/main/contrib/miner/b3miner-rtl/SPEC.md
- Stratum guide: https://github.com/b3chain/b3chain/blob/main/doc/stratum.md
- Integrator handbook: https://github.com/b3chain/b3chain/blob/main/contrib/miner/integration-guide.md
- Whitepaper: https://github.com/b3chain/b3chain/blob/main/doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md
```

**Notes for the integrator.** The cpuminer-multi `algo-gate` requires
`scanhash`, `hash`, `set_target` callbacks; map them onto the
`derive_addresses` / `mix` / final-BLAKE3 inner loop directly. The
existing `algo/blake3.c` is the closest in shape but only covers the
BLAKE3 primitive, not the scratchpad. The 2-round reduced BLAKE3 in
`mix` is the bit most ports get wrong on the first try; copy the
`blake3_short_compress` function out of `b3pow_ref.py` or
`b3pow_scratch.cpp` rather than re-deriving it.

### 15.2 BFGMiner — add B3Chain backend

**Title.** `Add B3Chain (b3pow_scratch) backend`

**Body (templated).**

```markdown
This PR adds a B3Chain backend to BFGMiner using the B3PoW-Scratch
v1.1 PoW. The wire protocol is standard Stratum V1; only the
share-validation hash function changes.

### What this PR does

- Adds `driver-b3chain.c` driver registration calling out to a new
  `algorithm/b3pow_scratch.{c,h}`.
- Adds the mandatory per-parent pad cache (see "Pad caching" below).
- Adds vector parity tests in `tests/test_b3pow_scratch.c` against
  https://github.com/b3chain/b3chain/blob/main/src/test/data/b3pow_consensus_vectors.json.
- Adds a config entry for `algorithm=b3pow_scratch` and updates the
  pool-URL scheme detection so `stratum+tcp://pool.b3chain.org:3333`
  is recognised.

### Driver registration boilerplate

Mirrors the existing `driver-cpu.c` / `driver-opencl.c` patterns;
the only B3Chain-specific glue is `b3pow_scratch` replacing the
`sha256d` call inside `submit_work`.

### Pad caching

See "Pad caching" in the cpuminer-multi PR template above. Identical
contract: pristine init per parent, fresh `memcpy` per nonce.

### References

(Same as the cpuminer-multi PR; see links above.)
```

### 15.3 Mining-OS distros (HiveOS, MinerStat, MinerOS)

**Scope.** Mining-OS distros do not need to add `b3pow_scratch` to a
CPU miner — at launch, B3Chain's CPU/GPU miners are not competitive,
and the supported hardware path is FPGA-only (B3Miner-1). The right
mining-OS deliverable at launch is **packaging the B3Miner-1 firmware
+ host stack** as a flashable image with the appropriate Stratum
config.

**Title.** `Add B3Chain (B3Miner-1 FPGA) miner profile`

**Body (templated).**

```markdown
This PR adds a B3Chain miner profile that drives the B3Miner-1 FPGA
card (Xilinx Kintex UltraScale+ KU5P + ESP32-S3 host) over Stratum V1.

### What this PR provides

- A miner profile (`miners/b3miner-1.{json,sh}`) targeting the
  B3Miner-1 host firmware.
- Default Stratum endpoint: `stratum+tcp://pool.b3chain.org:3333`
  (project reference testnet pool; operator should swap in their
  pool of choice).
- Hashrate reporting + per-card temperature / fan curves matching the
  existing OpenWifi-class FPGA cards.

### FPGA bitstream artefact

The bitstream is built from
https://github.com/b3chain/b3chain/tree/main/contrib/miner/b3miner-rtl
and is signed + published with each B3Miner-1 firmware release; URL
will be:

> `https://github.com/b3chain/b3chain/releases/download/b3miner-rtl-vX.Y.Z/b3miner-1.bit`

(Placeholder; updated once a tagged release ships.)

Host firmware source: https://github.com/b3chain/b3chain/tree/main/contrib/miner/b3miner-firmware

### CPU / GPU support

B3PoW-Scratch is GPU-hostile by design; the in-tree CUDA miner is
deprecated and CPU support exists only as a reference implementation
(https://github.com/b3chain/b3chain/blob/main/contrib/miner/b3chain-cpuminer.py).
This PR therefore packages **FPGA only**. If your platform wants to
list a CPU profile for testnet/regtest experimentation, see the
integration guide
(https://github.com/b3chain/b3chain/blob/main/contrib/miner/integration-guide.md)
§3 for the reference implementations.

### References

(Same as the cpuminer-multi PR; see links above.)
```

---

## 16. External maintainer engagement tracker

A working list of external maintainers we plan to reach out to with
the PR templates above. Status is honest: at launch nothing has been
sent. Each row will be updated as conversations happen.

| Tool / distro    | Maintainer(s)                          | What we plan to send                                                  | First contact (planned) | Status at launch |
|------------------|----------------------------------------|----------------------------------------------------------------------|-------------------------|------------------|
| `cpuminer-multi` | TheRavenwolf (@tpruvot, @JayDDee, fork maintainers) | PR template §15.1 + benchmark numbers + vector-check CI script         | post-launch             | to be contacted  |
| BFGMiner         | Luke Dashjr (Luke-Jr), @ckolivas / `ckpool` | PR template §15.2 + driver registration boilerplate + vector-check CI | post-launch             | to be contacted  |
| HiveOS           | HiveOS team (community + ops)          | PR template §15.3 + signed B3Miner-1 bitstream URL once tagged        | post-launch             | to be contacted  |
| MinerStat        | MinerStat team                         | PR template §15.3 + signed B3Miner-1 bitstream URL once tagged        | post-launch             | to be contacted  |
| MinerOS / SimpleMining (community distros) | community maintainers              | PR template §15.3 + signed B3Miner-1 bitstream URL once tagged        | post-launch             | to be contacted  |

Updates to this table belong in this file, not in the launch plan.
The expected cadence is one row update every time a maintainer
replies; we will not edit history just to claim more progress.

---

## 17. Document version

| Version | Date       | Notes                                       |
|---------|------------|---------------------------------------------|
| 0.1     | 2026-05-19 | Initial draft, Phase 3.1 launch deliverable |

Last updated: 2026-05-19 (`SPEC_VERSION = 0x00010101`).
