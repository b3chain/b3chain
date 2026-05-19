# B3Chain Pool Operator Guide

**Audience.** Pool operators already familiar with running Bitcoin
pools who want to add B3Chain support, either as a new pool brand on
B3Chain's testnet (and, when one exists, mainnet) or by extending an
existing multi-coin pool stack.

**Status.** Draft for review by external pool operators. The on-wire
protocol, share-validation contract, and `b3chaind` RPC surface are
stable; this document is the operator-facing handbook for deploying
against them.

**Companion docs.**

- [`doc/stratum.md`](stratum.md) — pool implementer contract (share-validation rules, target maths, default ports).
- [`doc/mining.md`](mining.md) — mining workflow, reference CPU miner, Stratum overview.
- [`contrib/miner/integration-guide.md`](../contrib/miner/integration-guide.md) — companion guide for miner-software authors (the other half of this launch package).
- [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) — normative B3PoW-Scratch v1.1 specification.
- [`doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](whitepaper/B3POW-SCRATCH-WHITEPAPER.md) — design rationale.
- [`contrib/testnet/pool/README.md`](../contrib/testnet/pool/README.md) — the in-tree reference pool stack (MIT-licensed; fork-friendly).

---

## 1. Why this document

B3Chain runs the same block-template / Stratum / payment-processor
architecture as Bitcoin. The only consensus-relevant deviation is the
proof-of-work hash function: **B3PoW-Scratch v1.1** instead of SHA-256d.
Everything else (block identity hash, txids, merkle tree, coinbase
format, address derivation, `submitblock` semantics) is unchanged. A
pool operator who already runs a Bitcoin pool can add B3Chain support
by swapping the share-validation hash call and adding a per-parent
scratchpad cache. This document is the deployment-grade walk-through
for that change.

---

## 2. Architecture summary

A working B3Chain pool needs the same four components as a Bitcoin
pool, plus one B3PoW-Scratch-specific data structure.

```
              +--------------------+
              |   Miners (TCP)     |
              +---------+----------+
                        |
        Stratum V1 (:3333) / Stratum V2 (:3336)
                        |
              +---------v----------+      +-------------------+
              |  Stratum server    |<---->|  Pad cache (1 MiB |
              |  share validator   |      |  × N parents)     |
              +---------+----------+      +-------------------+
                        |
            UNIX socket / IPC (shares + block-found)
                        |
              +---------v-----------+         +-------------------+
              |  Pool daemon        |<------> |  b3chaind         |
              |  block-template     |   RPC   |  (getblocktemplate|
              |  poller, PPLNS,     |  + ZMQ  |   submitblock)    |
              |  block confirmer,   |         +-------------------+
              |  payout job         |
              +---------+-----------+
                        |
              +---------v----------+
              |  Accounting DB     |
              |  (PostgreSQL)      |
              +--------------------+
                        |
              +---------v----------+
              |  Web UI / API      |
              |  (per-user stats,  |
              |  payouts, signup)  |
              +--------------------+
```

The "Pad cache" box is the only piece a Bitcoin-pool operator does not
already have. See §5 for the contract.

The reference stack in
[`contrib/testnet/pool/`](../contrib/testnet/pool/) implements all
five boxes as three Node.js services
([`src/stratum/`](../contrib/testnet/pool/src/stratum/),
[`src/pool/`](../contrib/testnet/pool/src/pool/),
[`src/web/`](../contrib/testnet/pool/src/web/)) sharing a Postgres
database.

---

## 3. The reference pool stack

[`contrib/testnet/pool/`](../contrib/testnet/pool/) is the working
pool the project operates at `pool.b3chain.org`. It is MIT-licensed,
Node.js / TypeScript, ~10 kLOC. Components a third-party operator can
re-use:

| Component | Path | Re-use as… |
|---|---|---|
| Stratum V1 server | [`src/stratum/server.ts`](../contrib/testnet/pool/src/stratum/server.ts), [`client.ts`](../contrib/testnet/pool/src/stratum/client.ts), [`job-manager.ts`](../contrib/testnet/pool/src/stratum/job-manager.ts) | drop-in V1 server, or reference for an integration into your own stack |
| Stratum V2 (mining server, TP, JD, V1↔V2 translator) | [`src/sv2/`](../contrib/testnet/pool/src/sv2/) | reference for SV2 wiring; Noise NX handshake at [`lib/noise.ts`](../contrib/testnet/pool/src/sv2/lib/noise.ts) |
| Share validator | [`src/stratum/share-validator.ts`](../contrib/testnet/pool/src/stratum/share-validator.ts) | the canonical share-validation pipeline; ~150 LOC |
| B3PoW-Scratch port | [`src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts) | pure-TS, byte-identical to the Python reference |
| Pad cache | [`src/lib/pad-cache.ts`](../contrib/testnet/pool/src/lib/pad-cache.ts) | the per-parent cache pattern (see §5) |
| Difficulty maths | [`src/lib/difficulty-math.ts`](../contrib/testnet/pool/src/lib/difficulty-math.ts) | Bitcoin-compatible `nbits` → target, share-difficulty → target |
| Block recorder, PPLNS, payouts | [`src/pool/`](../contrib/testnet/pool/src/pool/) | reference accounting + payout pipeline |
| Web UI / per-user dashboard | [`src/web/`](../contrib/testnet/pool/src/web/) | full Express + Socket.IO live dashboard |
| Reverse-proxy template | [`nginx/`](../contrib/testnet/pool/nginx/) | nginx vhost (TLS, rate-limit, websocket upgrade) |
| systemd units | [`systemd/`](../contrib/testnet/pool/systemd/) | service files for stratum, daemon, web |
| Installer | [`install.sh`](../contrib/testnet/pool/install.sh) | end-to-end seed1-grade install |

External operators should fork rather than depend on this tree
directly; an operator-friendly fork lives (planned) at
`https://github.com/b3chain/b3chain-pool`. Until that fork is
published, vendor the tree by sub-tree or sparse-checkout from
`contrib/testnet/pool/` in the main repo.

---

## 4. Required components for a pool operator

The minimum pool stack:

1. **Stratum server.** Either:
   - The in-tree Stratum V1 server (port 3333 default), and/or
   - The in-tree Stratum V2 mining server (port 3336 default); SV2 is
     strongly preferred for new deployments because of its Noise NX
     channel encryption and lower-bandwidth job framing. See
     [`contrib/testnet/pool/src/sv2/mining/`](../contrib/testnet/pool/src/sv2/mining/).
   - Your own implementation. Wire protocol unchanged from Bitcoin
     except the PoW hash call; see [`doc/stratum.md`](stratum.md).
2. **A `b3chaind` node.** Same binary as a B3Chain full node, run
   with `-server` and the RPC user/password configured (see §7).
   For low-latency `mining.notify` invalidation when a new block
   arrives, expose the ZMQ `hashblock`/`rawblock` endpoints.
3. **A share validator.** Two options, equivalently correct:
   - **Drop-in CLI binary.** A `verify-b3pow` invocation per share is
     simple to integrate but pays a process-launch cost. Suitable for
     low-volume pools or for sanity-checking; reference at
     [`contrib/testing/verify-b3pow.py`](../contrib/testing/verify-b3pow.py).
   - **In-process library call.** The canonical pattern. Use the
     in-tree TS port at
     [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts)
     (Node) or port the algorithm to your stack's language from the
     Python reference at
     [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py).
     For a C / C++ pool, link against the consensus implementation at
     [`src/crypto/b3pow_scratch.cpp`](../src/crypto/b3pow_scratch.cpp).
4. **Payment processor.** B3Chain's coinbase format is identical to
   Bitcoin's; any existing PPS / PPLNS / FPPS pipeline (cgminer-pool,
   ckpool, Yiimp, NOMP, your own) works unchanged. See §8.
5. **Accounting DB.** Reference uses PostgreSQL 16 with schemas at
   [`contrib/testnet/pool/db/`](../contrib/testnet/pool/db/). Any
   relational store you already trust is fine.

Optional but recommended:

6. **A vardiff implementation.** Standard Bitcoin-pool vardiff applies
   unchanged. The reference uses a 30-second retune window targeting
   one share per 10 s per connection
   ([`src/stratum/server.ts`](../contrib/testnet/pool/src/stratum/server.ts)).
7. **A web UI / per-user dashboard.** Optional for low-volume pools;
   the in-tree
   [`src/web/`](../contrib/testnet/pool/src/web/) is a reasonable
   starting point.

---

## 5. Share-validation MANDATORY pattern

This is the operator-side equivalent of §6 of the
[integration guide](../contrib/miner/integration-guide.md). The same
contract applies: `b3pow_scratch` mutates its `pad` argument, and you
must keep a pristine per-parent copy.

### 5.1 Per-parent pad cache (mandatory)

For a pool, the cache is keyed on the **little-endian parent block
hash** that appears in `mining.notify`'s `prev_hash_be_hex` (after byte
reversal). Capacity 4–8 is appropriate: tip plus stale / sibling
parents that might still produce late shares.

**TypeScript (lifted from
[`pad-cache.ts`](../contrib/testnet/pool/src/lib/pad-cache.ts)).**

```typescript
import { initScratchpad, b3powScratch, SCRATCH_BYTES } from "./b3pow-scratch";

class PadCache {
    private readonly capacity: number;
    private readonly map = new Map<string, Uint8Array>();    // hex key -> pristine

    constructor(capacity = 8) { this.capacity = capacity; }

    getFresh(prevHashLE: Uint8Array): Uint8Array {
        const key = Buffer.from(prevHashLE).toString("hex");
        let pristine = this.map.get(key);
        if (!pristine) {
            pristine = initScratchpad(prevHashLE);             // ~10 ms
            this.map.set(key, pristine);
            while (this.map.size > this.capacity) {
                const oldest = this.map.keys().next().value!;
                this.map.delete(oldest);
            }
        } else {
            this.map.delete(key);
            this.map.set(key, pristine);                       // LRU bump
        }
        const copy = new Uint8Array(SCRATCH_BYTES);
        copy.set(pristine, 0);                                 // ~100 us memcpy
        return copy;
    }
}

const cache = new PadCache();

function validateShare(header: Uint8Array, prevLE: Uint8Array,
                       shareTarget: bigint, networkTarget: bigint) {
    const pad = cache.getFresh(prevLE);                        // FRESH per call
    const { powHash } = b3powScratch(header, prevLE, pad);
    const powInt = bigIntFromBytesLE(powHash);
    if (powInt > shareTarget)   return { ok: false, reason: "low-diff" };
    return { ok: true, isBlock: powInt <= networkTarget, powHash };
}
```

**Python (lifted from
[`b3chain-cpuminer.py::PadCache`](../contrib/miner/b3chain-cpuminer.py)).**

```python
import sys, threading
sys.path.insert(0, 'contrib/miner/b3miner-rtl/ref')
from b3pow_ref import b3pow_scratch, init_scratchpad

class PadCache:
    def __init__(self, capacity: int = 8):
        self._capacity = capacity
        self._pristine: dict[bytes, bytes] = {}     # immutable pristine init
        self._order: list[bytes] = []
        self._lock = threading.Lock()

    def get_fresh(self, prev_le: bytes) -> bytearray:
        assert len(prev_le) == 32
        with self._lock:
            p = self._pristine.get(prev_le)
            if p is not None:
                self._order.remove(prev_le); self._order.append(prev_le)
                return bytearray(p)
        # Build outside the lock; init is the slow part (~10 ms).
        p = bytes(init_scratchpad(prev_le))
        with self._lock:
            if prev_le not in self._pristine:
                self._pristine[prev_le] = p
                self._order.append(prev_le)
                while len(self._order) > self._capacity:
                    self._pristine.pop(self._order.pop(0), None)
        return bytearray(p)

cache = PadCache()

def validate_share(header: bytes, prev_le: bytes,
                   share_target: int, network_target: int):
    pad = cache.get_fresh(prev_le)                           # FRESH per call
    pow_le = b3pow_scratch(header, prev_le, pad=pad).pow_hash
    pow_int = int.from_bytes(pow_le, "little")
    if pow_int > share_target:  return {"ok": False, "reason": "low-diff"}
    return {"ok": True, "is_block": pow_int <= network_target,
            "pow_le": pow_le}
```

Without the cache, your validator pays ~10 ms per share — at ten
shares per second per worker × hundreds of workers, the validator
becomes the pool's bottleneck. With the cache, per-share cost is
dominated by the mix loop (a few ms per share in pure TS / Python; a
few hundred µs in tuned C++).

### 5.2 Variable difficulty

Use whatever vardiff you already trust. The reference pool retunes
every 30 s targeting one share per 10 s per connection, with the
single-step ratio clamped to ≤4× and ≥¼×; see
[`contrib/testnet/pool/src/stratum/server.ts`](../contrib/testnet/pool/src/stratum/server.ts)
and
[`contrib/testnet/pool/docs/STRATUM-PROTOCOL.md`](../contrib/testnet/pool/docs/STRATUM-PROTOCOL.md).

The maths is byte-identical to a Bitcoin pool because the diff-1 target
is the same:

```
DIFF1_TARGET = 0x00000000ffff0000_0000000000000000_0000000000000000_0000000000000000
share_target = floor(DIFF1_TARGET / share_difficulty)
```

Canonical reference values:
[`contrib/testnet/pool/src/lib/difficulty-math.ts`](../contrib/testnet/pool/src/lib/difficulty-math.ts)
and the matching Python at the top of
[`b3chain-cpuminer.py`](../contrib/miner/b3chain-cpuminer.py).

### 5.3 Network-target (block-found) check

After the share clears `share_target`, recompute `powInt` against the
network target from the job's `nbits` and, if it also clears
`network_target`, the share is a candidate block:

```typescript
if (powInt <= networkTarget) {
    const blockHex = serializeBlock(header, [coinbase, ...job.txns]);
    const result = await rpc.call("submitblock", [blockHex]);
    if (result === null) {
        recordBlockFound(header, blockHex);
    } else {
        log.warn({ result }, "submitblock rejected");
    }
}
```

`submitblock` returns `null` on success and a string error code on
rejection ("inconclusive", "duplicate", "bad-cb-height", etc.); see
the upstream Bitcoin Core RPC docs for the full list. The reference
recorder is at
[`contrib/testnet/pool/src/pool/block-recorder.ts`](../contrib/testnet/pool/src/pool/block-recorder.ts).

---

## 6. Stratum job templating

`mining.notify` parameters for B3Chain are byte-identical to Bitcoin:

```
[ jobId,
  prev_hash_be_hex,
  coinb1_hex,
  coinb2_hex,
  merkle_branches_be_hex_list,
  "0x" + version_hex,
  "0x" + nbits_hex,
  "0x" + ntime_hex,
  clean_jobs_bool ]
```

Worked example (one full notify the reference pool emits at testnet
tip):

```json
[
  "00012ab",
  "00000000a3f00b1c8f12d6a7e2bb0c8e2f7e3b9c2f1e08a7d3c4b5a6f7e8d9c0b",
  "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff2503",
  "ffffffff020065cd1d000000001976a91488ac",
  ["b3...", "c4..."],
  "0x00000001",
  "0x1d7fffff",
  "0x67a94180",
  true
]
```

Field-by-field:

| Field            | Wire form           | Notes |
|------------------|---------------------|-------|
| `jobId`          | string              | opaque; the server echoes it back in `mining.submit`. |
| `prev_hash_be_hex` | 64-hex chars       | BE display; **reverse to LE before placing inside the header** and before feeding to `b3pow_scratch` (this is the second mandatory step, after pad caching). |
| `coinb1_hex` / `coinb2_hex` | hex          | The coinbase tx pre-split around an `extranonce1 || extranonce2` placeholder; the full coinbase the miner reconstructs is `coinb1 ‖ en1 ‖ en2 ‖ coinb2`. |
| `merkle_branches_be_hex_list` | list of hex | BE display; the miner folds them with the coinbase txid (LE) using `sha256d(left ‖ right)`. |
| `version_hex`    | `"0x"` + 8 hex chars | parsed as `int(s, 16)`. |
| `nbits_hex`      | `"0x"` + 8 hex chars | compact target encoding; decode with the standard Bitcoin formula. |
| `ntime_hex`      | `"0x"` + 8 hex chars | seconds-since-epoch; the miner may roll within the pool-allowed range. |
| `clean_jobs_bool` | true / false       | `true` invalidates older jobs; workers MUST abandon stale jobs immediately. |

The full schema is also documented at
[`contrib/testnet/pool/docs/STRATUM-PROTOCOL.md`](../contrib/testnet/pool/docs/STRATUM-PROTOCOL.md).

The reference Stratum-V1 server keeps the wire shape byte-identical to
upstream pool implementations so existing Bitcoin-pool client code can
talk to it unchanged except for the PoW hash function.

---

## 7. `b3chaind` connection

Run a dedicated `b3chaind` for the pool. Suggested service template
(testnet shown; swap `-chain=test` for mainnet when one ships):

```ini
# /etc/systemd/system/b3chaind-pool.service (example)
[Unit]
Description=B3Chain Core daemon (pool backend)
After=network-online.target

[Service]
ExecStart=/usr/local/bin/b3chaind \
    -chain=test \
    -conf=/etc/b3chain/b3chain.conf \
    -datadir=/var/lib/b3chain/.b3chain \
    -server=1 \
    -txindex=1 \
    -rpcbind=127.0.0.1:18534 \
    -rpcallowip=127.0.0.1 \
    -zmqpubhashblock=tcp://127.0.0.1:28332 \
    -zmqpubrawblock=tcp://127.0.0.1:28333
Restart=on-failure
User=b3chain
Group=b3chain

[Install]
WantedBy=multi-user.target
```

Required `b3chain.conf` entries:

```ini
rpcuser=b3chain
rpcpassword=...                        # or use the .cookie file
rpcwhitelist=b3chain:getblocktemplate,submitblock,getrawmempool,getmempoolinfo,gettxout,validateaddress,getblockchaininfo,getblock,getblockhash
zmqpubhashblock=tcp://127.0.0.1:28332  # low-latency tip change push
zmqpubrawblock=tcp://127.0.0.1:28333   # full-block push (optional)
```

The `rpcwhitelist` line is critical — anything not on the list is
denied, even with valid auth. The set above is the minimum the
reference pool uses; if you add features (e.g. on-chain payouts via
`sendtoaddress` or PSBT signing in the same daemon), add the matching
RPC names to the whitelist.

ZMQ is optional but strongly recommended. Without it, the pool daemon
polls `getblocktemplate` on a timer (default 2 s in the reference
stack) and loses 1–2 s of mining time on every new block. With ZMQ,
the daemon subscribes to `hashblock` and rebuilds the template within
~10 ms of a new tip.

Default ports (from `chainparams.cpp` and the
[`stratum.md`](stratum.md) table):

| Network | P2P    | RPC    |
|---------|--------|--------|
| Mainnet | 8533   | 8534   |
| Testnet | 18533  | 18534  |
| Regtest | 18544  | 18545  |

---

## 8. Payment processing

B3Chain's coinbase format is byte-identical to Bitcoin's: standard
Bitcoin script, same compact-size encoding, same witness commitment in
the coinbase output for segwit blocks. Any existing PPS / PPLNS / FPPS
pipeline you trust for Bitcoin works on B3Chain unchanged — the
on-chain payouts use `sendtoaddress` / PSBT / coinjoin-style
batched-payout patterns identical to Bitcoin.

### 8.1 Reward scheme

The reference pool runs **PPLNS over the last 4 032 weighted shares**
(see
[`contrib/testnet/pool/docs/PPLNS.md`](../contrib/testnet/pool/docs/PPLNS.md)
for the worked example). Pool fee is 1 %, minimum payout 1.0 B3C.
External pools should pick whatever reward scheme they prefer; the
in-tree implementation is one valid choice, not a constraint.

### 8.2 Address formats

| Network  | HRP    | Example                                  |
|----------|--------|------------------------------------------|
| Mainnet  | `b3`   | `b31q…` (bech32 / bech32m, when launched) |
| Testnet  | `tb3`  | `tb31q…` (bech32 / bech32m)              |
| Regtest  | `b3rt` | `b3rt1q…`                                |

All other Bitcoin script types (P2PKH, P2SH, P2WPKH, P2WSH, P2TR) are
supported with the same opcodes; only the bech32 HRP differs.
Validating an address before payout is one RPC call:

```
b3chain-cli validateaddress tb31q...
```

The reference web signup uses `validateaddress` on every payout address
the user enters; see
[`contrib/testnet/pool/src/lib/address.ts`](../contrib/testnet/pool/src/lib/address.ts)
and
[`contrib/testnet/pool/src/web/`](../contrib/testnet/pool/src/web/).

### 8.3 Block confirmation gate

Block-found shares should be held pending until the block has the
configured number of confirmations (the reference pool uses 100, the
same as Bitcoin coinbase maturity for safety against deep reorgs).
The block confirmer
([`src/pool/block-confirmer.ts`](../contrib/testnet/pool/src/pool/block-confirmer.ts))
polls `getblock` per pending block on a 30 s timer; treat blocks that
disappear from the chain (reorg) as forfeit.

---

## 9. Stratum V2 specifics

If your stack supports SV2, B3Chain works with it: the message types
in the upstream SV2 spec
(`SetupConnection`, `OpenStandardMiningChannel`,
`NewMiningJob`/`NewExtendedMiningJob`, `SubmitSharesStandard`,
`SubmitSharesError`) are unchanged, and the only B3Chain difference is
the PoW function applied to the assembled header inside
`SubmitSharesStandard`.

The reference SV2 implementation lives at
[`contrib/testnet/pool/src/sv2/`](../contrib/testnet/pool/src/sv2/):

- Mining server (port 3336 default):
  [`src/sv2/mining/`](../contrib/testnet/pool/src/sv2/mining/)
- Template Provider:
  [`src/sv2/tp/`](../contrib/testnet/pool/src/sv2/tp/)
- Job Declaration server (optional, opt-in):
  [`src/sv2/jd/`](../contrib/testnet/pool/src/sv2/jd/)
- V1↔V2 translator (port 3337 default):
  [`src/sv2/translator/`](../contrib/testnet/pool/src/sv2/translator/)
- Noise NX handshake + transport:
  [`src/sv2/lib/noise.ts`](../contrib/testnet/pool/src/sv2/lib/noise.ts)

### 9.1 Noise NX handshake — static keys

SV2's Noise NX (`Noise_NX_25519_ChaChaPoly_BLAKE2s`) authenticates the
responder (the pool) via an X25519 static key wrapped in a signed
certificate envelope. The initiator (the miner) does **not** need a
long-lived static identity; software miners typically supply an
ephemeral key on every connection, and FPGA miners (B3Miner-1) load a
static key from their ATECC608B secure element at first boot.

Operationally:

- Long-lived **authority key** (Ed25519) signs the pool's per-pool
  static cert. Generated once with
  `tsx src/cli/sv2-keys.ts authority`. Keep it offline.
- Per-pool **static X25519 key** is what miners see during the
  handshake. Generated with `tsx src/cli/sv2-keys.ts static`. Bound to
  a 90-day signed certificate (`B3POOL_SV2_CERT_VALIDITY_DAYS=90` by
  default).
- Both key files and the cert file are referenced from `pool.env`
  (see §11). Rotate the static key when the cert expires; rotate the
  authority key only on key compromise.

A pool that wants to support both hardware (static-key) and software
(ephemeral-key) miners has to accept ephemeral public keys without
checking them against a registry. The reference implementation does
exactly that — workers are authenticated at the application layer
(Stratum username/password or SV2 channel-open token), not at the
Noise layer.

---

## 10. Operational considerations

### 10.1 Monitoring

The minimum useful set of pool-level metrics:

| Metric                                | Source / how to compute |
|---------------------------------------|--------------------------|
| Block-found rate (24 h, 7 d)          | `count(*) from blocks where confirmed_at > now() - interval '24h'` |
| Network difficulty / pool hashrate    | `getblockchaininfo`'s `difficulty`; pool hashrate = sum of per-worker estimated hashrate from vardiff |
| Share-rejection rate (% per minute)   | from share-validator outcomes (reasons: `stale`, `duplicate`, `low-diff`, `invalid`) |
| Worker count + per-user shares/minute | from share-writer rows |
| `b3chaind` lag (block height vs chain.com / seed peers) | `getblockcount` vs a known reference |
| Stratum connection count + churn      | TCP-accept rate, TCP-close rate, connection age histogram |
| Pad-cache hit rate                    | the reference `PadCache.stats()` returns `{size, hits, misses, evictions}`; emit at 1 Hz |

The reference stack exposes `/metrics` (Prometheus format) from the
web service; see
[`contrib/testnet/pool/docs/OPERATOR-RUNBOOK.md`](../contrib/testnet/pool/docs/OPERATOR-RUNBOOK.md).

### 10.2 Alerting thresholds

Suggested baseline (tune to your pool's variance):

| Condition                                              | Severity |
|--------------------------------------------------------|----------|
| `blocks_found_24h == 0 && expected_24h > 0`            | page     |
| Share-rejection rate > 10 % for 5 minutes              | page     |
| Pad-cache miss rate > 50 % sustained > 5 min           | warn (likely cache too small or thrashing on reorg) |
| `b3chaind` ahead-of-tip lag > 60 s vs reference peer  | warn     |
| Stratum accept rate ≫ steady-state for 5 min          | warn (possible DDoS / mis-config push from a miner) |
| Faucet drain rate > 2× steady-state                    | warn (if you also run a testnet faucet) |
| Disk free < 10 % on the accounting DB host             | page     |

### 10.3 Backups

Two things matter and they are independent:

- **Accounting DB.** Nightly `pg_dump` of the full pool DB, plus
  point-in-time WAL archiving for hot recovery. The reference uses
  Postgres 16 and the standard `pg_basebackup` + WAL archive.
- **Per-payout CSV export.** On every payout job completion, write a
  CSV of `(user_id, address, amount_satoshi, txid)` rows to a
  rotated file on disk and to off-site object storage. This is the
  forensics fallback if the DB is ever corrupted: every payout the
  pool has ever made is reconstructible from the CSV trail without
  the DB.

The reference payout job at
[`src/pool/payout-job.ts`](../contrib/testnet/pool/src/pool/payout-job.ts)
writes this CSV after each successful batch.

---

## 11. Anti-pool-hijack and operational security

The minimum bar for an internet-facing pool:

- **TLS on Stratum V1.** Run `stratum+ssl://…:3334` alongside plain
  `stratum+tcp://…:3333`. The reference nginx config terminates TLS
  in front of the Stratum server; see
  [`contrib/testnet/pool/nginx/`](../contrib/testnet/pool/nginx/).
- **Noise NX on Stratum V2.** Built into SV2 by spec — the
  responder's static key + signed cert is the authentication. Make
  sure your static-key file is `chmod 600` and owned by the pool
  service user.
- **Rotating worker passwords (optional).** Worker passwords are
  ignored by the reference pool today (authentication is per-user via
  the web UI's signup + 2FA), but if you choose to enforce them,
  rotate at least every 90 days and never log them.
- **Rate-limit at the load balancer.** Cap new Stratum connections
  per source IP. The reference nginx config caps to 4 connections /
  IP / second with a burst of 16. Without this, a single attacker can
  exhaust the worker socket budget.
- **Separate identities for the daemon and the wallet.** The pool
  daemon needs `getblocktemplate` + `submitblock`; it does **not**
  need wallet write access for share validation. Run the payout
  wallet under a separate user (and ideally a separate daemon) and
  whitelist only the wallet RPCs it needs (`getbalance`,
  `sendtoaddress`, `listunspent`, `signrawtransactionwithwallet`).
- **`b3chaind` RPC bind to `127.0.0.1` only.** Never expose the RPC
  to the internet. The `rpcwhitelist` in §7 is the second line of
  defence, not the first.
- **2FA on the web UI's admin role.** The reference pool ships
  TOTP-based 2FA (otplib) on signup and on admin login; treat any
  admin login that bypasses 2FA as a compromise.

A more detailed pre-production checklist (TLS rotation, key
provenance, audit-log retention) is in
[`contrib/testnet/pool/docs/OPERATOR-RUNBOOK.md`](../contrib/testnet/pool/docs/OPERATOR-RUNBOOK.md).

---

## 12. Pool branding clarity

`pool.b3chain.org:3333` is the **project's reference testnet pool**.
It exists so the wider community has a known-good endpoint to point
miners at while the network bootstraps; it is not the "official"
pool, and the long-run health of B3Chain depends on **multiple
independent pool operators**.

External pools are expected and welcome. Practical asks:

- **Pick a different brand.** Domain, name, UI styling. The MIT
  license on the reference stack lets you re-skin freely; please do.
- **Re-skin, don't just rehost.** Forking
  [`contrib/testnet/pool/`](../contrib/testnet/pool/) and changing
  the colour scheme is enough; copy-pasting `pool.b3chain.org`'s
  branding is not.
- **List yourselves.** When you launch, open a PR adding your pool to
  a public list at `doc/community-pools.md` (forthcoming). The
  project will maintain the list neutrally — ordering is by launch
  date, and pools that fail to mine a block in 30 days get marked
  inactive.
- **Honour the project's no-coinbase-tax norm.** The reference
  coinbase output goes to the pool's payout address (1 % default
  fee). No additional non-payout outputs from the coinbase. If you
  ever need to add one (compliance, accounting), publish the change
  in advance so miners can opt out.

The reference pool's source license is MIT, per
[`contrib/testnet/pool/package.json`](../contrib/testnet/pool/package.json).
Fork freely; attribution is appreciated, not required.

---

## 13. Sample pool config

The reference pool reads `/etc/b3chain-pool/pool.env` (the in-tree
template is [`contrib/testnet/pool/.env.example`](../contrib/testnet/pool/.env.example);
a minimal operator-ready version follows). Place this at
`/etc/b3chain-pool/pool.env` (mode `0640`, owner `b3chain-pool:b3chain`).

```bash
# B3Chain pool — operator-side configuration.
# Copy to /etc/b3chain-pool/pool.env, fill in real values.

# ---- b3chaind RPC ----
B3POOL_RPC_HOST=127.0.0.1
B3POOL_RPC_PORT=18534                            # 8534 mainnet, 18545 regtest
B3POOL_RPC_USER=b3chain
B3POOL_RPC_PASSWORD_FILE=/etc/b3chain/rpcpassword
B3POOL_PAYOUT_WALLET=pool-payouts
B3POOL_PAYOUT_ADDRESS=tb31q...                   # generated once from pool-payouts wallet
B3POOL_NETWORK=testnet                           # testnet | mainnet | regtest

# ---- PostgreSQL ----
B3POOL_DB_URL=postgres://b3chain_pool:CHANGE_ME@127.0.0.1:5432/b3chain_pool

# ---- Stratum V1 ----
B3POOL_STRATUM_BIND=0.0.0.0
B3POOL_STRATUM_PORT=3333
B3POOL_STRATUM_DEFAULT_DIFF=1024
B3POOL_STRATUM_VARDIFF_TARGET_S=10               # target one share every N s per worker
B3POOL_STRATUM_VARDIFF_RETUNE_S=30
B3POOL_FEE_PERCENT=1.0                           # pool fee, % of block subsidy

# ---- Pool daemon ----
B3POOL_TEMPLATE_POLL_MS=2000                     # ZMQ subscribes preferred; this is the fallback poll
B3POOL_PAYOUT_INTERVAL_MS=3600000                # 1 h
B3POOL_BLOCK_CONFIRMATIONS=100                   # match Bitcoin coinbase maturity
B3POOL_PPLNS_N_SHARES=4032                       # PPLNS window (weighted shares)
B3POOL_SHARE_SOCKET=/run/b3chain-pool/share.sock # IPC between stratum + daemon

# ---- Web UI ----
B3POOL_WEB_BIND=127.0.0.1
B3POOL_WEB_PORT=5100
B3POOL_BASE_URL=https://your-pool.example.org
B3POOL_COOKIE_SECRET=...                         # openssl rand -hex 32
B3POOL_SESSION_HOURS=168

# ---- SMTP (signup / 2FA emails) ----
B3POOL_SMTP_HOST=127.0.0.1
B3POOL_SMTP_PORT=25
B3POOL_SMTP_FROM=YourPool <noreply@your-pool.example.org>

# ---- Stratum V2 (opt-in) ----
B3POOL_SV2_ENABLE=true
B3POOL_SV2_BIND=0.0.0.0
B3POOL_SV2_PORT=3336
B3POOL_SV2_AUTHORITY_KEY_FILE=/etc/b3chain-pool/sv2-authority.key
B3POOL_SV2_STATIC_KEY_FILE=/etc/b3chain-pool/sv2-static.key
B3POOL_SV2_CERT_FILE=/etc/b3chain-pool/sv2-cert.bin
B3POOL_SV2_CERT_VALIDITY_DAYS=90

# ---- Logging ----
B3POOL_LOG_LEVEL=info
```

Generate the SV2 keys (one-time):

```bash
cd /path/to/your-pool-fork
# Reads the same key/cert paths from pool.env (B3POOL_SV2_AUTHORITY_KEY_FILE,
# B3POOL_SV2_STATIC_KEY_FILE, B3POOL_SV2_CERT_FILE) and creates whichever
# files are missing. Re-running after the cert expires issues a fresh cert
# bound to the existing static key.
npm run sv2-keys
chmod 600 /etc/b3chain-pool/sv2-*.key /etc/b3chain-pool/sv2-cert.bin
```

For an end-to-end install runbook (Postgres, Postfix, nginx, systemd,
TLS, DKIM), see
[`contrib/testnet/pool/docs/DEPLOYMENT.md`](../contrib/testnet/pool/docs/DEPLOYMENT.md).

---

## 14. Issue reporting and contact

- **GitHub issues:** <https://github.com/b3chain/b3chain/issues> — tag
  `pool-operator`. Include your pool stack's version, the specific
  service (`stratum`, `daemon`, `web`), and a minimal reproducer
  where possible. Pool-specific issues that touch consensus (e.g. a
  block your pool found that `submitblock` rejected) should attach
  the full block hex.
- **Email:** `dev@b3chain.org` — for sensitive disclosures.
- **Discord / Matrix:** planned; channel addresses will be published
  on <https://b3chain.org> when launched. Until then GitHub is the
  canonical channel.
- **Security disclosures:** [`SECURITY.md`](../SECURITY.md) is the
  canonical contact. Please follow the responsible-disclosure window
  before public posts; the project values your time and we will
  respond within one working day to acknowledged reports.

---

## 15. Document version

| Version | Date       | Notes                                       |
|---------|------------|---------------------------------------------|
| 0.1     | 2026-05-19 | Initial draft, Phase 3.2 launch deliverable |

Last updated: 2026-05-19 (`SPEC_VERSION = 0x00010101`).
