# External audit — scope of engagement

**Status:** draft for auditor RFP
**Author:** b3chain
**Last updated:** 2026-05-19
**Companion documents:**
[`THREAT-MODEL.md`](THREAT-MODEL.md),
[`RFP.md`](RFP.md),
[`../whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md),
[`../../contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md),
[`../security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md),
[`../SECURITY-AUDIT.md`](../SECURITY-AUDIT.md),
[`../SECURITY-ROADMAP.md`](../SECURITY-ROADMAP.md),
[`../SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md).

---

## 1. Project context

B3Chain is a Bitcoin Core 30.2.0 fork that swaps Bitcoin's SHA-256d
Proof-of-Work for **B3PoW-Scratch v1.1.1** — a memory-hard BLAKE3
variant with a 1 MiB scratchpad, 8 lanes, 2 048 read–modify–write
iterations, and a 50 ms wall-clock verifier budget. UTXO model,
monetary schedule (21 M cap, 210 000-block halving), and block-identity
hash (SHA-256d) are unchanged. The PoW swap is the largest single
consensus diff against upstream and is the reason this audit exists.
The fork is pre-mainnet; testnet (`b3chain-test`) has been running on
`pool.b3chain.org` since 2026-05. This document defines the scope a
contracted auditor is asked to cover.

## 2. Repository pinning

| Field | Value |
|---|---|
| Repository | `https://github.com/b3chain/b3chain` |
| Branch | `b3chain-main` |
| Commit hash (engagement) | `<COMMIT>` (filled in at contract signing) |
| Release tag (if applicable) | `<TAG>` |
| Sibling website repo | `https://github.com/b3chain/b3chain-website` (rev `<WEBSITE_COMMIT>`, scope-relevant only for `/.well-known/security.txt`) |

The auditor should pin to a single commit at engagement start and
re-pin only on the maintainers' written agreement. The maintainers
commit to **not** rewriting history on `b3chain-main` during the
engagement window.

## 3. In-scope code

The audit covers four cross-checked implementations of the same
algorithm plus the hardware integration of one production miner.
"In scope" means the auditor is asked to read and reason about the
file; "byte-exact parity gated by CI" means a mismatch fails the
[`.github/workflows/b3miner-rtl.yml`](../../.github/workflows/b3miner-rtl.yml)
job today, and the auditor is asked to confirm the gate is honest.

### 3.1 Consensus C++ implementation (production validator)

| Path | Role |
|---|---|
| [`src/crypto/b3pow_scratch.{h,cpp}`](../../src/crypto/) | The C++ port of B3PoW-Scratch v1.1.1 (`b3pow::Hash`, `b3pow::InitScratchpad`). Production verifier inside `b3chaind`. |
| [`src/crypto/b3pow_cache.{h,cpp}`](../../src/crypto/) | 2-tier pinned LRU scratchpad cache owned by `ChainstateManager` (M-6 mitigation). |
| [`src/crypto/blake3/`](../../src/crypto/blake3/) | Vendored BLAKE3 C library. Pinned SHA tracked in [`doc/SECURITY-ROADMAP.md §2`](../SECURITY-ROADMAP.md). |
| [`src/pow.{h,cpp}`](../../src/pow.h) | Difficulty math, `CheckProofOfWork`/`CheckProofOfWorkImpl`, B3PoW verifier-budget plumbing. |
| [`src/pow/`](../../src/pow/) | LWMA-3 retarget (`lwma3.{h,cpp}`) and post-bootstrap operating floor. |
| [`src/primitives/block.cpp`](../../src/primitives/block.cpp) | `CBlockHeader::GetPoWHash(prev, pad, budget, &budget_exceeded)`. |
| [`src/validation.cpp`](../../src/validation.cpp) | The validation paths that call into `b3pow_scratch` (`AcceptBlock`, `CheckBlock`, headers-sync). Includes `max_reorg_depth` enforcement (M-4) and the depth-asymmetric verifier budget (M-7). |
| [`src/net_processing.cpp`](../../src/net_processing.cpp) | Peer-scoring on `BLOCK_POW_BUDGET`, depth-aware HEADERS ban score (M-5), `-paranoid-headers-sync` flag (M-10). |
| [`src/kernel/chainparams.cpp`](../../src/kernel/chainparams.cpp) | `enforce_BIP94 = true` on mainnet/testnet/signet (M-2), `powLimit = 0x1d7fffff` + `operating_pow_floor_bits = 0x1d3fffff` (M-13). |
| [`src/consensus/params.h`](../../src/consensus/params.h) | `Consensus::Params` fields the swap touches (`b3pow_verify_budget_ms`, `b3pow_cache_depth`, `max_reorg_depth`, `operating_pow_floor_bits`, `nEarlyDifficultyGuardHeight`). |
| [`src/test/b3pow_scratch_tests.cpp`](../../src/test/b3pow_scratch_tests.cpp), [`src/test/b3pow_cache_tests.cpp`](../../src/test/b3pow_cache_tests.cpp), [`src/test/pow_tests.cpp`](../../src/test/pow_tests.cpp), [`src/test/lwma3_tests.cpp`](../../src/test/lwma3_tests.cpp) | Unit-test surface to be evaluated for adversarial coverage. |
| [`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json) | Canonical PoW vectors (`schema_version=1`, `spec_version=0x00010101`). |

### 3.2 Reference Python implementation (executable spec)

| Path | Role |
|---|---|
| [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) | Pure-Python, no SIMD, byte-for-byte reference. SPEC §10's "source of truth alongside the spec". |
| [`contrib/miner/b3miner-rtl/ref/gen_vectors.py`](../../contrib/miner/b3miner-rtl/ref/gen_vectors.py) | Regenerates `sim/vectors/*.hex` and `src/test/data/b3pow_consensus_vectors.json` from `b3pow_ref.py`. |
| [`contrib/miner/b3miner-rtl/ref/tests/`](../../contrib/miner/b3miner-rtl/ref/tests/) | Pytest suite incl. `test_address_uniformity.py` (M-11 gate). |
| [`contrib/miner/b3miner-rtl/sim/vectors/`](../../contrib/miner/b3miner-rtl/sim/vectors/) | Generated `.hex` vectors consumed by RTL simulation. |
| [`contrib/testing/verify-b3pow.py`](../../contrib/testing/verify-b3pow.py) | End-to-end verifier: re-derives every vector and (optional) every recent live block via RPC. |

### 3.3 Pool TypeScript implementation (independent third validator)

The reference pool stack on `pool.b3chain.org` validates Stratum
shares using a Node/TypeScript port of `b3pow_ref.py`. The auditor
should confirm bit-exact agreement with the C++ and Python impls and
that the pool can never accept a share the node would reject.

| Path | Role |
|---|---|
| [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../../contrib/testnet/pool/src/lib/b3pow-scratch.ts) | TS port of the consensus hash. |
| [`contrib/testnet/pool/src/lib/pad-cache.ts`](../../contrib/testnet/pool/src/lib/pad-cache.ts) | LRU pristine-pad cache, fresh copy per share. |
| [`contrib/testnet/pool/src/lib/header.ts`](../../contrib/testnet/pool/src/lib/header.ts), [`difficulty-math.ts`](../../contrib/testnet/pool/src/lib/difficulty-math.ts) | Header serialisation + share-difficulty math. |
| [`contrib/testnet/pool/src/stratum/share-validator.ts`](../../contrib/testnet/pool/src/stratum/share-validator.ts) | The share-acceptance code path. |
| [`contrib/testnet/pool/package.json`](../../contrib/testnet/pool/package.json), `tsconfig.json` | Node ≥ 20, TypeScript 5.5; deps pinned in `package-lock.json`. |

### 3.4 RTL implementation (production miner)

The B3Miner-1 reference card runs the SystemVerilog RTL listed
below. The auditor is asked to confirm bit-exact parity vs the Python
reference on a large random-header corpus (§5 property 7) and to
read the FSM for obvious failure modes; full timing-closure and
side-channel review are out of scope unless contracted as an add-on.

| Path | Role |
|---|---|
| [`contrib/miner/b3miner-rtl/rtl/b3miner_top.sv`](../../contrib/miner/b3miner-rtl/rtl/b3miner_top.sv) | Top, clock domains, JTAG/SPI fanout. |
| [`contrib/miner/b3miner-rtl/rtl/scratchpad_mem.sv`](../../contrib/miner/b3miner-rtl/rtl/scratchpad_mem.sv) | 8 × 128 KiB BRAM partitions. |
| [`contrib/miner/b3miner-rtl/rtl/scratch_init.sv`](../../contrib/miner/b3miner-rtl/rtl/scratch_init.sv) | BLAKE3-XOF pad seeding (SPEC §6.1). |
| [`contrib/miner/b3miner-rtl/rtl/mixing_core.sv`](../../contrib/miner/b3miner-rtl/rtl/mixing_core.sv) | Per-iteration mix step + lane shuffle. |
| [`contrib/miner/b3miner-rtl/rtl/blake3_compress.sv`](../../contrib/miner/b3miner-rtl/rtl/blake3_compress.sv), [`blake3_xof.sv`](../../contrib/miner/b3miner-rtl/rtl/blake3_xof.sv) | BLAKE3 primitive. |
| [`contrib/miner/b3miner-rtl/rtl/pow_top.sv`](../../contrib/miner/b3miner-rtl/rtl/pow_top.sv) | PoW FSM (controller). |
| [`contrib/miner/b3miner-rtl/rtl/regfile.sv`](../../contrib/miner/b3miner-rtl/rtl/regfile.sv), [`spi_slave.sv`](../../contrib/miner/b3miner-rtl/rtl/spi_slave.sv) | Host control surface. |
| [`contrib/miner/b3miner-rtl/rtl/target_compare.sv`](../../contrib/miner/b3miner-rtl/rtl/target_compare.sv) | 256-bit big-endian compare. |
| [`contrib/miner/b3miner-rtl/rtl/params_pkg.sv`](../../contrib/miner/b3miner-rtl/rtl/params_pkg.sv) | `SPEC_VERSION` constants, parity with `b3pow_ref.py`. |
| [`contrib/miner/b3miner-rtl/docs/`](../../contrib/miner/b3miner-rtl/docs/) | Architecture + HWLOOP notes (background reading). |

### 3.5 Hardware secure-element integration

| Path | Role |
|---|---|
| [`contrib/miner/b3miner-hardware/SCHEMATIC.md`](../../contrib/miner/b3miner-hardware/SCHEMATIC.md) §6.7 | ATECC608B design: slot allocation, pinout, layout rules, provisioning expectations. |
| [`contrib/miner/b3miner-firmware/IMPLEMENTATION.md`](../../contrib/miner/b3miner-firmware/IMPLEMENTATION.md) Phase 4 add | Firmware integration surface for the secure element (`b3_sec` component, `cryptoauthlib` consumption). |
| [`contrib/miner/b3miner-firmware/components/b3_ota/`](../../contrib/miner/b3miner-firmware/components/b3_ota/) | OTA manifest path (manifest signature is verified against an ATECC608B-resident pubkey). |
| [`contrib/miner/b3miner-firmware/components/b3_stratum_v2/`](../../contrib/miner/b3miner-firmware/components/b3_stratum_v2/) | Stratum V2 / Noise NX handshake on the miner side. |

At commit `<COMMIT>` the `b3_sec` component itself is **not yet
implemented** in firmware (the SCHEMATIC.md design is committed; the
matching `cryptoauthlib`-backed code is on the firmware roadmap). The
auditor is asked to (a) review the documented design now and (b) hold
a follow-up review window for the implementation when it lands.

## 4. Out of scope

Explicitly excluded. The auditor is asked to flag any apparent
overlap rather than silently expand scope.

- **Bitcoin Core 30.2.0 inherited consensus paths the fork did not
  touch.** See [`doc/SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md)
  for the per-property `inherited` / `diverged-by-design` inventory.
  Re-auditing Bitcoin Core itself is not the goal of this engagement.
- **Qt GUI** (`src/qt/`). The wallet GUI is a UX surface; review is
  welcome but is not the budget priority of this engagement.
- **Subtree libraries** vendored from upstream and not modified by
  the fork: `src/secp256k1/`, `src/leveldb/`, `src/minisketch/`,
  `src/crc32c/`. Bugs in these libs should be reported upstream.
- **Mining-rig firmware components other than `b3_sec` / `b3_ota` /
  Stratum V2.** The full ESP-IDF firmware tree is open source; we
  scope this engagement to the security-critical components above.
- **Website front-end** (`b3chain-website/`). Static content only;
  bug-bounty handles website vulnerabilities separately.
- **Operational infrastructure** (seed-node SSH posture, nginx
  config, Let's Encrypt automation). Documented in
  [`.cursor/rules/git-push-policy.mdc`](../../.cursor/rules/git-push-policy.mdc);
  bug-bounty handles operational findings.
- **Inherited GUI strings, doxygen project name, and similar
  rebranding-only diffs.** Tracked under
  [`doc/SECURITY-AUDIT.md`](../SECURITY-AUDIT.md) B-2.
- **Physical glitch / fault-injection attacks on consumer-grade
  boards.** Out of scope unless contracted as an add-on (see §8).

## 5. Properties to verify

The auditor is asked to attest to each of the following or to file a
finding when an attestation cannot be supported. "Verify" means
either "construct a counter-example" or "argue an upper / lower
bound" — the auditor chooses the method appropriate to the property.

1. **Byte-exactness across all four implementations.** For every
   header in [`src/test/data/b3pow_consensus_vectors.json`](../../src/test/data/b3pow_consensus_vectors.json),
   the C++ (`src/crypto/b3pow_scratch.cpp`), Python
   (`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`), TypeScript
   (`contrib/testnet/pool/src/lib/b3pow-scratch.ts`), and RTL
   (`contrib/miner/b3miner-rtl/rtl/`) implementations produce the
   identical 32-byte PoW hash.
2. **Memory-hardness lower bound.** The 2 048 RMW iterations form a
   sequential dependency chain that cannot be amortised across nonces
   beyond the initial 32-byte seed (SPEC §8.B "Progress-freeness").
   Confirm no shortcut exists that does fewer than 2 048 dependent
   reads per nonce attempt within a constant memory budget less than
   `SCRATCH_BYTES = 1 MiB` without paying the recompute penalty
   sketched in SPEC §8.C. Specifically check for: time-memory
   trade-off attacks (Hellman 1980 style), pre-image-friendly
   structure that re-uses `pad_init` across distinct prev-hashes,
   and any algebraic linearisation of the `mix_step` round.
3. **Address-uniformity over the 1 MiB scratchpad.** The lane
   address derivation in SPEC §6.3 should produce a distribution
   indistinguishable from uniform over the 11-bit `addr` window per
   lane. CI gates 2²⁰ samples / lane / PR and 2²⁸ samples / lane /
   release tag via
   [`ref/tests/test_address_uniformity.py`](../../contrib/miner/b3miner-rtl/ref/tests/test_address_uniformity.py).
   We request a 2³⁶-sample external check (SPEC §8.E open item).
4. **Verification cost upper bound.** A single-block verifier
   evaluation on a 2026-era reference CPU (Ryzen 9 7950X, one core)
   completes in ≤ 50 ms wall-clock, the
   `Consensus::Params::b3pow_verify_budget_ms` value. The budget is
   enforced by [`b3pow::Hash` in `src/crypto/b3pow_scratch.cpp`](../../src/crypto/b3pow_scratch.cpp)
   with a probe stride of 256 iterations and by the
   `BlockValidationResult::BLOCK_POW_BUDGET` short-circuit in
   [`src/pow.cpp`](../../src/pow.cpp). Confirm the budget cannot be
   exceeded by ≥ 2× under any admissible header / pad combination on
   the reference CPU profile.
5. **No integer overflow or unbounded allocation in the consensus
   path.** Every consensus-reachable allocation (`Pad`,
   `b3pow::Cache`, headers-sync buffer, work-pad heap copy) has a
   compile-time or chainparam-derived upper bound. No arithmetic on
   externally-controlled values (header bytes, `nbits`, peer-supplied
   headers count) can wrap into an under-counted size, or into a
   read past the end of any `std::span` / `std::array`. UB-sanitizer
   builds inherited from Bitcoin Core should report clean over the
   `b3pow_*` test surface.
6. **Pool share validator agrees with consensus for all admissible
   header shapes.** The TS validator
   ([`share-validator.ts`](../../contrib/testnet/pool/src/stratum/share-validator.ts))
   must accept exactly the set of headers `b3chaind` would accept.
   Confirm correct behaviour on the awkward cases: a malformed
   `prev_hash` (wrong length, non-hex, all-zero), an all-zero
   coinbase, headers with `ntime` outside the median-time-past
   window, headers with `version`/`bits` outside chainparams,
   submissions for a stale `jobId`, and submissions whose
   `extranonce2` collides with another worker on the same connection.
7. **RTL functional equivalence vs reference.** Run a corpus of
   ≥ 10 000 random `(header, prev_block_hash)` pairs through both the
   Python reference and the RTL simulation
   ([`contrib/miner/b3miner-rtl/sim/`](../../contrib/miner/b3miner-rtl/sim/))
   and confirm bit-exact agreement on the final `pow_hash`. The
   in-tree gate runs ~5 000 vectors today; a 10 000+ random corpus
   from the auditor would close the open item in
   [SPEC §8.E](../../contrib/miner/b3miner-rtl/SPEC.md#8-security-argument-informal).
8. **ATECC608B secure-element integration (when implemented).**
   Confirm that (a) the slot-0 device key generated on-chip is
   non-exportable for the lifetime of the part, (b) the firmware
   ECDSA-signing path uses the secure element rather than any
   software fallback, (c) the OTA manifest verification path checks
   the slot-2 release-signing pubkey before booting a new image,
   and (d) I²C-bus probing cannot extract the slot-1 (Stratum V2
   Noise NX static private) key. Schematic basis:
   [`SCHEMATIC.md §6.7.4`](../../contrib/miner/b3miner-hardware/SCHEMATIC.md).
9. **Stratum V2 / Noise NX handshake correctness (if shipping in the
   audited build).** The firmware Stratum V2 component
   ([`b3_stratum_v2/`](../../contrib/miner/b3miner-firmware/components/b3_stratum_v2/))
   establishes a Noise NX session against the pool's
   `SignedCertificate` authority binding (see
   [`doc/SECURITY-AUDIT.md`](../SECURITY-AUDIT.md) P-2). Confirm
   correct cipher selection (X25519 / ChaCha20-Poly1305 / BLAKE2s),
   no nonce-reuse across reconnects, and that a tampered server
   certificate is rejected before any share is submitted.

## 6. Deliverables expected

1. **Written report**, suitable for public publication on
   `b3chain.org`, listing every finding with code references at the
   pinned commit.
2. **Severity-ranked findings**, using Critical / High / Medium /
   Low / Informational, with a one-line summary per finding plus a
   detailed write-up.
3. **Reproducer cases**, ideally as patches against the pinned
   commit or as standalone scripts under
   `contrib/audit-reproducers/<auditor>-<finding-id>/`.
4. **Remediation suggestions**, calibrated to the maintainers' diff
   discipline (small, reviewable, traceable to the finding).
5. **Optional follow-up review** of the maintainers' remediations,
   priced separately. We expect to ship fixes within four weeks of
   the report; the follow-up confirms the fixes match the findings.

## 7. Methodology hints

The maintainers do not prescribe methodology — these are notes on
what we expect to be productive given the construction.

- **Manual code review** of the C++ consensus path is the largest
  expected line item. Cross-reference against the Python reference
  rather than the spec text alone; the Python reference is the
  declarative source of truth (SPEC §10).
- **Vector-equivalence fuzzing**: feed random `(header,
  prev_block_hash)` pairs into each of the four impls and assert
  bit-exact agreement. Existing harness:
  [`contrib/testing/verify-b3pow.py`](../../contrib/testing/verify-b3pow.py)
  (covers Python ↔ JSON-vectors today; trivial to extend).
- **Differential fuzzing across impls** (C++ ↔ Python ↔ TS ↔ RTL).
  The simplest extension wires `b3powScratch` (TS) into the verify
  script over a child-process boundary; the harder one drives RTL
  cosim via the existing
  [`contrib/miner/b3miner-rtl/sim/`](../../contrib/miner/b3miner-rtl/sim/)
  testbench.
- **FPGA simulation parity** with reference vectors. The RTL CI
  ([`b3miner-rtl.yml`](../../.github/workflows/b3miner-rtl.yml))
  exercises ~5 000 vectors per run; an external 10 000+ corpus
  closes property §5.7.
- **Hardware glitch attacks** (clock glitching, EMFI, voltage
  glitching against the ATECC608B or the FPGA configuration plane)
  are out of scope for v1 unless contracted as an add-on. We do not
  claim physical-attack resistance on the consumer-grade reference
  card.

## 8. Suggested engagement size and timeline

The auditor's own scoping supersedes the figures below; these are
the maintainers' rough expectations to calibrate proposals.

| Engagement | Duration | Scope coverage |
|---|---|---|
| **Lite** | ~2 weeks | C++ consensus path (§3.1) only; properties §5.1, §5.4, §5.5. |
| **Standard** | ~4–6 weeks | §3.1 + §3.2 + §3.3 (consensus across impls); properties §5.1–§5.6 + §5.9. |
| **Deep** | ~8+ weeks | All of §3, including RTL parity at scale (§3.4) and the documented ATECC608B / Stratum V2 surfaces (§3.5); all properties §5.1–§5.9. |

[`doc/SECURITY-ROADMAP.md §4`](../SECURITY-ROADMAP.md) earmarks a
$40K–$120K USD budget bracket depending on scope; final pricing is
left to the auditor's quote in response to the
[RFP](RFP.md).

## 9. References

- Whitepaper: [`doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md)
- Formal spec: [`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md)
- 51%-attack analysis: [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md)
- Incident-response runbook: [`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](../security/RESPONSE-RUNBOOK-51ATTACK.md)
- Self-audit baseline: [`doc/SECURITY-AUDIT.md`](../SECURITY-AUDIT.md)
- Inheritance audit: [`doc/SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md)
- Security roadmap: [`doc/SECURITY-ROADMAP.md`](../SECURITY-ROADMAP.md)
- Threat model (sibling): [`THREAT-MODEL.md`](THREAT-MODEL.md)
- Auditor RFP template: [`RFP.md`](RFP.md)
- Bug bounty: [`../../security/bug-bounty.md`](../../security/bug-bounty.md)
