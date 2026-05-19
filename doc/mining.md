# B3Chain Mining Documentation

## Proof-of-Work Algorithm

B3Chain uses **B3PoW-Scratch v1.1** for proof-of-work — a memory-hard,
BLAKE3-based, scratchpad-driven PoW. Per-hash work involves a 1 MiB
on-chip scratchpad, 8 parallel lanes, and 2 048 sequential
read-modify-write iterations. See
[`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md)
for the normative specification.

```
PoW_hash = b3pow_scratch( header, prev_block_hash )
```

where `header` is the standard 80-byte serialized block header:

| Field           | Size    | Encoding     |
|-----------------|---------|--------------|
| nVersion        | 4 bytes | int32, LE    |
| hashPrevBlock   | 32 bytes| uint256, LE  |
| hashMerkleRoot  | 32 bytes| uint256, LE  |
| nTime           | 4 bytes | uint32, LE   |
| nBits           | 4 bytes | uint32, LE   |
| nNonce          | 4 bytes | uint32, LE   |

`prev_block_hash` is the 32-byte SHA-256d block-identity hash of the
parent block (the same value used in `hashPrevBlock`, raw little-endian
bytes). Including it in the PoW binds each candidate header to a
specific parent, which (a) gives the scratchpad-init a unique salt per
parent and (b) means a fork ancestor change invalidates any reuse of a
pre-computed pad.

**Important:** Block identity hashes (block hash, txid, merkle tree) still
use double SHA-256, same as Bitcoin. Only the PoW validation uses
B3PoW-Scratch.

## Reference implementations and test vectors

| Layer | Path |
|---|---|
| Normative spec | [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) |
| Python reference (importable) | [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) |
| Consensus C++ | [`src/crypto/b3pow_scratch.cpp`](../src/crypto/b3pow_scratch.cpp) |
| RTL | [`contrib/miner/b3miner-rtl/rtl/`](../contrib/miner/b3miner-rtl/rtl/) |
| Pool TS validator | [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts) |
| Consensus vectors (JSON) | [`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json) |
| End-to-end verifier | [`contrib/testing/verify-b3pow.py`](../contrib/testing/verify-b3pow.py) |

The Stratum implementer guide [`doc/stratum.md`](stratum.md) contains a
slim "everything a pool author needs" view of the same material plus
the precise share-validation contract.

## Mining with getblocktemplate (BIP 22/23)

### Workflow

1. Call `getblocktemplate` with `{"rules": ["segwit"]}`.
2. Build the block header from the template fields.
3. Initialise the 1 MB scratchpad **once** from
   `previousblockhash` (raw LE bytes). Reuse it across every nonce for
   this parent.
4. Iterate nonce values, computing
   `b3pow_scratch(header, previousblockhash, pad=pad)`.
5. When `int_le(pow_hash) <= target`, submit via `submitblock`.

### Example (Python)

```python
import struct, sys
sys.path.insert(0, 'contrib/miner/b3miner-rtl/ref')
from b3pow_ref import b3pow_scratch, init_scratchpad, nbits_to_target

template = rpc.call("getblocktemplate", [{"rules": ["segwit"]}])

# Parent hash in raw LE bytes (RPC returns BE display hex).
prev_le = bytes.fromhex(template["previousblockhash"])[::-1]
pad = init_scratchpad(prev_le)        # 1 MB, init once per parent

target = nbits_to_target(int(template["bits"], 16))

# Build header (merkle_root_le computed from coinbase + txns elsewhere)
def header(nonce):
    h  = struct.pack('<i', template["version"])
    h += prev_le
    h += merkle_root_le
    h += struct.pack('<III', template["curtime"],
                     int(template["bits"], 16), nonce)
    return h

for nonce in range(0xFFFFFFFF):
    h = header(nonce)
    pow_hash = b3pow_scratch(h, prev_le, pad=pad).pow_hash
    if int.from_bytes(pow_hash, 'little') <= target:
        submit_block(h, transactions)
        break
```

Per-hash cost in pure Python is around 0.5–1 s on a 5 GHz x86 core, so
this reference is suitable for regtest, single-share Stratum
verification, and pool integration testing. It is **not** competitive
on mainnet — see the "Hardware" section below.

### Reference miner

A complete reference CPU miner is provided at:

```
contrib/miner/b3chain-cpuminer.py
```

It is a correctness reference, not a production miner: pure-Python
B3PoW-Scratch hashes a handful of times per second per thread. The
miner exists to:

- Validate the end-to-end RPC + Stratum pipeline.
- Let pool authors replay shares byte-for-byte against an
  independently-implemented PoW.
- Let firmware authors cross-check FPGA output against the same code
  the consensus uses.

For solo mining on regtest / testnet:

```bash
pip3 install blake3
python3 contrib/miner/b3chain-cpuminer.py --regtest \
    --coinbaseaddr b3rt1q...your_address...

python3 contrib/miner/b3chain-cpuminer.py --benchmark
```

### Hardware reference: B3Miner-1

The reference production miner is **B3Miner-1**, a single Kintex
UltraScale+ KU5P card with an ESP32-S3 host running open firmware. See
[`contrib/miner/b3miner-firmware/`](../contrib/miner/b3miner-firmware/)
(firmware) and
[`contrib/miner/b3miner-hardware/SCHEMATIC.md`](../contrib/miner/b3miner-hardware/SCHEMATIC.md)
(hardware). Hashrate is in the 10s of MH/s class at ~10 W;
detailed benchmarks live in
[`contrib/testing/bench/results/`](../contrib/testing/bench/results/)
once the bench has been run.

## Stratum Protocol Notes

Stratum / pool-implementer guidance has moved to its own document:
[`doc/stratum.md`](stratum.md). It covers share validation, block
submission, extranonce handling, default ports, and the B3PoW-Scratch
specification reference.

## Pool mining with the reference miner

The reference miner at `contrib/miner/b3chain-cpuminer.py` also speaks
**Stratum V1** and is the canonical way to verify a new pool
implementation byte-for-byte. Every share submitted to the pool is
printed with full diagnostic detail (job id, both extranonces, ntime,
nonce, full coinbase tx, coinbase txid, merkle root, 80-byte header,
PoW hash LE+BE, block hash, share/network targets, accepted/rejected,
RTT). Between shares, periodic "best-hash-so-far" progress lines show
the nonce search progressing.

### Quick start

```bash
pip3 install blake3

python3 contrib/miner/b3chain-cpuminer.py \
    --stratum stratum+tcp://pool.b3chain.org:3333 \
    --user alice@example.com.cpu1 --pass x \
    --threads 2 --json-log shares.jsonl
```

`--user` follows the pool's `<email>.<workerName>` convention used for
per-user accounting. `--pass` is ignored by the pool (default `"x"`).

### Pool-mode flags

| Flag | Purpose |
|---|---|
| `--stratum URL` | Pool URL, e.g. `stratum+tcp://...:3333` or `stratum+ssl://...:3334`. Selecting `--stratum` puts the miner in pool mode. |
| `--user USER` | Worker username (`<email>.<workerName>`). |
| `--pass PASS` | Worker password (default `"x"`). |
| `--useragent STR` | UA advertised in `mining.subscribe` (default `b3chain-cpuminer/1.0`). |
| `--json-log PATH` | Append-only JSONL of every event (see below). |
| `--quiet-progress` | Suppress per-N-hash console progress lines (still in JSONL). |
| `--progress-interval N` | Internal-hash count between progress lines (default 1,000,000). |
| `--reconnect-delay SEC` | Reconnect backoff base (default 5 s; capped at 60 s). |
| `--max-attempts N` | Stop after N share submissions (0 = forever; useful for tests). |
| `--threads N` | Number of mining threads (each searches a disjoint extranonce2 slice). |
| `--legacy-blake3d` | Use the retired double-BLAKE3 PoW for cross-checking historical vectors. **Will not produce valid B3Chain shares.** |

### What you see on stdout per share

When a worker's `b3pow_scratch(header, prev)` falls below the share
target, the miner prints a multi-line dump **before** sending
`mining.submit` (so the share is recorded even if the network drops on
the way out), then appends the server response and round-trip time.
The dump's "trigger" line names the PoW algorithm in use so JSONL
replay tools can pick the right verifier; otherwise the format is
identical to the legacy mode.

```text
[2026-05-15T10:22:31.482Z] === SHARE #42 (thread=0, job=00012ab) ===
  trigger             : pow <= shareTarget  (B3PoW-Scratch v1.1 check)
  job_id              : 00012ab
  extranonce1         : 0000003f                 (server-assigned)
  extranonce2         : 00000000                 (4 bytes, miner-chosen, thread 0 slice)
  ntime               : 0x6643b257  (1715769943, 2026-05-15T10:22:23+00:00)
  nonce               : 0x4d2a91f7  (1294467063)
  ...
```

A rejected share replaces the last two lines with a `REJECTED` status
and the server-supplied error tuple. A block-found share gets an
extra `*** BLOCK CANDIDATE ***` banner before the dump and `*** BLOCK
ACCEPTED ***` after the response.

### JSONL log format

Passing `--json-log shares.jsonl` writes one JSON object per line for
every event the miner observes. Useful events:

| `event` | When it fires |
|---|---|
| `connect` | TCP/TLS established. |
| `subscribed` | `mining.subscribe` response received (extranonce1, extranonce2_size). |
| `authorized` | `mining.authorize` response received. |
| `set_difficulty` | Server pushed a new share difficulty (initial + every vardiff retune). |
| `notify` | Server pushed a new job; full coinb1/coinb2/branches recorded. |
| `progress` | Per-worker periodic best-hash-so-far line. |
| `share_pre_submit` | Share found, dump printed, about to send `mining.submit`. |
| `share_submit` | `mining.submit` round-trip complete; includes accepted/rejected, error, RTT. |
| `block_found` | Share that also met the network target was accepted. |
| `disconnect` | TCP drop or handshake failure. |
| `summary` | Final stats (runtime, shares, blocks, attempts, avg hashrate). |

Each `share_submit` event includes a `pow_algo` field (`"b3pow_scratch_v1.1"`
or `"blake3d_legacy"`) so replay tools know which verifier to invoke.

To replay a share from the JSONL and verify your pool's share-validation
pipeline byte-for-byte:

```bash
jq -c 'select(.event=="share_submit") | {seq:.share_seq,job:.job_id,header:.header_hex,prev:.prev_hash_hex,pow_le:.pow_hash_le}' shares.jsonl
# Then for any line, recompute the hash and confirm it matches.
python3 -c "
import sys; sys.path.insert(0, 'contrib/miner/b3miner-rtl/ref')
from b3pow_ref import b3pow_scratch
h = bytes.fromhex(sys.argv[1])
prev = bytes.fromhex(sys.argv[2])
pow_le = b3pow_scratch(h, prev).pow_hash.hex()
print('matches' if pow_le == sys.argv[3] else 'MISMATCH', pow_le)
" "<header_hex>" "<prev_hash_hex>" "<pow_hash_le>"
```

### Stratum V2

This miner only speaks Stratum V1. The pool exposes V2 separately (port
3336 with its translator at port 3337); a future version of the miner
may add a `stratum2://` URL scheme.

### Windows test UI

On Windows, double-clicking
[`contrib/miner/tests/run_tests_ui.bat`](../contrib/miner/tests/run_tests_ui.bat)
opens a PyQt6 application that runs every miner test (helper unit
tests, argparse mutex, `--benchmark`, mock-pool E2E, JSONL re-derive,
solo regtest, live pool reachability, and the optional local Docker
pool stack) with one click and shows pass/fail/skip plus the live
console output of every run. See
[`contrib/miner/tests/README.md`](../contrib/miner/tests/README.md) for
details.

The same launcher also ships a **live mining dashboard** — click the
**Mine** toolbar button to open a separate window that drives the CPU
miner against any Stratum V1 pool with rolling 5-minute hashrate, an
auto-rescaling polyline chart, per-share details (job, ntime, nonce,
PoW LE/BE, share & network targets, RTT, server response), per-thread
breakdown, the last 200 shares, raw stdout + JSONL event tabs, and a
**Save Session** button that writes a `mining-session-*` directory
(stdout, JSONL, JSON & Markdown summaries).

## Performance considerations

B3PoW-Scratch is **intentionally slow per hash** — that is the security
budget. The expected hardware hierarchy is, in descending H/s/$:

1. **B3Miner-1 (KU5P FPGA)**: tens of MH/s at ~10 W. Native target.
   The 1 MB scratchpad lives entirely in on-chip BRAM, the 8-lane
   layout maps 1:1 to one read+write port per lane, and the reduced
   BLAKE3 mixer fits in a few hundred LUTs per lane.
2. **Custom B3PoW ASIC**: feasible but the per-hash advantage over
   point 1 is small (the algorithm is memory-bandwidth bound, not
   compute-bound). Section 8.D of
   [`SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) and
   [`doc/analysis/FPGA-FEASIBILITY.md`](analysis/FPGA-FEASIBILITY.md)
   work this out quantitatively.
3. **Modern CPU (e.g. Zen 4 AVX-512)**: roughly 50–150 H/s/core for
   the optimized C++ implementation. Hundreds of orders of magnitude
   slower per dollar than point 1.
4. **GPU**: implementable, but the 1 MB working set + sequential
   data-dependent address chain destroy GPU pipelining. Throughput is
   typically below CPU per dollar. **B3PoW-Scratch is GPU-hostile by
   design.**

This is why the bundled
[`contrib/miner/b3chain-gpuminer/`](../contrib/miner/b3chain-gpuminer/)
still targets the retired double-BLAKE3 PoW: a port to B3PoW-Scratch
would produce a miner that is correct but several orders of magnitude
slower than a CPU. The directory is retained as a reference for the
previous algorithm only.

The difficulty adjustment algorithm calibrates target block time
around expected B3Miner-1 hashrates (see "Difficulty Adjustment" below).

## Difficulty Adjustment

B3Chain uses Bitcoin's standard difficulty retarget algorithm:

- **Retarget interval:** Every 2016 blocks
- **Target block time:** 600 seconds (10 minutes)
- **Max adjustment:** 4x up or down per period

### Early Difficulty Guard

For the first 10,000 blocks, an additional guard prevents chain stalls:
if a block takes longer than 20 minutes (2x target), difficulty decreases
by 25%. This ensures the chain remains usable during the bootstrap period
when hashrate may be volatile.

After block 10,000, standard Bitcoin difficulty adjustment applies exclusively.
