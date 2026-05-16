# B3Chain Mining Documentation

## Proof-of-Work Algorithm

B3Chain uses **double BLAKE3-256** for proof-of-work:

```
PoW_hash = BLAKE3(BLAKE3(block_header))
```

where `block_header` is the standard 80-byte serialized block header:

| Field           | Size    | Encoding     |
|-----------------|---------|--------------|
| nVersion        | 4 bytes | int32, LE    |
| hashPrevBlock   | 32 bytes| uint256, LE  |
| hashMerkleRoot  | 32 bytes| uint256, LE  |
| nTime           | 4 bytes | uint32, LE   |
| nBits           | 4 bytes | uint32, LE   |
| nNonce          | 4 bytes | uint32, LE   |

**Important:** Block identity hashes (block hash, txid, merkle tree) still
use double SHA-256, same as Bitcoin. Only the PoW validation uses BLAKE3.

## BLAKE3 Test Vectors

Test vectors for verifying a BLAKE3 implementation byte-for-byte
(single hash, double hash, and full 80-byte block-header vectors) are
maintained in [`doc/stratum.md`](stratum.md#2-test-vectors), the
authoritative pool-implementer reference. Any change to this hashing
must be reflected there first.

## Mining with getblocktemplate (BIP 22/23)

### Workflow

1. Call `getblocktemplate` with `{"rules": ["segwit"]}`
2. Build the block header from the template fields
3. Iterate nonce values, computing `BLAKE3(BLAKE3(header))`
4. When `PoW_hash <= target`, submit via `submitblock`

### Example (Python pseudocode)

```python
import blake3, struct

def double_blake3(header_bytes):
    h1 = blake3.blake3(header_bytes).digest()
    return blake3.blake3(h1).digest()

# Get template from RPC
template = rpc.call("getblocktemplate", [{"rules": ["segwit"]}])
target = target_from_nbits(int(template["bits"], 16))

# Build header
header = struct.pack('<i', template["version"])
header += bytes.fromhex(template["previousblockhash"])[::-1]  # LE
header += merkle_root  # computed from coinbase + txns
header += struct.pack('<III', template["curtime"],
                      int(template["bits"], 16), 0)

# Mine
for nonce in range(0xFFFFFFFF):
    header = header[:76] + struct.pack('<I', nonce)
    pow_hash = double_blake3(header)
    if int.from_bytes(pow_hash, 'little') <= target:
        submit_block(header, transactions)
        break
```

### Reference Miner

A complete reference CPU miner is provided at:

```
contrib/miner/b3chain-cpuminer.py
```

Usage:
```bash
# Install dependency
pip3 install blake3

# Mine on regtest
python3 contrib/miner/b3chain-cpuminer.py --regtest \
    --coinbaseaddr b3rt1q...your_address...

# Benchmark hash rate
python3 contrib/miner/b3chain-cpuminer.py --benchmark
```

## Stratum Protocol Notes

Stratum / pool implementer guidance has moved to its own document:
[`doc/stratum.md`](stratum.md). It covers share validation, block
submission, extranonce handling, default ports, and the BLAKE3
specification reference.

## Pool Mining With The Reference Miner

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

### Pool mode flags

| Flag | Purpose |
|---|---|
| `--stratum URL` | Pool URL, e.g. `stratum+tcp://...:3333` or `stratum+ssl://...:3334`. Selecting `--stratum` puts the miner in pool mode. |
| `--user USER` | Worker username (`<email>.<workerName>`). |
| `--pass PASS` | Worker password (default `"x"`). |
| `--useragent STR` | UA advertised in `mining.subscribe` (default `b3chain-cpuminer/1.0`). |
| `--json-log PATH` | Append-only JSONL of every event (see below). |
| `--quiet-progress` | Suppress per-N-hash console progress lines (still in JSONL). |
| `--progress-interval N` | Internal-hash count between progress lines (default 1,000,000). |
| `--reconnect-delay SEC` | Reconnect backoff base (default 5s; capped at 60s). |
| `--max-attempts N` | Stop after N share submissions (0 = forever; useful for tests). |
| `--threads N` | Number of mining threads (each searches a disjoint extranonce2 slice). |

### What you see on stdout per share

When a worker's `BLAKE3(BLAKE3(header))` falls below the share target,
the miner prints a multi-line dump **before** sending `mining.submit`
(so the share is recorded even if the network drops on the way out),
then appends the server response and round-trip time:

```text
[2026-05-15T10:22:31.482Z] === SHARE #42 (thread=0, job=00012ab) ===
  trigger             : pow <= shareTarget  (BLAKE3(BLAKE3(header)) check)
  job_id              : 00012ab
  extranonce1         : 0000003f                 (server-assigned)
  extranonce2         : 00000000                 (4 bytes, miner-chosen, thread 0 slice)
  ntime               : 0x6643b257  (1715769943, 2026-05-15T10:22:23+00:00)
  nonce               : 0x4d2a91f7  (1294467063)
  attempts_this_job   : 1,294,467,064  (this thread)
  hashrate_this_share : 1.82 MH/s
  coinbase (188 B)    : 02000000010000000000000000000000000000000000000000000000000000
                        00000000ffffffff44031e0a000000003f00000000000000000a2f4233636861
                        696e20506f6f6c2fffffffff0200f902950000000016001431b3...
  coinbase_txid (BE)  : 9d27c1c81b73...e4f1a3
  merkle_root  (BE)   : 6e10b4a3c2d1...09afde
  header (80 B)       : 00000020 7d8e91...c2 6e10b4...09 57b24366 ffff7f1e f7912a4d
                        \--ver--/\------------- prev (LE) -------------/...
  PoW hash (LE)       : 8a3f4c00...000000
  PoW hash (BE)       : 00000000...4c3f8a
  block_hash (BE)     : 0000000019aabbcc...
                        (SHA256d, identity hash for explorer)
  share_target  (BE)  : 00000000003fffc0000000000000000000000000000000000000000000000000
  share_difficulty    : 1024.000000
  network_target(BE)  : 00000000ffff0000000000000000000000000000000000000000000000000000
  network_difficulty  : 1.000000
  pow_int / share_tgt : 0.318  (lower = better, must be <= 1)
  pow_int / net_tgt   : 0.000311
  is_block            : false
  ----- mining.submit -----
  -> {"id":17,"method":"mining.submit","params":["alice@example.com.cpu1","00012ab","00000000","6643b257","4d2a91f7"]}
  <- {"id":17,"result":true,"error":null}     rtt=12.4 ms
  status              : ACCEPTED  (server validated against share target)
  ====================================================================
[10:22:31.482] share=#42 job=00012ab nonce=0x4d2a91f7 pow_be=00000000084c3f8a... diff=1024 net_diff=1.000000 ACCEPTED  rtt=12.4ms  rate=1.82 MH/s
```

A rejected share replaces the last two lines with a `REJECTED` status
and the server-supplied error tuple. A block-found share gets an
extra `*** BLOCK CANDIDATE ***` banner before the dump and `*** BLOCK
ACCEPTED ***` after the response.

Between shares, every `--progress-interval` internal attempts emit a
one-line progress entry per worker:

```text
[10:22:29.014] progress thread=0 job=00012ab en2=00000000 attempts=5,000,000 rate=1.79 MH/s best_pow_be=000003a1f4... dist_to_share=8.41x dist_to_block=8617x
```

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

To replay a share from the JSONL and verify your pool's share-validation
pipeline byte-for-byte:

```bash
jq -c 'select(.event=="share_submit") | {seq:.share_seq,job:.job_id,header:.header_hex,pow_le:.pow_hash_le}' shares.jsonl
# Then for any line, double-BLAKE3 the header_hex and confirm it equals pow_hash_le.
python3 -c "
import sys, blake3
h = bytes.fromhex(sys.argv[1])
pow_le = blake3.blake3(blake3.blake3(h).digest()).digest().hex()
print('matches' if pow_le == sys.argv[2] else 'MISMATCH', pow_le)
" "<header_hex>" "<pow_hash_le>"
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

## Performance Considerations

BLAKE3 is significantly faster than SHA256d on modern hardware:

- **CPU:** BLAKE3 is ~5-10x faster than SHA256d per core (due to SIMD)
- **GPU:** BLAKE3 GPU mining kernels are straightforward to implement
- **ASIC:** No BLAKE3 ASICs exist as of 2026; this provides a period of
  CPU/GPU-accessible mining

The b3chain difficulty adjustment algorithm accounts for BLAKE3's speed
by setting appropriate initial difficulty targets.

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
