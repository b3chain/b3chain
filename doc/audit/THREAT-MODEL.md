# Threat model — B3Chain + B3PoW-Scratch v1.1.1

**Status:** draft for auditor RFP
**Author:** b3chain
**Last updated:** 2026-05-19
**Companion documents:**
[`SCOPE.md`](SCOPE.md),
[`RFP.md`](RFP.md),
[`../security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md),
[`../security/RESPONSE-RUNBOOK-51ATTACK.md`](../security/RESPONSE-RUNBOOK-51ATTACK.md),
[`../SECURITY-AUDIT.md`](../SECURITY-AUDIT.md),
[`../SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md),
[`../SECURITY-ROADMAP.md`](../SECURITY-ROADMAP.md),
[`../whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md),
[`../../contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md),
[`../../contrib/miner/b3miner-hardware/SCHEMATIC.md`](../../contrib/miner/b3miner-hardware/SCHEMATIC.md).

---

## 1. Purpose

This document is the formal threat model an external auditor reads
alongside [`SCOPE.md`](SCOPE.md). It enumerates what we protect, who
we protect it from, and where each defence lives in the repository.
Items the [`B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md)
already analyses in depth are summarised here and cross-referenced
rather than restated.

## 2. Assets (in priority order)

| # | Asset | Description |
|---|---|---|
| A1 | **Network consensus integrity** | Every node on `b3chain-main`/`b3chain-test` agrees on the same ledger of transactions. The PoW swap is the largest single risk to A1; everything else inherits Bitcoin's existing consensus discipline. |
| A2 | **User funds (UTXO)** | The set of spendable outputs and their authorisation conditions. Protected by A1 and by the script-verification stack inherited unchanged from Bitcoin Core. |
| A3 | **Block-subsidy distribution fairness** | The block reward goes to the entity that did the work, and no one can systematically capture more reward than its hashrate share. Specific risk: hashrate concentration during bootstrap (V-6 in the 51%-attack analysis). |
| A4 | **Network availability** | Honest nodes can sync, mine, relay, and accept transactions. The 50 ms B3PoW verifier budget exists specifically to bound the per-header verification cost an attacker can impose on a syncing peer. |
| A5 | **Miner privacy** *(low priority)* | We do not claim protocol-level privacy. A reasonable miner running over Tor / via a pool gets the privacy properties Tor / the pool offer; we do nothing extra and break nothing inherited. |
| A6 | **Software supply chain** | Every binary an operator runs should be reproducibly built from the published source, with attribution that survives commit history. Defended by inherited Guix tooling + the planned [`SECURITY-ROADMAP.md §2`](../SECURITY-ROADMAP.md) verification of the vendored BLAKE3 SHA. |

## 3. Adversaries (tier list)

Tiers are roughly ordered by capability; a higher tier subsumes the
abilities of every lower tier.

| Tier | Adversary | Capabilities | Plausible motive |
|---|---|---|---|
| **T1** | Honest-but-curious researcher (read-only) | Read all public code, run a node, observe public chain state, run regtest experiments. | Academic interest, finding bugs to disclose. |
| **T2** | External miner with consumer hardware (CPU/GPU) | Tier 1 + commodity CPU/GPU compute, broadband, can run a dozen geographically distributed nodes. | Speculative mining; small-scale profit. |
| **T3** | Resourced miner with FPGA capacity (custom B3PoW miner) | Tier 2 + KU5P-class FPGA inventory at scale (10s–100s of cards), DC bandwidth, the ability to clone the open-source RTL. | Maximise mining revenue; possibly attempt selfish-mining-class strategies. |
| **T4** | Resourced miner with ASIC NRE budget (custom B3PoW ASIC; honest about asymmetry) | Tier 3 + a $5–20M 7 nm tape-out budget and the ability to keep the silicon in-house. Per [`B3POW-51-ATTACK-ANALYSIS.md §3.4`](../security/B3POW-51-ATTACK-ANALYSIS.md), per-die advantage is ~4× FPGA, not the 10⁴×–10⁶× advantage SHA-256d ASICs have over CPUs. | Single-vendor mining edge; not (we hope) sustainable monopoly. |
| **T5** | Nation-state / well-funded attacker with multi-modal capability | Tier 4 + the ability to compromise upstream dependencies, coerce ISPs, perform routing attacks (BGP-hijack the seed nodes), or commission supply-chain attacks against the build pipeline. Effectively unbounded budget on any single sub-attack. | Disrupt or capture the chain for strategic / political reasons. |
| **T6** | Malicious insider (contributor with merge rights) | Tier 1 + the ability to submit code into the trusted code path. Mitigated by the **2-ACK consensus** policy on merges to `b3chain-main` and by reproducible builds, but listed explicitly because we cannot prove away insider risk. | Backdoor a critical path; exfiltrate keys; censor a transaction. |

The total adversary-tier count is **6**. Future expansions
(e.g. quantum capabilities) are tracked under
[`SECURITY-ROADMAP.md §6`](../SECURITY-ROADMAP.md) and are not yet a
distinct tier here.

## 4. Attack surfaces

### 4.1 Cryptographic surface

| Surface | Adversary tiers | Where it lives | Residual risk after in-tree mitigation |
|---|---|---|---|
| BLAKE3 collisions / preimages | T5 | `src/crypto/blake3/` (vendored upstream) | Out of scope for this audit — we rely on BLAKE3's own analysis. A break in BLAKE3 invalidates almost every modern post-2020 design; we are not unique here. |
| B3PoW-Scratch algorithmic shortcut (skip / shrink the 2 048 RMW chain) | T3–T5 | [`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp), [`b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) | In scope — [SCOPE.md §5.2](SCOPE.md). M-11 + M-12 + SPEC §8.B/C/F sketch; auditor formalises the bound. |
| BLAKE3 SIMD dispatcher mismatch | T2 | `src/crypto/blake3/` SSE2/AVX2/AVX-512 paths | Mitigated by `audit-simd-blake3.py` (B-1 in `SECURITY-AUDIT.md`) + planned OSS-Fuzz (SECURITY-ROADMAP §1). |
| Reduced-round `mix_step` diffusion | T3–T5 | SPEC §6.5 + §8.F sketch | Open audit item — formal indifferentiability bound requested. |

### 4.2 Consensus surface

| Surface | Adversary tiers | Where it lives | Residual risk |
|---|---|---|---|
| 51% / majority-hashrate attack | T3–T5 | Whole chain | Bounded by `max_reorg_depth = 200` (M-4) + 2-tier pinned LRU (M-6) + depth-asymmetric verifier budget (M-7) + paranoid-headers-sync flag (M-10). Full analysis in [`B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md). |
| Selfish mining (Eyal–Sirer) | T3–T4 | Inherited Bitcoin P2P + LWMA-3 retarget | Auditable threshold α* ≈ 0.25 with γ=0.5, ≈ 0.33 with γ=0; measured by `audit-selfish-mining-sim.py` (A-2). |
| Time-warp attack | T3–T5 | [`src/kernel/chainparams.cpp`](../../src/kernel/chainparams.cpp) | Mitigated by `enforce_BIP94 = true` on mainnet/testnet/signet (M-2 / F-2). Verified by `audit-timewarp-sim.py` (A-3). |
| Difficulty manipulation via small-window oscillation | T3–T4 | [`src/pow/lwma3.cpp`](../../src/pow/lwma3.cpp) | LWMA-3 window=45, solve-time clamp 6×spacing / −spacing/6 (M-3). Floor tightened to `0x1d7fffff` + post-bootstrap operating floor `0x1d3fffff` (M-13 / F-6). |
| Eclipse attack | T3–T5 | Inherited Bitcoin P2P + addrman | Inherited Bitcoin mitigations; default `-maxconnections=200` raises the bar (M-9). Heilman et al. 2015 baseline. |
| `b3pow::Cache` eviction DoS | T2–T4 | [`src/crypto/b3pow_cache.{h,cpp}`](../../src/crypto/b3pow_cache.h) | 2-tier pinned LRU (M-6) prevents tip-pad eviction; verified by `audit-cache-eviction-dos.py` (A-5) + `audit-b3pow-cache-pinning.py` (A-7). |
| Per-header verifier-budget abuse (CPU exhaustion) | T2–T4 | [`src/pow.cpp`](../../src/pow.cpp) + [`src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp) | `BlockValidationResult::BLOCK_POW_BUDGET` + `Misbehaving("b3pow-budget-exceeded")`; per-`HEADERS`-batch cap `MAX_B3POW_VERIFY_PER_BATCH=256` (H-1.1, H-1.3). |
| Deep-reorg attempt | T3–T5 | [`src/validation.cpp`](../../src/validation.cpp) | `BlockValidationResult::BLOCK_DEEP_REORG` at `max_reorg_depth = 200` (M-4 / F-3). Bypassed during IBD / assumevalid / regtest. |

### 4.3 Network surface

| Surface | Adversary tiers | Where it lives | Residual risk |
|---|---|---|---|
| P2P DoS (message flood, invalid header flood) | T2–T5 | [`src/net_processing.cpp`](../../src/net_processing.cpp) | Inherited Bitcoin DoS scoring (`denialofservice_tests.cpp`) + B3PoW-specific `Misbehaving("b3pow-budget-exceeded")` + headers-batch cap. |
| Eclipse / Sybil | T3–T5 | Inherited Bitcoin P2P | Inherited Bitcoin mitigations (addrman v2, BIP155). Sybil-resistance is inherently economic for any PoW chain. |
| Mainnet-magic-bytes confusion | T2 | [`src/kernel/chainparams.cpp`](../../src/kernel/chainparams.cpp) | Bitcoin's `f9beb4d9` rejected at handshake; verified by `audit-network-isolation.py` (N-1). |
| Tor / I2P egress weakness | T1–T3 | Inherited Bitcoin (`feature_proxy.py`, `i2p_tests.cpp`) | Inherited mitigations. |

### 4.4 Mining surface

| Surface | Adversary tiers | Where it lives | Residual risk |
|---|---|---|---|
| Share withholding (block-withholding attack on pool) | T3–T4 | [`contrib/testnet/pool/src/stratum/share-validator.ts`](../../contrib/testnet/pool/src/stratum/share-validator.ts) | Pool detects via standard share-vs-block-ratio statistics. PPLNS payout (P-1 in `SECURITY-AUDIT.md`) limits the attacker's recoverable loss. |
| Pool hijack (rogue Stratum endpoint masquerading as `pool.b3chain.org`) | T2–T5 | Stratum V1 (no auth) / Stratum V2 Noise NX (authed) | V1 is unauthenticated by design — same as every Stratum V1 pool. V2 mitigates via `SignedCertificate` authority binding (P-2). |
| Coinbase capture (pool steals miner's coinbase) | T3 | SV2 `coinbase-pays-pool` policy | SV2 enforces miner-declared coinbase address on miner-declared jobs (P-2). |
| Hashrate concentration / single-vendor monopoly | T3–T4 | Whole network | V-6 in `B3POW-51-ATTACK-ANALYSIS.md`; mitigation = open RTL + multiple SKUs + sustained shipping. Modeled by `audit-fpga-concentration-model.py` (A-6). |

### 4.5 Hardware surface

| Surface | Adversary tiers | Where it lives | Residual risk |
|---|---|---|---|
| Side-channel on FPGA (power / EM / timing) | T4–T5 | [`contrib/miner/b3miner-rtl/rtl/`](../../contrib/miner/b3miner-rtl/rtl/), [`SCHEMATIC.md`](../../contrib/miner/b3miner-hardware/SCHEMATIC.md) | Out of scope for v1 audit unless contracted. PoW evaluation contains no secret material; the only side-channel-sensitive operations are ATECC608B signing on the host MCU, which lives off-FPGA. |
| Glitch attack on ATECC608B (clock / voltage / EM) | T4–T5 | [`SCHEMATIC.md §6.7`](../../contrib/miner/b3miner-hardware/SCHEMATIC.md) | Out of scope for v1 audit. We rely on Microchip's own AT608-rev hardening for the device; the board does not add glitch-detection beyond what the part provides. Listed under "what we accept losing" (§6). |
| JTAG attack on B3Miner-1 (FPGA configuration extraction) | T2–T5 | JTAG header on B3Miner-1 (`SCHEMATIC.md §6.5`) | The RTL is open source; bitstream extraction reveals nothing new. ATECC608B keys are off-FPGA and unaffected. JTAG is physically present as a debug aid; production stencils may DNP the header. |
| Counterfeit board pretending to be a genuine B3Miner-1 | T3–T5 | ATECC608B slot-0 device key (per-card) | Pools can in principle require an ECDSA challenge against slot-0 (the device key is unique per part and non-exportable). Implementation is on the firmware roadmap; absent that, "genuine board" is a non-property today. |

### 4.6 Supply-chain surface

| Surface | Adversary tiers | Where it lives | Residual risk |
|---|---|---|---|
| Dependency compromise (CDN, npm/PyPI, GitHub Actions runner) | T5–T6 | `package-lock.json`, `requirements.txt`, vendored BLAKE3 SHA | Lockfiles checked in; vendored BLAKE3 SHA pinning is roadmap'd (SECURITY-ROADMAP §2). |
| Build-reproducibility break (different binary from same source) | T5–T6 | [`contrib/guix/`](../../contrib/guix/) inherited | Guix builds inherited; B3Chain-specific verification on the roadmap (SECURITY-ROADMAP §2). [`doc/release-process.md`](../release-process.md) documents the regen discipline. |
| Backdoored release artefact | T5–T6 | Release-signing key + Sigstore/Cosign pipeline (planned Phase 2.3 of launch plan) | Pre-launch: ATECC608B slot-2 release-signing key (per `SCHEMATIC.md §6.7.4`) once provisioned. |
| Test-vector poisoning (regenerated vectors no longer match shipped binary) | T6 | `gen_vectors.py` + `b3pow_consensus_vectors.json` parity gates | Parity enforced in CI (`b3miner-rtl.yml` + `b3pow_scratch_tests.cpp`); auditor asked to confirm the gate cannot be bypassed silently. |

### 4.7 Operational surface

| Surface | Adversary tiers | Where it lives | Residual risk |
|---|---|---|---|
| Release-signing key compromise | T5–T6 | ATECC608B slot-2 (planned) / GPG (current) | Pre-launch we rely on operator GPG hygiene; post-launch the key lives on an air-gapped signing host (`SCHEMATIC.md §17`). |
| ATECC608B provisioning-pipeline compromise | T5–T6 | Production test fixture (out-of-tree script, `SCHEMATIC.md §16` item 10) | Documented in schematic; provisioning script not yet in-tree. |
| Pool-operator key compromise (`pool.b3chain.org`) | T5 | Pool DB credentials, payout signing keys | Operational, not protocol-level. Bug bounty (§ scoping in [`security/bug-bounty.md`](../../security/bug-bounty.md)) treats pool DoS as out of scope; consensus impact (e.g. operator paying out invalid shares) is in scope. |
| Seed-node SSH compromise | T5 | SSH posture in [`.cursor/rules/git-push-policy.mdc`](../../.cursor/rules/git-push-policy.mdc) | Key-only on port 2222, `fail2ban`, `deploy` user with NOPASSWD sudo. Single key on the operator's workstation. |

## 5. Adversary × surface matrix

Severity is the maintainers' calibrated estimate at this commit. **H**igh
/ **M**edium / **L**ow. "Residual" = the risk that remains *after* the
in-tree mitigation is honestly evaluated; the auditor is asked to
challenge each row.

| Surface ↓ × Tier → | T1 | T2 | T3 | T4 | T5 | T6 |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| BLAKE3 break | L | L | L | L | M | L |
| B3PoW algorithmic shortcut | L | L | **M** | **M** | **H** | M |
| 51% / selfish mining | L | L | **M** (bootstrap **H**) | **H** | **H** | L |
| Time-warp | L | L | L | L | L | M |
| Verifier-budget DoS | L | M | M | L | L | L |
| Cache eviction DoS | L | M | M | L | L | L |
| P2P DoS | L | M | M | L | L | L |
| Eclipse / Sybil | L | M | M | M | **H** | L |
| Share / block withholding | L | L | M | M | M | L |
| Pool hijack (V1) | L | L | M | M | M | L |
| FPGA side-channel | L | L | L | L | L (out of scope) | L |
| ATECC608B glitch | L | L | L | M | M (out of scope) | L |
| JTAG attack on miner | L | L | L | L | L | L |
| Supply-chain dependency | L | L | M | M | **H** | **H** |
| Build reproducibility | L | L | L | M | **H** | **H** |
| Release-signing key | L | L | L | M | **H** | **H** |
| Pool operator key | L | L | M | M | **H** | M |
| Seed-node SSH | L | L | L | M | **H** | L |

Cells the auditor is most asked to dispute (where a wrong estimate is
expensive): **B3PoW algorithmic shortcut** under T3–T5 and
**51% / selfish mining** under T3 in the bootstrap window. These are
the rows whose risk we have actively engineered against and where an
unknown weakness would invalidate the engineering.

## 6. What we accept losing

Stated explicitly so the auditor knows not to file findings here as
"undefended". These are reasoned trade-offs, not oversights.

- **Complete privacy at the protocol level.** Transactions are
  pseudonymous, not anonymous; payment graphs are public. We inherit
  Bitcoin's privacy posture and add nothing.
- **FPGA glitch-attack resistance on consumer-grade boards.** The
  reference card is a hand-solder-friendly KU5P design optimised for
  open hardware (BOM cost, repairability) rather than tamper
  resistance. A nation-state actor with physical access wins.
- **Permanent ASIC immunity.** B3PoW-Scratch is FPGA-economical and
  on-chip-memory-bound; an ASIC port is feasible and (per the spec
  §8.D table) ~4× per-die. We engineer for "ASIC port is feasible
  for honest miners" rather than "no ASIC is possible".
- **Network-level privacy beyond what Tor / I2P provide.** Inherited
  upstream support, no protocol-level mixnet.
- **Web / Qt GUI hardening as a primary defence.** The GUI is
  user-facing convenience; it is not a security boundary.

## 7. Out of scope

- **Web / Qt UI vulnerabilities.** The wallet GUI and website
  front-end have their own surfaces (XSS, CSRF, browser-fingerprint
  leaks). They are handled by the bug-bounty programme
  ([`security/bug-bounty.md`](../../security/bug-bounty.md)) rather
  than by this audit.
- **Social engineering** against maintainers, contributors, miners,
  or pool operators.
- **OS-level malware** on the operator's workstation. Anything that
  reads the operator's keystrokes or files defeats us regardless of
  our software hygiene.
- **Smart-contract layer-2 systems** that may eventually run atop
  B3Chain. There are none at this commit.

## 8. Trust boundaries (text diagram)

```
              ┌─────────────────────────────────────────────────────────────────┐
              │                  PUBLIC INTERNET (adversarial)                  │
              └─────────────────────────────────────────────────────────────────┘
                     │                    │                       │
                     │ P2P (8533/18533)   │ Stratum V1/V2         │ HTTP(S)
                     │ unauthenticated    │ V1 unauth /           │ TLS 1.3
                     │                    │ V2 Noise NX           │
                     ▼                    ▼                       ▼
              ┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐
              │  b3chaind    │    │ pool.b3chain.org │    │   b3chain.org     │
              │  (node)      │    │  (operator-run)  │    │   (website)       │
              │  TRUST = LOW │    │  TRUST = MED     │    │   TRUST = LOW     │
              └──────┬───────┘    └────────┬─────────┘    └─────────┬─────────┘
                     │ RPC localhost       │ RPC localhost           │
                     │ (cookie auth)       │ to seed1 b3chaind       │ static
                     ▼                     ▼                         │
            ┌────────────────┐    ┌──────────────────┐               │
            │ Wallet / RPC   │    │  Pool DB / web   │               │
            │ TRUST = HIGH   │    │  TRUST = MED     │               │
            └────────┬───────┘    └────────┬─────────┘               │
                     │                     │                          │
                     ▼                     ▼                          ▼
            ┌────────────────────────────────────────────────────────────┐
            │  OPERATOR WORKSTATION (b3chain maintainers; trusted root)  │
            │  - GPG / SSH keys                                          │
            │  - Build pipeline (Guix planned)                           │
            │  - Release signing                                         │
            └────────────────────────────────────────────────────────────┘

                                    ─ ─ ─ ─ ─ ─

            ┌────────────────────────────────────────────────────────────┐
            │   Miner data plane (B3Miner-1 reference card)              │
            │  ┌────────────────┐  SPI(40b)  ┌─────────────────────────┐ │
            │  │  ESP32-S3 host │ ─────────▶ │ XCKU5P (RTL, this audit)│ │
            │  │  Stratum + OTA │            │ scratchpad + mixing     │ │
            │  └────┬──────┬────┘            └─────────────────────────┘ │
            │       │ I2C  │ Ethernet/W5500                              │
            │       ▼      │                                              │
            │  ┌────────┐  │                                              │
            │  │ATECC   │  │ to pool (Stratum V1 / V2)                    │
            │  │608B    │  │                                              │
            │  │TRUST = │  │                                              │
            │  │HIGHEST │  │                                              │
            │  │(part   │  │                                              │
            │  │never   │  │                                              │
            │  │exports │  │                                              │
            │  │keys)   │  │                                              │
            │  └────────┘  │                                              │
            └────────────────────────────────────────────────────────────┘
```

Trust-level shorthand:

- **LOW** — anyone-can-talk-to surface, no secret material assumed safe inside it.
- **MED** — operator-controlled; compromise affects operator's
  customers, not consensus.
- **HIGH** — long-lived secret material lives here.
- **HIGHEST** — secret material that the rest of the system **cannot
  recover from compromise** (ATECC608B-held device key; release-signing
  key once provisioned to slot 2).

The auditor is asked to confirm the (highest → lower) information
flows: ATECC608B → ESP32-S3 firmware reveals only signatures, never
key bytes; ESP32-S3 → FPGA reveals only header / share data, never
secret material; FPGA → public network reveals only valid shares.
The (lower → higher) flows are equally important: nothing on the
public internet should be able to write to the ATECC608B
configuration zone, which is why §6.7.4 of the schematic locks the
configuration zone at provisioning time.

## 9. Cross-references

- [`B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md) — the long-form 51%-attack treatment this document summarises.
- [`SECURITY-AUDIT.md`](../SECURITY-AUDIT.md) — the in-tree self-audit baseline.
- [`SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md) — what Bitcoin proves that we still prove.
- [`SECURITY-ROADMAP.md`](../SECURITY-ROADMAP.md) — what we plan to harden next.
- [`SCOPE.md`](SCOPE.md) — what code the auditor is asked to read.
- [`RFP.md`](RFP.md) — the engagement-request template.
- [`../../security/bug-bounty.md`](../../security/bug-bounty.md) — the post-audit standing-incentive programme.
