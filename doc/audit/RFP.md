# Request for Proposal — external security audit of B3Chain + B3PoW-Scratch v1.1.1

**Status:** template; maintainer fills the `[PLACEHOLDER]` brackets
before sending.
**Author:** b3chain
**Last updated:** 2026-05-19
**Companion documents:**
[`SCOPE.md`](SCOPE.md),
[`THREAT-MODEL.md`](THREAT-MODEL.md),
[`../security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md),
[`../SECURITY-AUDIT.md`](../SECURITY-AUDIT.md),
[`../SECURITY-ROADMAP.md`](../SECURITY-ROADMAP.md),
[`../whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md).

---

## 1. Cover letter (copyable intro paragraph)

> Dear [FIRM NAME],
>
> We are b3chain, the maintainers of B3Chain — a Bitcoin Core 30.2.0
> fork that replaces SHA-256d Proof-of-Work with **B3PoW-Scratch
> v1.1.1**, a memory-hard BLAKE3 variant we have specified, prototyped,
> CI-gated across four implementations (C++ consensus, Python reference,
> TypeScript pool validator, SystemVerilog RTL), and live-tested on
> testnet. Before mainnet launch we are commissioning an external
> security audit of the PoW swap and its supporting code. We believe
> your firm is a good fit because of [SPECIFIC PRIOR WORK]. The audit
> package — scope, threat model, and the existing self-audit
> baseline — is linked below. We would welcome a scoping call at your
> convenience and a formal proposal in response. Maintainer contact:
> `audits@b3chain.org`.

## 2. Project background

**B3Chain** is a Bitcoin Core 30.2.0 fork. The repository is at
[`github.com/b3chain/b3chain`](https://github.com/b3chain/b3chain) on
the MIT license. UTXO model, monetary schedule (21 M cap, 210 000-block
halving), block-identity hash (SHA-256d), wallet format, and P2P
protocol are inherited unchanged. The fork is pre-mainnet; testnet
(`b3chain-test`) has been running on `pool.b3chain.org:3333` since
2026-05 with a public faucet, a Stratum V1 and Stratum V2 pool, and a
reference KU5P FPGA miner (B3Miner-1). Bitcoin Core's full inherited
test suite (144 properties across consensus / wallet / P2P) passes
unmodified on B3Chain at this commit; see
[`doc/SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md).

**The launch dilemma we engineered against.** A new Bitcoin-derived
chain that ships on SHA-256d inherits Bitcoin's existing ASIC fleet
as an attacker on day one. Choosing a GPU-friendly algorithm trades
the ASIC-carryover risk for botnet-hashrate risk. We instead designed
**B3PoW-Scratch v1.1.1**: a 1 MiB on-chip-memory-bound construction
that is FPGA-economical on a Xilinx Kintex UltraScale+ KU5P at ~10 W,
GPU-hostile by virtue of the sequential 2 048 RMW chain, and
ASIC-non-trivial (a 7 nm port is feasible at ~$5–20M NRE for ~4×
per-die throughput — see [`doc/security/B3POW-51-ATTACK-ANALYSIS.md
§3.4`](../security/B3POW-51-ATTACK-ANALYSIS.md)). The construction,
its mitigations, and the open audit items are documented in
[`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md)
and the launch-grade whitepaper
[`doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md).

**Why an audit now.** The PoW swap is the largest single diff against
upstream and the load-bearing claim of the project. We have completed
an in-tree self-audit (23 properties green —
[`doc/SECURITY-AUDIT.md`](../SECURITY-AUDIT.md)), an explicit
51%-attack threat model with 13 in-tree mitigations
([`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md)),
and the four-implementation parity discipline above. External
adversarial review is the next step we cannot do for ourselves;
[`SECURITY-ROADMAP.md §4`](../SECURITY-ROADMAP.md) lists this
engagement as a blocking item for mainnet launch.

## 3. Scope summary

The full scope-of-engagement document is at [`SCOPE.md`](SCOPE.md).
At a glance:

- Consensus C++ (`src/crypto/b3pow_scratch.{h,cpp}`, `b3pow_cache.{h,cpp}`, `src/pow/`, validation paths in `src/validation.cpp`/`src/net_processing.cpp`/`src/kernel/chainparams.cpp`).
- Reference Python (`contrib/miner/b3miner-rtl/ref/`) and the parity vectors (`src/test/data/b3pow_consensus_vectors.json`).
- Pool TypeScript (`contrib/testnet/pool/src/lib/b3pow-scratch.ts`, `lib/pad-cache.ts`, `src/stratum/share-validator.ts`).
- RTL (`contrib/miner/b3miner-rtl/rtl/*.sv`).
- Hardware secure-element design (`contrib/miner/b3miner-hardware/SCHEMATIC.md §6.7`; firmware integration on the [`SECURITY-ROADMAP`](../SECURITY-ROADMAP.md) — implementation lands during the engagement window).

Inherited Bitcoin Core consensus paths the fork did not touch, the
Qt GUI, and vendored subtree libraries (secp256k1, leveldb,
minisketch, crc32c) are **out of scope** for this engagement.

## 4. Threat model summary

The full threat model is at [`THREAT-MODEL.md`](THREAT-MODEL.md). At
a glance: six adversary tiers (T1 honest researcher → T6 malicious
insider), seven attack-surface categories (cryptographic, consensus,
network, mining, hardware, supply-chain, operational), and an
adversary × surface severity matrix the auditor is asked to dispute.
The cells most likely to repay audit effort are **B3PoW algorithmic
shortcut** (T3–T5) and **51% / selfish mining in the bootstrap
window** (T3 onwards).

## 5. Deliverables wanted

1. **Written report**, suitable for public publication on
   `b3chain.org`, listing every finding with code references at the
   pinned commit.
2. **Severity-ranked findings** (Critical / High / Medium / Low /
   Informational) with reproducer cases.
3. **Reproducer scripts or patches**, against the pinned commit.
4. **Remediation suggestions** calibrated to the maintainers' small,
   reviewable, traceable diff discipline.
5. **Optional follow-up review** of remediations, priced separately.

## 6. Timeline preference and flex

Maintainer preference is **engagement start within 4 weeks of
signing**, with a draft report by **week 6–8** and the final report
no later than **week 10** of the engagement.

Hard constraints (cannot move):

- The auditor must hold the pinned commit unchanged for the entire
  engagement window; we will not rewrite history on `b3chain-main`
  during the audit.
- Findings affecting consensus must be embargoed until coordinated
  disclosure per §8.

Soft constraints (we will accommodate):

- We expect to ship fixes within four weeks of the report.
- We can defer mainnet launch to absorb high-severity findings;
  delaying launch is preferable to shipping a known-broken chain.

## 7. Budget range

`[USD X – Y]` — maintainer fills based on engagement size; see
[`SCOPE.md §8`](SCOPE.md) and
[`SECURITY-ROADMAP.md §4`](../SECURITY-ROADMAP.md) for the
$40K–$120K USD scoping bracket. We welcome proposals outside this
range with justification.

## 8. Engagement model

The maintainers are open to either model and ask the firm to
recommend the one that fits its own internal accounting best.

- **Fixed-fee** with a written scope, milestone payments at kickoff /
  draft report / final report. Preferred for "Lite" / "Standard"
  scopes from [`SCOPE.md §8`](SCOPE.md).
- **Hourly** with a written cap, time logs reported weekly. Preferred
  for "Deep" scopes where the upper bound of effort is hard to
  predict in advance (e.g. RTL parity at scale, ATECC608B
  side-channel work).

In both cases the maintainers ask for a written change-order process
if scope creep is identified mid-engagement, and we commit to
responding to scope-clarification questions within 48 hours.

## 9. NDA / public-disclosure expectations

- We expect to publish the **final report verbatim** on
  `b3chain.org`. Drafts are confidential to the maintainers; we will
  not share drafts outside the maintainer group during the
  engagement.
- We expect a **coordinated public-disclosure window** for any
  Critical or High finding. Default window: 90 days from initial
  report, negotiable shorter if active exploitation is observed in
  the wild, negotiable longer if the fix requires a hard fork.
- Mutual NDA in place during the engagement window;
  post-publication, the report and any fix patches are public under
  the project's MIT licence. Reproducer artefacts the firm wishes to
  retain as proprietary trade secrets should be flagged at scoping;
  we will not publish those.

## 10. References we would value

A short list of comparable prior work would help us evaluate
fit. Specifically we are interested in:

- **PoW consensus audits** for any Bitcoin-derived or BLAKE3-derived
  chain. RandomX, Equihash, Cuckatoo, Ethash audits are all relevant
  comparables; please cite specifically.
- **BLAKE3 implementation audits** (e.g. for the reference C, the
  SIMD dispatcher, or RTL ports).
- **FPGA / RTL audits** with public reports. Single-vendor IP audits
  (e.g. Xilinx soft-CPU cores) are useful comparables.
- **Hardware secure-element integration audits** (ATECC608x, OPTIGA
  Trust M, NXP SE050).
- **Stratum V2 / Noise protocol** audits — we would value any
  experience with the Stratum-V2 reference implementations or with
  the Snow / NoiseLink Noise stacks.

We are not strict about format; a list of "we did X for Y, public
report at Z, lead engineer was A" is enough.

## 11. Sample questions for the firm

The maintainers ask the firm to address the following in its
proposal:

1. How will you handle the **four-implementation parity** burden? Do
   you propose to verify all four impls in scope, or to derive
   confidence in three from a single-impl deep-dive plus
   differential testing?
2. What is your **RTL verification depth**? Are you set up to read
   SystemVerilog adversarially, or do you propose to treat the RTL as
   a black box validated against the Python reference?
3. What is your stance on **memory-hardness proofs**? We are not
   asking for a publishable indifferentiability proof, but we do
   want a defensible lower bound on the recompute cost at
   sub-`SCRATCH_BYTES` adversary memory. How rigorous will your
   analysis be?
4. Do you have in-house **fuzzing infrastructure** beyond the
   in-tree harnesses (`contrib/oss-fuzz/b3chain/`,
   `audit-simd-blake3.py`, `verify-b3pow.py`)? We are happy to extend
   the existing harnesses to your specifications.
5. How will you handle the **ATECC608B implementation gap**? The
   schematic-level design is committed; the firmware `b3_sec`
   component is on the roadmap. Are you willing to review the design
   now and the code when it lands, or do you prefer to scope a
   single later window that covers both?
6. What is your **disclosure-window policy** in the case where a
   finding requires a hard fork to remediate? We are willing to
   delay disclosure if the alternative would put the network at
   immediate risk.
7. What **public report format** do you prefer, and are you willing
   to publish the report under a permissive licence (CC-BY-4.0 or
   equivalent) so we can mirror it from `b3chain.org`?
8. What is your **conflict-of-interest policy** for any miner /
   pool / exchange operator who might wish to commission a follow-up
   audit? We are happy to make the audit-firm relationship public,
   but we will not enter an exclusivity arrangement.

## 12. Contact

- **Primary contact:** `audits@b3chain.org`
- **Project URL:** [`https://b3chain.org`](https://b3chain.org)
- **Repository:** [`https://github.com/b3chain/b3chain`](https://github.com/b3chain/b3chain) (branch `b3chain-main`, commit `<COMMIT>` for the engagement)
- **Bug-bounty / security disclosures:** [`https://github.com/b3chain/b3chain/blob/b3chain-main/security/bug-bounty.md`](https://github.com/b3chain/b3chain/blob/b3chain-main/security/bug-bounty.md) + RFC 9116 `security.txt` at `https://b3chain.org/.well-known/security.txt`.

---

## Appendix A — Auditor shortlist (maintainer reference; not in the sent RFP)

This appendix is for the maintainers' internal scoping and is
**not** part of the RFP sent to firms. Verify each firm's current
practice areas before contacting; this list is calibrated to 2026
publicly available information and may be stale.

| Firm | URL | Known specialty | Why a good fit | Why a risk |
|---|---|---|---|---|
| **Trail of Bits** | trailofbits.com | Low-level systems, cryptography, blockchain protocol reviews. Maintains `osquery`, `manticore`, `slither`. Has published audits of multiple Bitcoin-derived projects. | Deep C/C++ review capacity; strong fuzzing culture; has historically taken on PoW reviews. | High demand → multi-month lead times typical; pricing at the upper end of the bracket. |
| **Cure53** | cure53.de | Web / browser / WebRTC / cryptographic protocol audits; significant Tor and Signal work. | Excellent on Noise (Stratum V2) and on TS / JS code review (pool stack); strong reputation for adversarial thinking. | PoW / RTL surface is not their primary practice area; we would want to confirm reviewer assignment. |
| **Quarkslab** | quarkslab.com | Hardware security, secure-element analysis, embedded firmware reverse-engineering. | Strong fit for the ATECC608B + firmware portion; published work on Microchip Trust*M and ATECC parts. | Less PoW-protocol depth than Trail of Bits / NCC; would scope a hardware-focused engagement well but might propose to subcontract the consensus review. |
| **NCC Group** | nccgroup.com | Broad spectrum; significant cryptographic protocol and embedded work; FOX-IT integration. | Likely able to staff every surface in [`SCOPE.md`](SCOPE.md) from one firm; published Bitcoin-related reports. | Larger firm → team composition harder to lock; review depth varies by reviewer. |
| **Kudelski Security** | kudelskisecurity.com | Cryptographic hardware, smart card / SE work, IoT. Has a published crypto practice. | Strong on the hardware secure-element surface and on cryptographic primitives. | PoW-protocol depth is the smaller part of their practice; we would want to confirm specific consensus-review staffing. |
| **OpenZeppelin** | openzeppelin.com | Smart-contract audits (Solidity, Cairo, Move). Defender / Sentinel tooling. | Strong cryptography depth at the contract-language layer. | **Less PoW-focused**; their public portfolio is heavily L2 / smart-contract — would want strong confidence in a B3PoW-capable reviewer before contracting. |
| **Sigma Prime** | sigmaprime.io | Ethereum / Lighthouse client; significant consensus-client experience. | Deep consensus-client review experience; strong fuzzing. | **Ethereum-focused** — Bitcoin-derived UTXO + PoW is a different stack from their day-to-day; would want explicit reviewer match. |
| **Halborn** | halborn.com | Blockchain protocol and DeFi audits; broad portfolio. | Active in the blockchain audit market; can typically scope quickly. | Quality varies by engagement; we would want code-level deliverable samples before contracting. |
| **Least Authority** | leastauthority.com | Zcash, Filecoin, MobileCoin audits; cryptographic protocol depth. | Has the cryptography depth for the diffusion-bound work in [`SCOPE.md §5`](SCOPE.md) property 2. Comfortable with PoW. | Smaller team; scheduling can be tight. |

**Maintainer notes:**

- The "good fit / risk" notes are calibrated to the engagement scope
  in [`SCOPE.md`](SCOPE.md). A firm marked as risky here may still
  be the right choice for a different scope.
- For "Deep" engagements covering both consensus and the
  ATECC608B / RTL surfaces, a **two-firm split** (one firm on
  consensus + one firm on hardware) is acceptable and often
  faster — flag this in the RFP if interested.
- Conflict-of-interest disclosure: at the time of writing none of
  the maintainers has an undisclosed prior relationship with any
  firm on this list.
