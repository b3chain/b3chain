# R-13 Lightning Compatibility — Detailed Expansion

**Status:** draft proposal (not yet ratified into [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md); §9 of this document proposes a roadmap restructure)
**Last updated:** 2026-05-20
**Parent:** [R-13 in `POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md#r-13--lightning-compatibility-statement--reference-channel-demo-on-testnet)
**Companion:** [`POW-PEERS-COMPETITIVE-ANALYSIS.md`](POW-PEERS-COMPETITIVE-ANALYSIS.md) §3.3, §5.5

This document expands the one-paragraph acceptance criterion in
R-13 of the roadmap into an implementation-grade plan: what Lightning
actually requires from a base chain, three viable integration paths
ranked, a four-phase rollout, the chain-params patch sketch, and a
recommendation for how to restructure R-13 in the parent roadmap.

---

## Table of contents

- [§1 Why R-13 is high-leverage](#1-why-r-13-is-high-leverage)
- [§2 What Lightning actually depends on](#2-what-lightning-actually-depends-on)
- [§3 Three implementation paths, ranked](#3-three-implementation-paths-ranked)
- [§4 Phased rollout](#4-phased-rollout)
- [§5 Implementation-level detail: the chain-params patch](#5-implementation-level-detail-the-chain-params-patch)
- [§6 Things that look like risk but aren't](#6-things-that-look-like-risk-but-arent)
- [§7 Things that genuinely are risk](#7-things-that-genuinely-are-risk)
- [§8 How R-13 amplifies the rest of the roadmap](#8-how-r-13-amplifies-the-rest-of-the-roadmap)
- [§9 Recommendation: split R-13 + add R-20 / R-21 / R-22](#9-recommendation-split-r-13--add-r-20--r-21--r-22)

---

## §1 Why R-13 is high-leverage

R-13 is one of two roadmap items (the other is R-11 asset issuance)
whose answer to "what does b3chain do that BTC doesn't?" is
*qualitatively* different from "we have a different PoW algorithm".
Lightning is a credibility multiplier:

- **Listing committees** read "Lightning-compatible, demonstrated on
  testnet" as "the chain is alive and the script semantics actually
  work end-to-end". Static script-parity claims don't move them; a
  closed channel does.
- **Exchanges** that already support Lightning withdrawals for BTC
  (Kraken, Bitfinex, OKX) can extend to b3chain with near-zero
  engineering once an LSP-side LN node exists. That's a tier-1
  deposit/withdrawal UX without any base-layer throughput change.
- **Wallet integration** for Lightning (Phoenix, Breez, Zeus,
  Mutiny) gets us into mobile UX without us building a mobile
  wallet. This is the cheapest path past gap #6 in
  [`POW-PEERS-COMPETITIVE-ANALYSIS.md §1.3`](POW-PEERS-COMPETITIVE-ANALYSIS.md#13-where-we-are-behind).
- **Tooling inheritance proof.** Lightning exercises every
  non-trivial Bitcoin Script and Taproot path simultaneously
  (HTLCs, revocation, multisig, anchor outputs,
  `SIGHASH_SINGLE | SIGHASH_ANYONECANPAY`, `OP_CSV`, `OP_CLTV`,
  MuSig2). If LN works, the entire BTC parity claim is empirically
  validated.

## §2 What Lightning actually depends on

LN is not "Bitcoin Script in general", it's a specific set of
features. The inventory below maps each Lightning-required feature
to its b3chain inheritance status (BTC Core 30.2.0 fork — see
[`README.md`](../../README.md)).

| BOLT layer | Base-chain requirement | b3chain inheritance |
|---|---|---|
| BOLT 2 (funding) | 2-of-2 P2WSH or P2TR multisig; SegWit v0 or v1 | yes — full SegWit + Taproot |
| BOLT 3 (commitment tx) | `OP_CHECKSEQUENCEVERIFY` (BIP112), `OP_CHECKLOCKTIMEVERIFY` (BIP65), `OP_CHECKSIG`, `OP_CHECKSIGVERIFY`, `OP_SIZE`, `OP_HASH160` | yes |
| BOLT 3 (anchor outputs, post-2020) | Static keys + CSV; package relay for CPFP fee-bumping the anchor | yes (package relay shipped in BTC Core 28+; inherited) |
| BOLT 3 (ephemeral anchors, BIP431) | TRUC v3 transactions, 1P1C package relay | yes, conditional on continued upstream cherry-pick discipline (see R-15) |
| BOLT 5 (onchain handling) | RBF, mempool reliability, sane fee estimation | yes |
| BOLT 7 (gossip) | none consensus-level; needs deterministic block heights | yes |
| BOLT 9 (feature bits) | none consensus-level | n/a |
| BOLT 11 (invoices) | none consensus-level; needs deterministic chain hash | yes — genesis hash is the LN `chain_hash` parameter |
| Taproot channels (eltoo precursor, MuSig2) | BIP340 Schnorr, BIP341 Taproot, BIP342 Tapscript | yes |
| Splicing (BOLT-ish, in flight upstream) | RBF + ephemeral anchors | yes |

**Conclusion of the inventory.** There is no consensus-level work
to do. The *engineering* is entirely in LN-client chain-awareness
configuration. This is what makes R-13 a P1 with "low technical
risk" — and what makes the demo so high-value: it proves the
inventory.

## §3 Three implementation paths, ranked

Three Lightning implementations are worth integrating; for each
there are several integration patterns. Six options total but only
three are sensible. Recommended priority order:

### §3.1 Path A — LND with `bitcoind` backend (recommended primary)

LND already supports two backends: `neutrino` (compact block
filters, BIP157/158) and `bitcoind` (full-node JSON-RPC + ZMQ). The
`bitcoind` backend is the closest fit because:

- `b3chaind` is bitcoind-compatible at the RPC layer (BTC Core
  30.2 fork; see
  [`POW-PEERS-COMPETITIVE-ANALYSIS.md §3.10`](POW-PEERS-COMPETITIVE-ANALYSIS.md#310-ecosystem)).
- ZMQ topic names (`rawblock`, `rawtx`, `hashblock`, `hashtx`) are
  inherited unchanged.
- The only LND code change is `chainreg/chainparams.go` to register
  a b3chain network.

**Minimum patch surface in LND** ([`lightningnetwork/lnd`](https://github.com/lightningnetwork/lnd)):

- `chainreg/chainparams.go` — add a `B3ChainParams` struct (network
  magic, genesis hash, default ports, HRP `b3`, SLIP-0044 coin
  type from R-03).
- `chainreg/chainregistry.go` — register `b3chain`, `b3chaintest`,
  and `b3chainregtest` as valid `--chain.active` values.
- `lncfg/chainregistry.go` — validate flags.
- The `btcwallet` dependency needs the same chain params — either
  fork [`btcsuite/btcwallet`](https://github.com/btcsuite/btcwallet)
  and `btcsuite/btcd/chaincfg` to add a `B3ChainNetParams`, or
  contribute upstream behind a `--registernet` flag (BCH-N took
  the upstream-flag route; Litecoin took the fork route).

**Estimated effort.** 3–5 engineer-weeks for a working node, plus
2 weeks for the demo. Most of the time is in `btcsuite/btcd/chaincfg`
patching, not LND itself.

### §3.2 Path B — Core Lightning (CLN) plugin

CLN ([`ElementsProject/lightning`](https://github.com/ElementsProject/lightning))
has a more bitcoind-aligned design and a plugin architecture that
means a fork may not be necessary at all:

- CLN uses `bitcoin-cli` calls under the hood; replacing it with
  `b3chain-cli` is a one-line config (`--bitcoin-cli`).
- The hard-coded chain check is in `bitcoind.c` — specifically the
  genesis hash compare. There is a CLN "test chain" mode that
  bypasses; the production path needs a small patch to accept a
  `chain_hash` parameter at startup, or a chain registration
  similar to LND's.
- BOLT 11 invoices use `chain_hash` from `chain_params` in
  `common/chainparams.c` — that's the single struct to extend.

**Why this is path B and not A.** CLN's user base is smaller than
LND's, so the *demonstration* value is lower per unit of effort.
But the *engineering* is genuinely smaller. If team capacity is the
binding constraint, swap A and B.

### §3.3 Path C — LDK (Lightning Dev Kit)

LDK ([`lightningdevkit/rust-lightning`](https://github.com/lightningdevkit/rust-lightning))
is a library, not a node. It powers Breez SDK, Mutiny, Bitkit, and
Cash App's LN integration. Because it's bitcoin-agnostic-ish by
design (the `ChainSource` and `BroadcasterInterface` traits are
abstractions), porting LDK against b3chain is nearly trivial:

- Implement the `ChainSource` trait against `b3chaind` JSON-RPC.
- Implement the `BroadcasterInterface` trait against `b3chain-cli
  sendrawtransaction`.
- Add `chain_hash` constant (b3chain genesis).
- ~500 lines of Rust glue.

**Why this is path C.** The deliverable is a *library*, not a
public node, so the demo artefact ("a channel was opened and an
HTLC routed") is weaker for listing-committee purposes. But it's
the *fastest* path to mobile-wallet integration (Breez SDK → custom
wallet for b3chain), and it's the *only* path that gets us onto
Mutiny / Bitkit-style browser wallets without their cooperation.
If R-13's success metric is "B3 in a mobile wallet on launch day",
this is the winner.

### §3.4 Recommended sequencing

Path A is the primary deliverable for R-13's acceptance criterion.
Path B is a nice-to-have if capacity allows. Path C unlocks
R-13-adjacent ecosystem moves and is proposed in §9 as its own
roadmap item (R-21).

## §4 Phased rollout

The current single R-13 acceptance criterion in
[`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md) is split below into
four sub-phases. Intermediate, demonstrable wins instead of one
all-or-nothing demo.

### §4.1 Phase 13a — Compatibility statement & gap analysis (~1 week, docs only)

Ship `doc/scaling/LIGHTNING.md` with:

- The §2 inventory table, expanded with per-BIP citations into the
  b3chain consensus source files (so a reviewer can `grep` for
  `OP_CHECKLOCKTIMEVERIFY` in [`src/script/interpreter.cpp`](../../src/script/interpreter.cpp)
  and see it's identical to BTC's).
- A "chain parameters needed by an LN node" table: `chain_hash`,
  genesis block hash, network magic bytes, default ports, BIP44
  coin type (cross-link R-03), HRP (`b3`), `MIN_HTLC_MSAT` policy
  default, `MIN_FUNDING_SATOSHIS` policy default, dust limit
  (546 sats inherited).
- A "test vector" appendix: a deterministically-derived sample
  funding transaction, commitment transaction, HTLC offered
  transaction, and HTLC timeout sweep transaction on b3chain
  testnet. These are *not* live — they're hand-constructed
  reference artefacts so any future LN implementer has a known-
  good byte-exact reference (same discipline as
  [`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json)).

This phase has the highest ROI per token of effort. It's also the
deliverable an exchange or wallet team can use to do their own LN
integration without our active help. §9 proposes promoting this to
its own roadmap item (R-20).

### §4.2 Phase 13b — `btcd` / `btcsuite` chain-params fork (~2 weeks)

Set up `contrib/lightning/btcsuite-b3chain/` with:

- A pinned vendored fork of `btcsuite/btcd/chaincfg` adding
  `B3ChainNetParams`, `B3ChainTestNetParams`,
  `B3ChainRegressionNetParams`.
- A pinned vendored fork of `btcsuite/btcwallet` consuming the
  chain params above.
- CI build that produces a `btcd` binary that thinks b3chain is a
  valid network.
- A `Makefile` target that builds the fork and produces `replace`
  directives for downstream LND/CLN consumers' `go.mod`.

**Fork-vs-upstream-PR decision.** File the upstream PR anyway (so
the option of contributing back stays open) but ship the fork in-tree
so we are not blocked on upstream review. Match what the Litecoin
team did with [`ltcsuite/ltcd`](https://github.com/ltcsuite/ltcd).

### §4.3 Phase 13c — LND patch + dual-node testnet demo (~3 weeks)

Set up `contrib/lightning/lnd-b3chain/`:

- A pinned vendored fork of LND with the `chainreg` patch.
- A `docker-compose.yml` that brings up:
  - 1× `b3chaind` in testnet mode, with `-zmqpubrawblock`,
    `-zmqpubrawtx`, `-blockfilterindex=1`.
  - 2× LND nodes (Alice, Bob) configured against `b3chaind` via
    ZMQ + RPC.
  - 1× `lncli` helper container.
- A `demo-r0/` directory committed with the artefacts the
  acceptance criterion already lists, plus:
  - Channel open tx hex (verified with `b3chain-cli decoderawtransaction`).
  - HTLC commitment tx hex with annotations linking each output to
    BOLT-3 §3.
  - Cooperative close tx hex.
  - Force-close + revocation tx hex (separate run, deliberate
    breach).
  - `lncli describegraph` output showing the channel announced in
    BOLT-7 gossip.
  - `lncli sendpayment` output for 1, 10, 1 000 sat payments
    (three different amounts to exercise small/medium dust-limit
    behaviour).
- A script `demo-r0/replay.sh` that any reviewer can run to
  reproduce the demo from scratch on a fresh machine in <30
  minutes.

### §4.4 Phase 13d — Public testnet LSP-ish node + watchtower (~4 weeks, ops)

Optional but high-impact: stand up one public LND node
`alice.lightning.b3chain.org` peered into the b3chain testnet, with
`--watchtower.active` on, accepting incoming channel requests from
any wallet that has the b3chain chain params. Document the
connection string. This makes the demo not just reproducible but
*live*.

A watchtower demo is particularly valuable because it exercises
BOLT-13 and proves the justice-transaction path works against
b3chain's mempool eviction and RBF policies — which is the same
proof an exchange security review wants. §9 proposes splitting this
out as its own P2 item (R-22).

## §5 Implementation-level detail: the chain-params patch

To make the LND patch concrete, the file `chainreg/b3chain_params.go`
in the LND fork is essentially this sketch (proposed new code in a
fork — not yet authored):

```go
// chainreg/b3chain_params.go (new file in LND fork, sketch)
package chainreg

import (
    "github.com/btcsuite/btcd/chaincfg"
    "github.com/btcsuite/btcd/chaincfg/chainhash"
    "github.com/lightningnetwork/lnd/keychain"
)

var b3chainGenesisHash = chainhash.Hash{
    // little-endian bytes of the b3chain mainnet genesis block hash;
    // populated from src/kernel/chainparams.cpp `consensus.hashGenesisBlock`
    // once mainnet is launched.
}

var b3chainMainNetParams = BitcoinNetParams{
    Params: &chaincfg.Params{
        Name:             "b3chain",
        Net:              0xB3C4A1B3, // arbitrary, must match b3chaind pchMessageStart
        DefaultPort:      "8533",
        Bech32HRPSegwit:  "b3",
        PubKeyHashAddrID: 0x00,  // BTC parity
        ScriptHashAddrID: 0x05,  // BTC parity
        PrivateKeyID:     0x80,  // BTC parity
        HDCoinType:       0,     // placeholder — SLIP-0044 assignment from R-03
        GenesisHash:      &b3chainGenesisHash,
    },
    RPCPort:  "8534",
    CoinType: keychain.CoinTypeBitcoin, // re-purpose; OR introduce CoinTypeB3Chain
}
```

Plus the corresponding `BitcoinChainRegistration{}` entry in
`chainregistry.go` and a `b3chain` case in the `--chain.active`
flag parser.

That's the entire LND-side patch. The downstream `btcd` /
`btcwallet` patches are larger but they're the standard
ltcd-style adaptation — well-trodden ground.

## §6 Things that look like risk but aren't

Common "LN-on-altchain" concerns that don't apply to us because of
BTC parity discipline:

- **"Lightning relies on specific dust limit semantics."** True;
  b3chain inherits the 546-satoshi dust limit and the `IsStandard`
  policy unchanged.
- **"Lightning needs RBF."** True; b3chain inherits RBF policy
  unchanged (full RBF on by default in BTC Core 30.x).
- **"Lightning needs package relay for anchor channels."** True;
  b3chain inherits package relay (shipped BTC Core 28+).
- **"Lightning's commitment tx uses `SIGHASH_SINGLE |
  SIGHASH_ANYONECANPAY` in specific ways."** Yes; we inherit the
  full `SIGHASH` machinery from BTC Core unchanged.

The thing to *actually* worry about is operational: keeping the
`btcd` / `btcsuite` fork current as upstream evolves. That's why
R-15 (quarterly upstream-rebase) is listed as a soft pre-req for
R-13's long-term sustainability — without it, the LN fork rots
within a year.

## §7 Things that genuinely are risk

- **`btcsuite/btcd` upstream is in maintenance mode** (Lightning
  Labs deprioritised it). Litecoin, BCH, Dogecoin all maintain
  their own `*suite/*d` forks for the same reason. Plan for the
  fork to be permanent.
- **LDK is moving faster than LND right now.** If the team has
  Rust capacity, Phase 13c (LND demo) could be deprioritised in
  favour of an LDK-first plan (R-21 in the §9 proposal).
- **Public LSP economics are not trivial.** Phase 13d implies
  inbound liquidity provisioning and channel rebalancing. Defer
  to community / commercial LSPs (Voltage, Boltz) once R-13 is
  past the credibility-demo bar.

## §8 How R-13 amplifies the rest of the roadmap

| Other R-item | Effect of R-13 landing |
|---|---|
| R-01 exchange-grade RPC parity | LN demo *is* a complete exchange-grade integration test of the RPC surface (ZMQ + JSON-RPC + mempool + RBF). The demo doubles as R-01's acceptance test. |
| R-02 listing handbook | "Lightning Network compatible — see `demo-r0/`" is a single bullet that elevates the handbook above any other small-cap PoW chain. |
| R-03 hardware-wallet support | Some HW wallets (Trezor) sign LND PSBT-format funding txs. R-13 surfaces the path-derivation work R-03 already covers. |
| R-11 asset issuance | If R-11 lands on "no native asset issuance — defer to L2", R-13 is the L2 you defer *to*. Without R-13 the deferral has no destination. |
| R-15 quarterly upstream-rebase | R-13 creates a *standing* `btcsuite/btcd` fork that must be re-based to track BTC Core mempool/policy changes. R-15's existence is what makes R-13 sustainable. |

## §9 Recommendation: split R-13 + add R-20 / R-21 / R-22

**Proposal:** split off two pieces, keep R-13 itself intact, add
three new R-items.

- **Add R-20** (new, P1) — Lightning compatibility statement &
  test vectors. Docs-only. The Phase 13a content.
- **Keep R-13** as P1, but tighten its scope to "server-side LND +
  `btcsuite` fork + dual-node testnet demo". Phases 13b + 13c only.
- **Add R-21** (new, P1) — LDK port for mobile-wallet ecosystem.
  Library deliverable, not node.
- **Add R-22** (new, P2) — Public LSP-ish testnet node +
  watchtower. Phase 13d only.

Net effect on the roadmap: 19 → 22 items; tier counts shift from
P0=6 / P1=8 / P2=5 to P0=6 / P1=10 / P2=6.

### §9.1 Why this carving and not alternatives

**Why not "leave R-13 alone + add only R-20 LDK".** The
compatibility statement (Phase 13a) is the single highest-ROI piece
of Lightning work and it has *zero* dependencies on the LND fork.
Burying it inside R-13 means it ships *after* 3–5 weeks of `btcsuite`
patching, when it could ship in 1 week as a standalone listing-
committee-facing artefact. That's wrong sequencing. Any third-party
LN dev or wallet team can act on the compatibility statement
immediately — they don't need to wait for us to finish the LND
demo to start their own integration.

**Why not "split R-13 into R-13a / b / c / d".** Sub-numbering
(a/b/c) violates the rest of the roadmap's "one item = one
shippable deliverable" pattern and adds bookkeeping for no
information gain. The R-NN namespace exists exactly so that what
looks like sub-phases of one thing can be flat items with explicit
pre-req chains.

**Why R-13's remaining scope (LND demo) stays unitary.** The LND
patch, the `btcsuite/btcd` chain-params fork, the dual-node
testnet, and the `demo-r0/` artefact set all have to land together
to be useful. You cannot ship "the LND patch is done but no demo
exists" — the demo *is* how a reviewer validates the patch. So
splitting that in half buys nothing.

**Why LDK gets its own item rather than being a Path-C sub-bullet
of R-13.** Different language (Rust), different audience (mobile
wallets and embedded clients, not server operators), different
consumer set (Breez SDK, Mutiny, Bitkit), different release cadence
than LND. Treating it as "Path C of R-13" understates that it's an
independent engineering programme aimed at an entirely different
market segment.

**Why the public LSP-ish node drops to P2.** It's operational, not
engineering. Once R-13 lands, anyone (including a community member)
can stand up that node from the `demo-r0/` artefacts. Promoting it
to P1 implies the *team* must run it, which forces an open-ended
operational commitment (inbound liquidity, channel rebalancing,
watchtower SLA). That commitment is real but not blocking for "is
b3chain Lightning-compatible — yes/no".

### §9.2 Pre-req chain after the change

```text
R-20 (compat statement, docs)  ->  no pre-reqs
        |
        +--> R-13 (LND demo)             ->  needs R-20 chain params
        |
        +--> R-21 (LDK port)             ->  needs R-20 chain params
                |
                +--> R-22 (public LSP)   ->  needs R-13 deployable LND config
```

This chain makes the critical path explicit: R-20 unblocks the two
parallel engineering tracks (R-13 server, R-21 mobile), and R-22
is opt-in.

### §9.3 Why R-20 is P1 and not P0

R-20 is technically eligible for P0 — same effort profile as R-05
(funding-model statement) and R-14 (security disclosure), and
listing-committee-facing in the same way. It's tiered **P1** rather
than P0 because the absence of a Lightning compatibility statement
does not *block* a listing review the way absence of a security
contact does. But it's a strong P1 — the kind that should be
sequenced very early in P1 execution, not last.

### §9.4 Proposed roadmap edits

If §9 is approved, edits to [`POW-PEERS-ROADMAP.md`](POW-PEERS-ROADMAP.md):

1. Update the "Tier rules" item counts: P0 stays at 6; P1 grows
   from 8 to 10; P2 grows from 5 to 6.
2. Tighten R-13's `In-tree home` to remove the
   `doc/scaling/LIGHTNING.md` reference (that moves to R-20) and
   tighten the `Acceptance` to "server-side LND + `btcsuite` fork
   + dual-node testnet demo only — see
   [`R-13-LIGHTNING-EXPANSION.md`](R-13-LIGHTNING-EXPANSION.md)
   §4.2 + §4.3 for full scope".
3. Add R-20 (Lightning compatibility statement &
   test vectors), R-21 (LDK port), R-22 (public LSP node) as new
   R-items with all eight standard fields, each citing the
   corresponding §4.x of this document.
4. Update the sequencing mermaid: R-20 unblocks R-13 + R-21; R-13
   unblocks R-22.

Open question (deliberately left for human decision):
should R-20 be promoted to P0 instead? See §9.3. The document
recommends P1; the team's call.
