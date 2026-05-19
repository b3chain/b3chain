# B3Chain Testnet Runbook

This is the public, hands-on guide for the **B3Chain public testnet**. It
covers everything an outside operator needs to:

1. [Point an existing wallet at testnet](#3-point-a-wallet-at-testnet)
2. [Run a full node](#2-run-a-full-node)
3. [Get free test coins from the faucet](#4-get-test-coins-from-the-faucet)
4. [Mine with the reference CPU miner](#5-mine-with-the-reference-cpu-miner)
5. [Mine via Stratum on the public pool](#6-mine-via-stratum-on-the-public-pool)
6. [Mine with a B3Miner-1 FPGA card](#7-mine-with-a-b3miner-1-fpga-card)
7. [Watch the chain in the explorer](#8-block-explorer)
8. [Read the live status JSON](#9-live-status-monitor)
9. [Troubleshoot](#10-troubleshooting)
10. [Nuke and retry](#11-how-to-nuke-and-retry)
11. [Talk to us](#12-talk-to-us)

Test B3C (`tB3C`) has **no monetary value**. The testnet exists to
soak-test consensus rules and the B3PoW-Scratch v1.1 PoW pipeline before
mainnet launch. The chain may be reset without notice if a critical bug
is found.

---

## 1. Overview

The B3Chain testnet is the small, operator-run network that fronts
[`b3chain.org/testnet.html`](https://b3chain.org/testnet.html). At
bootstrap (Phase 8a) it runs on three seed hosts:

| Role | Hostname / IP | What runs there |
|---|---|---|
| `seed1` | `166.88.4.250` / `seed1.b3chain.org` | `b3chaind -chain=test`, the public Stratum pool (`pool.b3chain.org`), the faucet (`faucet.b3chain.org`), the explorer (`explorer.b3chain.org`), and the status monitor that feeds [`/testnet-status.json`](https://b3chain.org/testnet-status.json) |
| `seed2` | `151.158.1.22` | `b3chaind -chain=test` only — additional P2P seed, no pool/faucet/explorer |
| `seed3` | `151.158.1.60` | `b3chaind -chain=test` only — additional P2P seed, no pool/faucet/explorer |

The DNS seed `testnet-seed.b3chain.org` is a round-robin A record over
all three seed IPs, so a fresh `b3chaind -chain=test` finds peers
without any config. The fixed-seed list compiled into the binary
(`contrib/seeds/nodes_test.txt`) is the fallback for clients that
cannot reach DNS.

The PoW algorithm is **B3PoW-Scratch v1.1** — a memory-hard,
BLAKE3-based, 1 MiB-scratchpad PoW. Everything mining-adjacent must
agree byte-for-byte on this algorithm; see
[`doc/stratum.md`](stratum.md) (the implementer contract),
[`doc/mining.md`](mining.md) (RPC + reference miner workflow), and
[`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md)
(the normative spec) for the byte-level details. This runbook stays at
the operator level and refers you back to those documents when you need
them.

---

## 2. Network parameters

Confirmed against
[`src/kernel/chainparams.cpp`](../src/kernel/chainparams.cpp)
(`CTestNetParams`).

| Field | Value |
|---|---|
| Chain name (CLI: `-chain=`) | `test` |
| Magic bytes (`pchMessageStart`) | `b3 c1 02 0e` |
| P2P port (default) | **`18533`** |
| RPC port (default) | `18534` |
| Stratum (pool) | **`stratum+tcp://pool.b3chain.org:3333`** |
| Bech32 HRP | `tb3` |
| Base58 PUBKEY prefix | `0x6f` (`m` / `n`) |
| Base58 SCRIPT prefix | `0xc4` (`2`) |
| BIP44 `coin_type` | `1` (standard testnet) |
| Target block interval | 600 s (10 min) |
| Difficulty algorithm | LWMA-3 (M-3, M-4) |
| Reorg-depth cap | 200 blocks |
| Verifier budget | 50 ms per header |
| Cache depth | 8 (5 LRU + 3 pinned) |
| Early-difficulty-guard height | 10 000 blocks |
| Subsidy halving interval | 210 000 blocks |
| Genesis hash | `4b3f758b306086eca0a95c68020ab74cb87c652b1788780fa3235306bb3d4006` |
| Genesis merkle root | `a3e989c3afe53b750b3a668b7eef73109961252ace3470a0b50065195adc1e4f` |
| DNS seed | `testnet-seed.b3chain.org.` |

Mainnet uses different magic (`b3 c0 01 0d`), different ports
(`8533` / `8534`), and the `b3` Bech32 HRP. The two networks cannot mix.

---

## 3. Point a wallet at testnet

Any wallet built from the B3Chain source on `b3chain-main` (or a
released `v0.1.x-testnet` tag) speaks the testnet protocol when started
with `-chain=test`.

### CLI wallet (bundled `b3chain-cli` / `b3chaind`)

```bash
b3chaind -chain=test -daemon
b3chain-cli -chain=test getnewaddress "" bech32
# returns tb3...
```

The wallet stores its data under `~/.b3chain/testnet3/wallets/`. If you
want a non-default datadir, pass `-datadir=/path/to/dir` to every
invocation.

### External wallets

Wallets that accept BIP44 `coin_type=1` (the standard testnet slot)
will work as long as you tell them:

- P2P port: `18533`
- Bech32 HRP: `tb3`
- DNS seed or fixed peer: `testnet-seed.b3chain.org`

A Sparrow / Electrum-style server URL is **not** provided at bootstrap;
the public-facing wallet path is "run your own node, point your wallet
at it over RPC / ZMQ". Wallets that expect a public Electrum-style
backend will not work until Phase 2.4's `electrs` deployment lands.

---

## 4. Run a full node

### 4.1 Quickest path

```bash
b3chaind -chain=test
```

That is enough. The DNS seed brings in peers, the chain syncs, and
RPC binds on `127.0.0.1:18534`.

### 4.2 Recommended `b3chain.conf`

Put this in `~/.b3chain/b3chain.conf` (or pass `-conf=/path/to.conf`):

```ini
chain=test

# --- RPC ---
server=1
rpcuser=b3chain
rpcpassword=CHANGE_ME_TO_A_LONG_RANDOM_STRING
rpcbind=127.0.0.1
rpcallowip=127.0.0.1

# --- P2P ---
listen=1
# Belt-and-braces: add the three operator-run seeds explicitly in case
# DNS is broken on your network. Round-robin DNS already resolves to
# these IPs, so this is purely a fallback.
addnode=166.88.4.250:18533
addnode=151.158.1.22:18533
addnode=151.158.1.60:18533

# --- Logging ---
debug=net
debug=mempool
```

Start the daemon:

```bash
b3chaind -conf=$HOME/.b3chain/b3chain.conf -daemon
```

### 4.3 Verify your node is on the right chain

```bash
b3chain-cli -chain=test getblockchaininfo  | head -n 20
b3chain-cli -chain=test getnetworkinfo    | head -n 10
```

- `"chain": "test"`
- `"blocks":` should be at least within a few hundred of the height
  reported by [`/testnet-status.json`](https://b3chain.org/testnet-status.json)
  once your node has caught up.
- `getnetworkinfo` should show 3+ inbound or outbound connections.

If `chain` says anything other than `test`, you started the wrong
binary or forgot `-chain=test`. Stop the daemon and start it again with
the correct flag.

---

## 5. Get test coins from the faucet

### 5.1 Web UI

Open [`https://faucet.b3chain.org`](https://faucet.b3chain.org), paste a
`tb3...` address, and submit.

- **Amount per request:** `0.5` tB3C
- **Cooldown:** 24 hours per IP **and** per destination address
- **Source:** [`contrib/testnet/faucet/app.py`](../contrib/testnet/faucet/app.py)
  (Flask + sqlite rate-limit DB; runs under systemd on seed1)

### 5.2 HTTP API

```bash
# JSON status (faucet balance, node tip, cooldown info)
curl -s https://faucet.b3chain.org/status | jq

# Request coins (form-encoded POST, same as the web UI button)
curl -s -X POST https://faucet.b3chain.org/request \
     -d "address=tb3qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

The HTML response embeds the `txid` on success and a human-readable
error on failure. Rate-limit violations return HTTP `429` with a
`Cooldown active. Try again in N h M m.` message.

### 5.3 Drained faucet

If `https://faucet.b3chain.org/status` reports
`"faucet_balance": "0.00000000"`, the operator's top-up cron has not
fired yet. The faucet is refilled at most once per hour from the
operator's miner wallet (see
[`contrib/testnet/faucet/topup.sh`](../contrib/testnet/faucet/topup.sh)).
Open a GitHub issue if it stays drained for more than 6 hours — that is
an outage, not normal operation.

---

## 6. Mine with the reference CPU miner

The reference CPU miner is
[`contrib/miner/b3chain-cpuminer.py`](../contrib/miner/b3chain-cpuminer.py).
It supports both solo mining (against your own node's
`getblocktemplate` RPC) and pool mining (Stratum V1 against
`pool.b3chain.org:3333`). It always uses the canonical
**B3PoW-Scratch v1.1** PoW unless you pass `--legacy-blake3d`, in which
case shares **will be rejected** by the live pool.

### 6.1 Solo mining (your own node)

```bash
pip3 install blake3   # required by the B3PoW-Scratch Python reference

b3chain-cli -chain=test getnewaddress "" bech32
# tb3qXXXXXX

python3 contrib/miner/b3chain-cpuminer.py \
    --rpcconnect=127.0.0.1 \
    --rpcport=18534 \
    --rpcuser=b3chain \
    --rpcpassword=YOUR_RPC_PASSWORD \
    --coinbaseaddr=tb3qXXXXXX
```

### 6.2 Expected hashrate (and why it is slow on purpose)

| Hardware                       | Approx. hashrate           |
|--------------------------------|----------------------------|
| 1 core, pure-Python reference  | a handful of H/s           |
| 1 core, C++ consensus impl     | a few hundred H/s          |
| Modern CPU (8 cores, C++)      | low-thousand H/s           |
| B3Miner-1 FPGA (XCKU5P)        | target on the order of MH/s |

B3PoW-Scratch is **memory-bound by design** (1 MiB scratchpad per
hash, 8-lane RMW, 2 048 sequential iterations). The pure-Python
reference is intentionally a correctness oracle, not a competitive
miner. Use it for solo mining on regtest, for cross-checking pool
behaviour at a known-slow rate, or as the worked example when
implementing a fast miner. For serious mining, use a B3Miner-1 card
(§7) or another B3PoW-Scratch-aware miner.

The "early-difficulty-guard" regime on testnet (the first 10 000
blocks) clamps difficulty low enough that a single CPU thread can
produce blocks at roughly the 10-minute target.

---

## 7. Mine via Stratum on the public pool

Pool URL: **`stratum+tcp://pool.b3chain.org:3333`**

The reference pool (see
[`contrib/testnet/pool/`](../contrib/testnet/pool/)) speaks Stratum V1
and validates every share against the canonical B3PoW-Scratch v1.1
algorithm exactly the way `b3chaind` does
([`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts)).

### 7.1 Worker name + password convention

The pool follows the conventional `<email>.<workerName>` Stratum V1
username scheme:

| Username pattern                  | Meaning                                  |
|-----------------------------------|------------------------------------------|
| `alice@example.com.cpu1`          | Verified account `alice@example.com`, worker `cpu1` |
| `tb3qxxx.fpga0`                   | Anonymous: address-only username, worker `fpga0` |
| `anything-without-a-dot`          | Anonymous: no per-user accounting       |

The password field is **ignored**; pass `x` as a placeholder. Per-user
accounting (per-worker hashrate dashboard, PPLNS credit, payouts to a
verified payout address) requires signing up at
[`https://pool.b3chain.org`](https://pool.b3chain.org). Anonymous
miners' shares contribute to the pool's hashrate but receive no PPLNS
credit and no payout.

### 7.2 Difficulty and share format

- Starting share difficulty: **`1024`** (`B3POOL_STRATUM_DEFAULT_DIFF`).
- Vardiff target: one share every **`10 s`** per worker
  (`B3POOL_STRATUM_VARDIFF_TARGET_S`). The server retunes every 30 s.
- `mining.suggest_difficulty` is honoured and clamped to the configured
  `[minDiff, maxDiff]`.
- Shares submit a 4-byte `extranonce1` (assigned by the server on
  `mining.subscribe`) plus a 4-byte `extranonce2` rolled by the miner.
- The pool validates each share against (a) the connection's current
  share target, and (b) the active block template's network target;
  a share that meets the network target becomes a block.
- The wire protocol is plain Stratum V1 with the messages documented in
  [`contrib/testnet/pool/docs/STRATUM-PROTOCOL.md`](../contrib/testnet/pool/docs/STRATUM-PROTOCOL.md).
  Stratum V2 is provisioned in the same repo but is **opt-in** at the
  moment (`B3POOL_SV2_ENABLE=false` by default) — see
  [`doc/stratum.md`](stratum.md) for the implementer contract.

### 7.3 Payout policy

- **Reward scheme:** PPLNS over the last `4032` weighted shares
  (`B3POOL_PPLNS_N_SHARES`).
- **Pool fee:** `1%`.
- **Block confirmations before payout credit:** `100`
  (`B3POOL_BLOCK_CONFIRMATIONS`); blocks that reorg before then are
  flagged `is_orphan` and credited shares are unwound.
- **Default minimum payout:** `1.0` tB3C, auto-payout once per hour
  (`B3POOL_PAYOUT_INTERVAL_MS`).
- Detailed worked example: [`contrib/testnet/pool/docs/PPLNS.md`](../contrib/testnet/pool/docs/PPLNS.md).

### 7.4 Pointing the reference CPU miner at the pool

```bash
python3 contrib/miner/b3chain-cpuminer.py \
    --stratum stratum+tcp://pool.b3chain.org:3333 \
    --user alice@example.com.cpu1 --pass x \
    --threads 2 \
    --json-log shares.jsonl
```

Every share is printed with byte-level detail (job id, both
extranonces, ntime, nonce, full coinbase tx + txid, merkle root, full
80-byte header, PoW hash LE + BE, block hash, share / network targets,
accepted/rejected status, RTT). `--json-log` writes the same data as
JSONL for later replay. See `--help` for the full flag list and
[`contrib/testnet/pool/docs/STRATUM-PROTOCOL.md`](../contrib/testnet/pool/docs/STRATUM-PROTOCOL.md)
for the protocol-level reference.

---

## 8. Mine with a B3Miner-1 FPGA card

The B3Miner-1 is the reference FPGA mining card for B3PoW-Scratch:
XCKU5P FPGA + ESP32-S3 host + Ethernet. See
[`contrib/miner/b3miner-firmware/README.md`](../contrib/miner/b3miner-firmware/README.md)
for the firmware architecture and
[`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md)
for the normative PoW spec the bitstream implements.

### 8.1 Provisioning a card

1. Flash the firmware:

   ```bash
   cd contrib/miner/b3miner-firmware
   idf.py set-target esp32s3
   idf.py build
   idf.py -p COMx flash monitor
   ```

   Requires ESP-IDF v5.2+.

2. On first boot, the card brings up the web dashboard on its
   DHCP-assigned IP (and on the link-local serial console). Use it to
   configure:

   - Pool URL: `stratum+tcp://pool.b3chain.org:3333`
   - Worker name (Stratum username):
     `<email>.<workerName>` (verified account) or `<tb3...>.<workerName>`
     (anonymous, address-only)
   - Password: `x`

3. Confirm the card is showing as a connected worker at
   [`https://pool.b3chain.org`](https://pool.b3chain.org) under your
   verified account dashboard, and that its hashrate appears in
   [`/testnet-status.json`](https://b3chain.org/testnet-status.json).

### 8.2 Equivalent CLI for headless cards

A B3Miner-1 in production normally provisions itself off NVS, but the
Stratum command it speaks is the same Stratum V1 protocol described in
§7. If you are bringing up a card without the dashboard, the wire
contract is the same `mining.subscribe` → `mining.authorize` →
`mining.notify` → `mining.submit` sequence documented in
[`contrib/testnet/pool/docs/STRATUM-PROTOCOL.md`](../contrib/testnet/pool/docs/STRATUM-PROTOCOL.md).

---

## 9. Block explorer

URL: [`https://explorer.b3chain.org`](https://explorer.b3chain.org)

The explorer is a deployment of
[`janoside/btc-rpc-explorer`](https://github.com/janoside/btc-rpc-explorer)
pointed at the seed1 testnet node, with B3C rebrand patches applied via
[`contrib/testnet/explorer/`](../contrib/testnet/explorer/). It shows:

- Live tip / recent blocks, search by height / hash / address / txid
- Per-address transaction history
- Mempool snapshot
- Per-block coinbase + merkle / wtxid trees
- Network summary (peers, difficulty, hashrate estimate)

### JSON API endpoints (a subset)

`btc-rpc-explorer` exposes its own JSON endpoints; the common ones:

| Endpoint | Returns |
|---|---|
| `https://explorer.b3chain.org/api/blocks` | Recent blocks |
| `https://explorer.b3chain.org/api/block/<height-or-hash>` | One block |
| `https://explorer.b3chain.org/api/tx/<txid>` | One transaction |
| `https://explorer.b3chain.org/api/address/<addr>` | Address history |
| `https://explorer.b3chain.org/api/mempool-summary` | Mempool snapshot |

For consensus-level cross-checks (`getblockchaininfo`,
`getmininginfo`, `getrawmempool`, etc.) run them against your own
`b3chaind -chain=test` node over RPC. Do **not** rely on the explorer
for security-sensitive verification.

---

## 10. Live status monitor

A small Python exporter at
[`contrib/testnet/status-monitor/`](../contrib/testnet/status-monitor/)
runs on seed1 (via cron or systemd-timer; see its README) and writes
`/var/www/b3chain/testnet-status.json`. Nginx serves it as:

[`https://b3chain.org/testnet-status.json`](https://b3chain.org/testnet-status.json)

The website's testnet page polls this JSON every 60 s for the "Live
status" panel.

### Schema

```json
{
  "generated_at": "<ISO8601 UTC>",
  "chain": "test",
  "node": {
    "height": <int>,
    "best_block_hash": "<hex>",
    "best_block_time": <unix ts>,
    "difficulty": <float>,
    "verification_progress": <float 0..1>,
    "peer_count": <int>
  },
  "network": {
    "hashrate_estimate_hps": <float | null>,
    "target_block_interval_s": 600,
    "actual_recent_interval_s": <float | null>
  },
  "pool": {
    "url": "stratum+tcp://pool.b3chain.org:3333",
    "online": <bool>,
    "connected_workers": <int | null>,
    "hashrate_estimate_hps": <float | null>,
    "blocks_found_24h": <int | null>,
    "last_block_height": <int | null>
  },
  "faucet": {
    "online": <bool>,
    "balance_satoshis": <int | null>,
    "address": "<faucet address | null>"
  },
  "recent_blocks": [
    {
      "height": <int>,
      "hash": "<hex>",
      "time": <unix ts>,
      "tx_count": <int>,
      "size_bytes": <int>
    }
  ]
}
```

Fields are `null`-able. If `node.height` is `null` the node RPC was
unreachable when the exporter last ran (the JSON's `generated_at`
timestamp tells you how stale that is). The website renders gracefully
when a field is missing.

A backwards-compatible plain-text snapshot is also published at
[`https://b3chain.org/testnet-status.txt`](https://b3chain.org/testnet-status.txt)
by [`contrib/testnet/monitor/seed-status.sh`](../contrib/testnet/monitor/seed-status.sh).

---

## 11. Troubleshooting

### "Connection refused" / `b3chaind` will not start

- Check `~/.b3chain/debug.log` (or `journalctl -u b3chaind -n 200` if
  you run it under systemd) for the actual reason. The most common
  ones are a stale lockfile from an unclean shutdown
  (`~/.b3chain/testnet3/.lock`) and an already-bound port.
- Confirm `18533` (P2P) and `18534` (RPC) are not in use:
  `ss -tlnp | grep -E '18533|18534'`.

### Node syncs but never lands on the right tip

- Run `b3chain-cli -chain=test getblockchaininfo` and compare
  `bestblockhash` to the value in
  [`/testnet-status.json`](https://b3chain.org/testnet-status.json).
  If they differ once both are at the same height, you may be on a
  fork — restart with `-reindex` and let the longest-chain rule
  resolve it.
- Confirm `chain=test`. A node accidentally started against mainnet
  (`-chain=main`) or signet (`-chain=signet`) will sync **a different
  chain** and never see testnet blocks.

### Stratum: `mining.submit` returns `Share above target`

- Your share's PoW hash is greater than the share target you were
  given by the last `mining.set_difficulty`. Usually means the miner
  is computing PoW against the wrong header serialization, the wrong
  `prev_block_hash` endianness, or with `--legacy-blake3d` set. See
  [`doc/stratum.md`](stratum.md) §2 for the byte-exact contract and
  the worked test vectors.

### Stratum: `Job not found`

- The pool already invalidated the job you submitted against (new
  block template or a `clean_jobs=true` `mining.notify` arrived).
  Drop your in-flight shares and pick up the new job. Vardiff is
  vendor-agnostic — keep your `mining.notify` queue at depth ≥ 2.

### Faucet: `Cooldown active. Try again in N h M m.`

- Per-IP **or** per-address 24 h cooldown is still active. Wait it
  out, or use a different IP **and** a different `tb3...` destination
  address.

### Faucet: `Send failed: <RPC error>` or `Internal error talking to node.`

- The faucet's hot wallet is drained, or the node is down. Check
  [`https://faucet.b3chain.org/status`](https://faucet.b3chain.org/status)
  for the live balance; open a GitHub issue if it stays drained for
  more than 6 hours.

### Explorer is empty / stuck

- The explorer is a non-consensus convenience and may lag the chain
  during heavy reorgs or restarts. Cross-check with your own node's
  `getblockchaininfo`; if your node also agrees the chain has not
  advanced, that is the real story.

---

## 12. How to nuke and retry

If your local state is fouled (wallet corrupted, sync stuck after a
chain reset, etc.), the safe sequence is:

```bash
# 1. Stop the daemon.
b3chain-cli -chain=test stop

# 2. Back up the wallet (testnet coins are valueless, but the address
#    history may matter for debugging). Default location:
cp -a ~/.b3chain/testnet3/wallets ~/b3chain-testnet-wallets.bak

# 3. Wipe the chain state. KEEP wallets/ and b3chain.conf; everything
#    else under testnet3/ is rebuildable from peers.
cd ~/.b3chain/testnet3
rm -rf blocks chainstate indexes peers.dat banlist.dat mempool.dat anchors.dat

# 4. Resync.
b3chaind -chain=test -daemon
```

If you also want a clean wallet, delete the `wallets/` directory in
step 3 — but remember to restore from your backup if you actually
needed the addresses.

A full network-wide reset (operator-triggered, e.g. after a critical
bug) is announced via the testnet status page and the channels in §12;
in that case everyone starts from genesis again.

---

## 13. Talk to us

- **Bug reports / consensus oddities / sync stalls / wallet weirdness:**
  open a GitHub issue at
  [`github.com/b3chain/b3chain/issues`](https://github.com/b3chain/b3chain/issues).
  Include your `b3chaind` version (`getnetworkinfo`), the testnet block
  height, and the last 200 lines of `debug.log` /
  `journalctl -u b3chaind-testnet`.
- **Security disclosure:** `security@b3chain.org`. Please do not file
  security-sensitive issues in public GitHub before contacting us.
- **Real-time chat:** a Discord and a Matrix room are *planned* but
  not yet live; the GitHub issue tracker is the authoritative channel
  until then.
- **Contributions:** see
  [`CONTRIBUTING.md`](../CONTRIBUTING.md) (the test-vector regen
  discipline and the RTL contribution flow are documented there).

Cross-references:

- [`doc/mining.md`](mining.md) — RPC workflow + reference miner usage
- [`doc/stratum.md`](stratum.md) — implementer contract for pools and miners
- [`contrib/miner/b3miner-firmware/README.md`](../contrib/miner/b3miner-firmware/README.md) — B3Miner-1 host firmware
- [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) — normative PoW spec
- [`contrib/testnet/pool/`](../contrib/testnet/pool/) — pool source tree (TS / Node.js)
- [`contrib/testnet/faucet/app.py`](../contrib/testnet/faucet/app.py) — faucet source
- [`contrib/testnet/status-monitor/`](../contrib/testnet/status-monitor/) — live status exporter source
- Website page: [`b3chain.org/testnet.html`](https://b3chain.org/testnet.html)
- Explorer: [`explorer.b3chain.org`](https://explorer.b3chain.org)
- Faucet: [`faucet.b3chain.org`](https://faucet.b3chain.org)
- Status JSON: [`b3chain.org/testnet-status.json`](https://b3chain.org/testnet-status.json)
