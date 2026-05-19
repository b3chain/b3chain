# B3Chain Security Roadmap

The Phase 11 self-audit ([`SECURITY-AUDIT.md`](SECURITY-AUDIT.md))
verifies that what we shipped behaves correctly today. The
inheritance audit ([`SECURITY-INHERITANCE.md`](SECURITY-INHERITANCE.md))
verifies that we did not break any property Bitcoin already proves.
This document is the **forward-looking** counterpart: the eight
things that should happen before, around, or after mainnet launch to
keep raising the bar.

Each item below is sized small enough to be tracked as a single
GitHub issue. Status values:

- `proposed` — discussed, not yet scheduled.
- `in-progress` — work has started, not yet shipped.
- `done` — shipped and verified.
- `deferred` — explicitly out of scope for the current cycle, with
  a written reason.

Last reviewed: not yet (rewritten by maintainer review).

---

## 1. OSS-Fuzz integration for BLAKE3 dispatcher and consensus parsers

| Field | Value |
|-------|-------|
| **Status**       | `proposed` |
| **Priority**     | High |
| **Effort**       | 2–4 person-weeks |
| **Dependencies** | OSS-Fuzz Google account; existing `src/test/fuzz/` harnesses |
| **Owner**        | (unassigned) |

### Scope

Bitcoin Core already has 60+ libFuzzer harnesses under `src/test/fuzz/`.
B3Chain inherits all of them. Two additions are specifically B3Chain
business:

1. A harness for the BLAKE3 SIMD dispatcher: feed random byte
   sequences, compare outputs across SIMD/portable, fail on any
   mismatch. (This is the differential test from `audit-simd-blake3.py`
   running continuously.)
2. A harness for any new consensus parser code introduced by the PoW
   swap (e.g. PoW context-string parsing, if any).

### Expected security gain

OSS-Fuzz runs continuously on Google's infrastructure with thousands
of CPU-hours. A reachable bug is found in days rather than years.

### Risks

- Onboarding requires a public-coverage commitment; we should be
  comfortable that OSS-Fuzz's bug-disclosure process matches our
  disclosure policy.
- Triage burden if the dispatcher is noisy.

---

## 2. Reproducible Guix builds verified against vendored BLAKE3 SHA

| Field | Value |
|-------|-------|
| **Status**       | `proposed` |
| **Priority**     | High |
| **Effort**       | 1–2 person-weeks |
| **Dependencies** | `contrib/guix/` (inherited unchanged from Bitcoin Core) |
| **Owner**        | (unassigned) |

### Scope

Bitcoin Core ships a Guix-based reproducible build pipeline that
produces byte-identical binaries on any machine. B3Chain inherits this.
The B3Chain-specific verification steps are:

- The vendored BLAKE3 C library (`src/crypto/blake3/c/`) is pinned to a
  specific upstream SHA. The Guix manifest must verify that SHA at build
  time and refuse to build if it changed.
- Each release publishes the SHA-256 of the produced `b3chaind` and
  `b3chain-cli` binaries. Anyone can rebuild and verify.

### Expected security gain

Defends against compromise of any single maintainer's build environment
(see CCleaner 2017, Solarwinds 2020 supply-chain attacks).

### Risks

- Guix tooling has a steep onboarding curve; we should provide a
  one-command wrapper.

---

## 3. Continuous benchmark CI

| Field | Value |
|-------|-------|
| **Status**       | `in-progress` |
| **Priority**     | Medium |
| **Effort**       | 1 person-week (already started) |
| **Dependencies** | [`.github/workflows/compare-bench.yml`](../.github/workflows/compare-bench.yml) |
| **Owner**        | (current extension PR) |

### Scope

The throughput comparison
[`compare-pow-throughput.py`](../contrib/testing/compare/compare-pow-throughput.py)
runs on every PR and fails if BLAKE3d throughput regresses by more than
10% versus a pinned baseline. Already wired up in
`compare-bench.yml`. Future work:

- Wire up the block-validation comparison (slower; should run nightly,
  not per-PR).
- Add a "result over time" chart to the website.
- Add an actual physical-power meter to the benchmark machine.

### Expected security gain

Performance regressions are usually code-quality bugs that have
security implications too (e.g. a buffer copy that the optimiser
suddenly stops eliding).

---

## 4. External cryptographic audit

| Field | Value |
|-------|-------|
| **Status**       | `proposed` |
| **Priority**     | Critical (blocking mainnet launch) |
| **Effort**       | 4–8 person-weeks of audit firm time + 2 person-weeks of internal time |
| **Cost bracket** | $40K – $120K USD depending on scope |
| **Dependencies** | Phase 11 self-audit complete (it is); B3PoW v1.1.1 51%-attack self-evaluation complete (see [`B3POW-51-ATTACK-ANALYSIS.md`](security/B3POW-51-ATTACK-ANALYSIS.md)) |
| **Owner**        | (unassigned) |

### Scope

Engage a reputable cryptography audit firm (Trail of Bits, NCC Group,
Cure53, Quarkslab, Least Authority) for a focused review of:

- The B3PoW-Scratch v1.1.1 PoW integration: every diff from upstream
  Bitcoin Core that touches `pow.cpp`, `pow/lwma3.{h,cpp}`,
  `validation.cpp` PoW paths, `chainparams.cpp`, `crypto/blake3/`,
  `crypto/b3pow_scratch.{h,cpp}`, and `crypto/b3pow_cache.{h,cpp}`.
- The 51%-attack mitigations M-2..M-9 documented in
  [`B3POW-51-ATTACK-ANALYSIS.md`](security/B3POW-51-ATTACK-ANALYSIS.md):
  BIP94, LWMA-3, max_reorg_depth, the 2-tier pinned cache, the
  depth-asymmetric verifier budget, the emergency-checkpoint stub,
  and the paranoid-headers-sync flag.
- The address format changes (`key_io.cpp`, base58/bech32 wiring).
- The HD wallet coin_type swap.

The audit firm is **not** asked to re-audit Bitcoin Core itself —
that's Bitcoin's reviewers' job.

### Deliverable

Public audit report, hosted on b3chain.org, with all findings and
remediations linked.

### Expected security gain

External adversarial review catches what internal review consistently
misses.

### Risks

- Firms with deep PoW expertise have multi-month lead times; book
  early.
- Findings may delay launch; that is acceptable.

---

## 5. Bug bounty programme

| Field | Value |
|-------|-------|
| **Status**       | `proposed` |
| **Priority**     | High (post-launch) |
| **Effort**       | 1 person-week setup + ongoing triage |
| **Cost bracket** | $5K – $50K per finding (tiered) |
| **Dependencies** | External audit complete |
| **Owner**        | (unassigned) |

### Scope

Public bounty programme with payout tiers:

| Severity | Component | Payout (USD) |
|----------|-----------|-------------:|
| Critical | Consensus | $50 000 |
| High     | Wallet    | $20 000 |
| High     | RPC / P2P | $15 000 |
| Medium   | Website / docs leak credentials | $1 000 |
| Low      | Anything reachable but non-exploitable | $250 |

Hosted on Immunefi, HackerOne, or self-hosted with a clear scope and
disclosure policy.

### Expected security gain

Continuous, market-priced incentive for outside researchers to find
bugs before attackers do.

### Risks

- Triage burden grows quickly. Need at least one person rotating
  through inbound reports.
- Payout funding must be earmarked separately from operational budget.

---

## 6. Post-quantum signature experiment (measurement-only)

| Field | Value |
|-------|-------|
| **Status**       | `proposed` |
| **Priority**     | Low (nothing breaks if deferred) |
| **Effort**       | 4–6 person-weeks |
| **Dependencies** | none |
| **Owner**        | (unassigned) |

### Scope

Add a separate, non-activated transaction version that uses Falcon-512
or Dilithium-2 signatures alongside ECDSA. Measure the impact on:

- Transaction size (PQC sigs are 1–4 KB vs ECDSA's 71 bytes).
- Verification CPU cost.
- UTXO set growth.
- Mempool behaviour with full PQC tx workloads.

This is **measurement only**. No consensus change. The data informs a
future decision about whether/when/how to deploy PQC-protected outputs.

### Expected security gain

When (not if) sufficiently capable quantum hardware appears, ECDSA
preimages can be recovered from public keys exposed by spent outputs.
Bitcoin and forks share this exposure. Doing the measurement now means
we are not surprised later.

### Risks

- Curiosity from press / community that this means we plan to switch.
  We don't, yet. Communications must be very clear.

---

## 7. Mainnet checkpoint key ceremony

| Field | Value |
|-------|-------|
| **Status**       | `in-progress` (the emergency-checkpoint *stub* shipped as M-9 / V-5; the multi-party signing ceremony is still pending) |
| **Priority**     | Medium (in-progress) |
| **Effort**       | 1 person-week ceremony + ongoing per-checkpoint |
| **Dependencies** | M-9 stub shipped ([`src/node/emergency_checkpoints.{h,cpp}`](../src/node/), [`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](security/RESPONSE-RUNBOOK-51ATTACK.md)) |
| **Owner**        | (unassigned) |

### What shipped (stub)

`-assumevalidcheckpoints=<path>` loads operator-supplied JSON of
(height, hash) pairs and rejects any block at one of those heights
with a different hash.  The binary ships ZERO checkpoints; this flag
is OFF by default.  See the runbook for the operational procedure.

### What's still proposed (ceremony)

### Scope

If the project decides to ship maintainer-signed checkpoints (pinned
block hashes that nodes can opt into refusing reorgs past), the
checkpoint key generation must be:

- Multi-party, M-of-N (e.g. 3-of-5 maintainer keys).
- Generated in a documented in-person ceremony with attendees, video
  recording, and post-ceremony attestation hashes.
- Stored in geographically-distributed hardware wallets.
- Rotated on a schedule.

Followed by a published checkpoint-publication policy: when, by whom,
under what process.

### Expected security gain

A defence-in-depth against sustained 51% attacks during the chain's
early years, when honest hashrate is low.

### Risks

- Centralisation concern: nodes that opt into the checkpoint stream
  trust the maintainers. The opt-in must be explicit and reversible.
- Opt-in by default vs opt-in on request — we recommend opt-in on
  request, never opt-in by default.

### Status note

Deferred unless and until 51% attack probability becomes a real
operational concern. Documented here so we have the procedure ready
if needed.

---

## 8. Hardware-rooted miner integrity (TPM-attested miner identity)

| Field | Value |
|-------|-------|
| **Status**       | `proposed` |
| **Priority**     | Low (research-grade) |
| **Effort**       | 6–10 person-weeks |
| **Dependencies** | OSS-Fuzz, external audit (so we don't add complexity to a not-yet-audited base) |
| **Owner**        | (unassigned) |

### Scope

Mining pools today have no good way to verify that a connected miner
is running the agreed-upon software. A TPM-based attestation could let
a pool require:

- Miner runs an unmodified, signed b3chain-miner binary.
- Pool can enforce policy (e.g. require version X+).
- Suspicious behaviour can be tied to a hardware identity, not just an
  IP.

This is research-grade — there is no industry deployment we can copy.
It is on the roadmap as a long-term direction, not a launch blocker.

### Expected security gain

Reduces the surface for malicious mining strategies (selfish mining,
withholding attacks, censorship by individual miners).

### Risks

- Centralising risk: who chooses which TPMs are accepted? Bad answers
  here are worse than no attestation at all.
- TPM availability and standardisation: not all mining hardware ships
  with a usable TPM.

---

## 9. Continuous 51%-attack monitoring & alerting

| Field | Value |
|-------|-------|
| **Status**       | `proposed` |
| **Priority**     | High (post-mainnet) |
| **Effort**       | 2–3 person-weeks |
| **Dependencies** | Phase 0 / Phase 1 simulators (`audit-51-attack-sim.py`, `audit-selfish-mining-sim.py`, `audit-bootstrap-reorg-sim.py`) shipped (they did); a dedicated monitoring host with redundant b3chain nodes |
| **Owner**        | (unassigned) |

### Scope

Move the 51%-attack analysis from a self-audit artifact to a
**live signal**.  Components:

- **Hashrate sentinel**: rolling-window hashrate measurement from the
  monitoring host's view of the chain; alert when the apparent hashrate
  drops by > 30% over 1 hour or > 50% over 6 hours.  Inputs: block
  timestamps and LWMA-3 difficulty target.
- **Reorg sentinel**: alert on any reorganisation > 10 blocks
  observed by the monitoring host (well below the
  `max_reorg_depth = 200` cap, so the operator sees it before it
  hits the consensus rule).
- **Stale-tip-headers sentinel**: scrape `debug.log` for the rate of
  `stale-tip-headers (gap=...)` Misbehaving events; alert if a single
  peer triggers it > 3 times / hour.
- **Cache eviction sentinel**: scrape for `b3pow_cache` resize /
  evict log lines (after M-6, these should be near-zero on a
  well-behaved node).
- **Exchange-feed integration**: if at least one cooperating exchange
  publishes a reorg-victim feed (deposit double-spend reports), wire
  it in to the alerting pipeline.

Each sentinel triggers the corresponding section of
[`RESPONSE-RUNBOOK-51ATTACK.md`](security/RESPONSE-RUNBOOK-51ATTACK.md).

### Expected security gain

Catches an attack while it's in motion rather than after the fact.
Reduces mean-time-to-runbook from "exchange tells us" to "monitoring
tells us within minutes".

### Risks

- False positives during legitimate hashrate volatility (mining-pool
  migrations, ISP outages).  Tune thresholds conservatively.
- Adds an alerting surface that itself must be reliable.

---

## How this list evolves

1. New items are proposed by anyone, opened as a GitHub issue with the
   `roadmap-proposal` label, then merged into this document at the
   maintainers' next review.
2. Existing items move through `proposed` → `in-progress` → `done`
   states with a brief note in the row.
3. Items can move to `deferred` with a written reason; never silently
   removed.
4. The accompanying public page
   [`b3chain.org/testing/roadmap.html`](https://b3chain.org/testing/roadmap.html)
   is regenerated from this file.
