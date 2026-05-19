# B3Chain Repository Map

This is a topographic map of the B3Chain Core repository. Read it
before your first non-trivial change. The goal is to make it cheap to
answer two questions:

1. **"Where does X live?"** — given a feature area, find the file.
2. **"Where do I add X?"** — given a new change, find the right
   subtree and the right neighbours.

If you add, remove, or move a top-level subtree, update this file in
the same PR.

---

## Top-level layout

| Path | Purpose |
|---|---|
| [`src/`](../src) | The `b3chaind` node, wallet, RPC, P2P, mempool, consensus, validation. Forked from Bitcoin Core 30.2.0 with minimal diff. |
| [`src/crypto/`](../src/crypto) | Crypto primitives. **B3PoW-Scratch C++ consensus implementation lives here** (`b3pow_scratch.{h,cpp}`). |
| [`src/pow/`](../src/pow) | Difficulty math and consensus PoW glue. |
| [`src/test/`](../src/test) | C++ unit tests (catch + boost::test). |
| [`src/test/data/`](../src/test/data) | Canonical PoW test vectors (`b3pow_consensus_vectors.json`). |
| [`test/functional/`](../test/functional) | Python functional tests run via `test_runner.py`. |
| [`doc/`](.) | All project documentation: build, design, security, mining, this map. |
| [`doc/whitepaper/`](whitepaper) | B3PoW-Scratch whitepaper Markdown source and pandoc PDF render rig. |
| [`doc/articles/`](articles) | Long-form technical articles (e.g. *Why B3PoW-Scratch?*). |
| [`doc/diagrams/`](diagrams) | Mermaid sources for cross-doc system / algorithm / hardware diagrams. |
| [`doc/security/`](security) | Threat-model and incident-response runbooks (`B3POW-51-ATTACK-ANALYSIS.md`, `RESPONSE-RUNBOOK-51ATTACK.md`). |
| [`doc/analysis/`](analysis) | FPGA feasibility and ASIC-economics analyses extending the spec. |
| [`doc/audit/`](audit) | Third-party audit scope, threat model, RFP. |
| [`doc/economics/`](economics) | Monetary policy, miner incentives, long-run security budget. |
| [`doc/preprint/`](preprint) | IACR ePrint LaTeX source for the academic preprint. |
| [`doc/outreach/`](outreach) | Launch outreach kit (Bitcointalk ANN, HN, Reddit, social, conference targets). |
| [`doc/release-notes/`](release-notes) | Per-release notes (inherited Bitcoin Core history + B3Chain releases). |
| [`doc/man/`](man) | `man(1)` pages for `b3chaind`, `b3chain-cli`, etc. |
| [`doc/SECURITY-*.md`](.) | Inherited and added security posture documents. |
| [`doc/CHANGELOG.md`](CHANGELOG.md) | Human-curated changelog for the B3Chain fork. |
| [`contrib/`](../contrib) | Out-of-band tooling: miners, hardware, RTL, testnet stack, testing, packaging. |
| [`contrib/miner/`](../contrib/miner) | All mining-related code. See subtree table below. |
| [`contrib/testnet/`](../contrib/testnet) | Reference testnet stack (pool, faucet, explorer, status monitor). |
| [`contrib/testing/`](../contrib/testing) | Audit scripts, benchmark suite, regtest harness, verification scripts. |
| [`contrib/testing/bench/`](../contrib/testing/bench) | **B3PoW-Scratch benchmark suite** (CPU/C++/FPGA/verify) + methodology + raw results. |
| [`security/`](../security) | Bug-bounty program, security disclosure tooling, security.txt source. |
| [`depends/`](../depends) | Bitcoin Core depends/ system for reproducible dependency builds. |
| [`build/`](../build) | (gitignored) Out-of-tree build directory created by `cmake`. |
| [`ci/`](../ci) | CI helper scripts called from `.github/workflows/`. |
| [`.github/workflows/`](../.github/workflows) | GitHub Actions: build matrix, RTL CI, release pipeline. |
| [`cmake/`](../cmake) | CMake modules and toolchain files. |
| [`share/`](../share) | Examples, packaging templates, RPC auth tools. |

---

## `src/` — node and consensus

The `src/` tree is Bitcoin Core 30.2.0 with the smallest diff that
makes B3Chain work. Don't churn `src/` for style — the lower the
diff, the cheaper upstream backports become.

| Path | Notes |
|---|---|
| [`src/b3chaind.cpp`](../src/b3chaind.cpp) | Node daemon entry point. |
| [`src/b3chain-cli.cpp`](../src/b3chain-cli.cpp) | RPC CLI. |
| [`src/b3chain-tx.cpp`](../src/b3chain-tx.cpp), [`b3chain-wallet.cpp`](../src/b3chain-wallet.cpp), [`b3chain-util.cpp`](../src/b3chain-util.cpp) | Standalone helper binaries. |
| [`src/chainparams.cpp`](../src/chainparams.cpp) | Chain-id parameters (`bc` → `b3`, ports, genesis, seeds, deployments). **Touch on consensus-affecting changes only.** |
| [`src/consensus/`](../src/consensus) | Consensus rules (block subsidy, max sigops, etc.). |
| [`src/crypto/b3pow_scratch.{h,cpp}`](../src/crypto) | The on-the-wire B3PoW-Scratch consensus implementation in C++. Byte-exact mirror of [`b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py). |
| [`src/crypto/blake3.{h,cpp}`](../src/crypto) | BLAKE3 primitive (full and 2-round reduced variants used by B3PoW-Scratch). |
| [`src/pow/`](../src/pow) | Difficulty target math, retarget, work calculation. |
| [`src/validation.cpp`](../src/validation.cpp) | Block + tx validation pipeline. PoW check calls into `src/crypto/b3pow_scratch.cpp`. |
| [`src/test/`](../src/test) | C++ unit tests. |
| [`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json) | Canonical PoW test vectors. Regenerate with `contrib/miner/b3miner-rtl/ref/gen_vectors.py`. |
| [`src/wallet/`](../src/wallet) | Wallet, descriptors, key management. |
| [`src/rpc/`](../src/rpc) | RPC dispatch, request validation. |
| [`src/qt/`](../src/qt) | Qt5 desktop GUI (`b3chain-qt`). |
| [`src/kernel/`](../src/kernel), [`src/node/`](../src/node), [`src/init.cpp`](../src/init.cpp) | Bitcoin Core kernel/node refactor split. |
| [`src/secp256k1/`](../src/secp256k1), [`src/leveldb/`](../src/leveldb), [`src/minisketch/`](../src/minisketch), [`src/crc32c/`](../src/crc32c), [`src/ipc/`](../src/ipc) | Upstream subtrees. Do not modify locally — patch upstream and resubmit the subtree. |

---

## `test/` — functional and fuzz

| Path | Notes |
|---|---|
| [`test/functional/`](../test/functional) | Python functional tests. Entry point: `test_runner.py`. |
| [`test/fuzz/`](../test/fuzz) | Fuzzing harnesses. |
| [`test/lint/`](../test/lint) | Repo-wide lint and style checks invoked by CI. |
| [`test/util/`](../test/util) | Test fixtures and helpers. |

---

## `contrib/miner/` — mining stack

The mining stack has four implementations of B3PoW-Scratch that **must
remain byte-exact equivalents**. The canonical reference is the Python
file in `b3miner-rtl/ref/`; everything else is graded against it.

| Path | Role |
|---|---|
| [`contrib/miner/b3chain-cpuminer.py`](../contrib/miner/b3chain-cpuminer.py) | Reference CPU miner. Uses `b3pow_ref.b3pow_scratch` via a `PadCache` for correctness. Not competitive on hashrate; intended for protocol validation, pool implementer testing, and regtest mining. |
| [`contrib/miner/b3chain-gpuminer/`](../contrib/miner/b3chain-gpuminer) | **Deprecated.** Targets the retired double-BLAKE3 PoW. Retained for reference only. |
| [`contrib/miner/b3miner-firmware/`](../contrib/miner/b3miner-firmware) | ESP-IDF firmware for the B3Miner-1 host MCU (ESP32-S3). Stratum client, FPGA register I/O, telemetry. |
| [`contrib/miner/b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h`](../contrib/miner/b3miner-firmware/components/b3_fpga/include/b3_fpga_regs.h) | The wire contract between firmware and FPGA. |
| [`contrib/miner/b3miner-hardware/`](../contrib/miner/b3miner-hardware) | KiCad sources, `SCHEMATIC.md` (XCKU5P single-chip card), BOM, mechanical drawings. |
| [`contrib/miner/b3miner-rtl/`](../contrib/miner/b3miner-rtl) | Verilog/SystemVerilog RTL for the B3PoW-Scratch core, Vivado build scripts, sim testbenches. |
| [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) | **Formal B3PoW-Scratch v1.1 specification.** All implementations are graded against this document. |
| [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) | **Canonical Python reference.** Single source of truth for byte-level behaviour. |
| [`contrib/miner/b3miner-rtl/ref/gen_vectors.py`](../contrib/miner/b3miner-rtl/ref/gen_vectors.py) | Regenerates `src/test/data/b3pow_consensus_vectors.json` and `ref/vectors/consensus_vectors.json` in lockstep. |
| [`contrib/miner/b3miner-rtl/ref/vectors/`](../contrib/miner/b3miner-rtl/ref/vectors) | The RTL testbench's mirror of the consensus vectors. |
| [`contrib/miner/integration-guide.md`](../contrib/miner/integration-guide.md) | Third-party miner authors' handbook (header layout, Stratum, share validation, test vectors). |
| [`contrib/miner/tests/`](../contrib/miner/tests) | Smoke and integration tests for the miner stack. |

### Implementation parity table

| Layer | Language | File | Used by |
|---|---|---|---|
| Reference | Python | `contrib/miner/b3miner-rtl/ref/b3pow_ref.py` | `verify-b3pow.py`, `b3chain-cpuminer.py`, vector regen |
| Consensus | C++ | `src/crypto/b3pow_scratch.{h,cpp}` | `b3chaind` block validation |
| Pool | TypeScript | `contrib/testnet/pool/src/lib/b3pow-scratch.ts` (+ `pad-cache.ts`) | Pool share validation |
| Hardware | SystemVerilog | `contrib/miner/b3miner-rtl/src/*.sv` | FPGA core for B3Miner-1 |

Any change to one of these **must** also change the others and
regenerate vectors.

---

## `contrib/testnet/` — reference testnet stack

| Path | Notes |
|---|---|
| [`contrib/testnet/pool/`](../contrib/testnet/pool) | Stratum-V1 reference mining pool (Node/TypeScript). Validates shares via the B3PoW-Scratch TS port. |
| [`contrib/testnet/pool/src/stratum/share-validator.ts`](../contrib/testnet/pool/src/stratum/share-validator.ts) | Where pool share PoW validation lives. |
| [`contrib/testnet/faucet/`](../contrib/testnet/faucet) | Testnet faucet. |
| [`contrib/testnet/explorer/`](../contrib/testnet/explorer) | Block explorer backend. |
| [`contrib/testnet/electrs/`](../contrib/testnet/electrs) | Electrs configuration for the testnet. |
| [`contrib/testnet/monitor/`](../contrib/testnet/monitor) | Node health monitor. |
| [`contrib/testnet/status-monitor/`](../contrib/testnet/status-monitor) | Cron-driven JSON exporter the website's `testnet.html` polls every 60 s. |
| [`contrib/testnet/miner/`](../contrib/testnet/miner) | Helpers for testnet mining (e.g. dispatch scripts). |

---

## `contrib/testing/` — verification, audits, benches

| Path | Notes |
|---|---|
| [`contrib/testing/verify-b3pow.py`](../contrib/testing/verify-b3pow.py) | Verifies the consensus-vector suite + (optionally) live testnet blocks against `b3pow_ref.py`. **Run this before opening any PoW-touching PR.** |
| [`contrib/testing/regtest-simulation.sh`](../contrib/testing/regtest-simulation.sh) | 3-node regtest network exercise: mines 2 016 blocks, sends across wallets, verifies chain consistency. |
| [`contrib/testing/bench/`](../contrib/testing/bench) | B3PoW-Scratch benchmark suite (CPU, C++, FPGA, verifier) + methodology + chart generator + raw results. |
| [`contrib/testing/audit/`](../contrib/testing/audit) | Standalone audit scripts (e.g. supply-cap check). |
| [`contrib/testing/compare/`](../contrib/testing/compare) | Cross-impl comparison helpers (some predate B3PoW-Scratch; check first). |
| [`contrib/testing/tools/`](../contrib/testing/tools) | Misc helper utilities. |
| [`contrib/testing/results/`](../contrib/testing/results) | Standing results outputs (not the bench `results/r0/`). |

---

## `doc/` — documentation

A short menu. The full set lives in [`doc/`](.) — use `ls` and the
file names are self-describing.

| Path | Topic |
|---|---|
| [`doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](whitepaper/B3POW-SCRATCH-WHITEPAPER.md) | The launch whitepaper. |
| [`doc/articles/why-b3pow-scratch.md`](articles/why-b3pow-scratch.md) | The narrative companion to the whitepaper. |
| [`doc/diagrams/`](diagrams) | System / algorithm / scratchpad / hardware diagrams (Mermaid + Makefile). |
| [`doc/b3chain-pow-design.md`](b3chain-pow-design.md) | Design rationale for B3PoW-Scratch v1.1. |
| [`doc/mining.md`](mining.md) | Operator-facing mining documentation. |
| [`doc/stratum.md`](stratum.md) | Pool implementer contract (PoW computation, vectors, pad-caching rules). |
| [`doc/testnet-runbook.md`](testnet-runbook.md) | How to join the public testnet, mine, and watch the explorer. |
| [`doc/pool-operator-guide.md`](pool-operator-guide.md) | How to operate a B3PoW-Scratch share-validating pool. |
| [`doc/security/`](security) | 51%-attack analysis and incident-response runbook. |
| [`doc/SECURITY-*.md`](.) | Security inheritance, roadmap, audit notes. |
| [`doc/analysis/FPGA-FEASIBILITY.md`](analysis/FPGA-FEASIBILITY.md) | KU5P resource usage, MMCM timing, BRAM occupancy. |
| [`doc/analysis/ASIC-ECONOMICS.md`](analysis/ASIC-ECONOMICS.md) | NRE cost, breakeven hashrate, honest "what would an ASIC look like" analysis. |
| [`doc/economics/MONETARY-POLICY.md`](economics/MONETARY-POLICY.md), [`MINER-INCENTIVES.md`](economics/MINER-INCENTIVES.md), [`SECURITY-BUDGET.md`](economics/SECURITY-BUDGET.md) | Tokenomics and long-run security budget. |
| [`doc/audit/SCOPE.md`](audit/SCOPE.md), [`THREAT-MODEL.md`](audit/THREAT-MODEL.md), [`RFP.md`](audit/RFP.md) | Third-party audit prep package. |
| [`doc/preprint/B3POW-SCRATCH-PREPRINT.tex`](preprint/B3POW-SCRATCH-PREPRINT.tex) | IACR ePrint LaTeX source. |
| [`doc/outreach/`](outreach) | Launch outreach templates (Bitcointalk ANN, HN Show HN, Reddit, social). |
| [`doc/release-process.md`](release-process.md) | Release workflow including B3PoW vector regen discipline. |
| [`doc/CHANGELOG.md`](CHANGELOG.md) | Human-curated changelog. |

---

## `.github/workflows/` — CI

| Workflow | Triggers | Purpose |
|---|---|---|
| `ci.yml` (Bitcoin Core inherited) | Push, PR | Cross-platform build + test matrix. |
| `b3miner-rtl.yml` | `contrib/miner/b3miner-rtl/**` changes | RTL pytest vectors, linting, sim where Vivado-free. |
| `release.yml` | Tag push | Deterministic release builds (Guix/Docker), SBOM, Sigstore signing, SHA256SUMS. |
| `benchmark.yml` | Manual / nightly | Reruns the CPU + verifier benches and uploads CSVs. |

---

## "Where do I add X?" decision matrix

| Change | Where it goes | Reviewer expectations |
|---|---|---|
| Consensus rule change | `src/consensus/`, `src/validation.cpp`, `src/chainparams.cpp`. Add functional test under `test/functional/`. | 2 ACKs, activation plan in PR description. |
| PoW algorithm change | All four impls (`b3pow_ref.py`, `b3pow_scratch.cpp`, `b3pow-scratch.ts`, RTL) + regen vectors + update `SPEC.md`. | 2 ACKs, vector parity proven via `verify-b3pow.py`. |
| PoW algorithm bug fix that does *not* change consensus | Same four impls, but call out that on-the-wire bytes are unchanged. | 1–2 ACKs. |
| New RPC | `src/rpc/`, register in `src/rpc/register.h`, add to `doc/JSON-RPC-interface.md`, functional test. | 1 ACK. |
| New wallet behaviour | `src/wallet/`, functional test, doc snippet. | 1 ACK. |
| Mining stack code (host firmware / RTL) | `contrib/miner/b3miner-firmware/` or `b3miner-rtl/`. Update relevant README. | 1 ACK from a miner-stack maintainer. |
| Pool / faucet / explorer | `contrib/testnet/<subproject>/`. Update `doc/testnet-runbook.md` if user-facing. | 1 ACK. |
| Docs only | `doc/`, plus this map if you're adding a tree. | 1 ACK, no test gate. |
| Build system | `cmake/`, `depends/`, or `.github/workflows/`. | 1 ACK, the CI must stay green. |
| New benchmark or audit script | `contrib/testing/bench/` or `contrib/testing/audit/`. Add a row to `methodology.md` if it produces a number cited externally. | 1 ACK. |
| Security policy update | `SECURITY.md` (root), `doc/security/`, or `security/`. | 1 ACK from a maintainer. |

---

## Subtrees that are *not* ours

These directories are upstream subtrees. Submit patches upstream, then
import the new commit here. Do **not** maintain a local fork.

- [`src/secp256k1/`](../src/secp256k1) — upstream: <https://github.com/bitcoin-core/secp256k1>
- [`src/leveldb/`](../src/leveldb) — upstream: <https://github.com/google/leveldb>
- [`src/minisketch/`](../src/minisketch) — upstream: <https://github.com/bitcoin-core/minisketch>
- [`src/crc32c/`](../src/crc32c) — upstream: <https://github.com/google/crc32c>
- [`src/ipc/libmultiprocess/`](../src/ipc/libmultiprocess) — upstream: <https://github.com/chaincodelabs/libmultiprocess>

---

## Quick navigation

| If you're looking for… | Go to |
|---|---|
| The PoW spec | [`contrib/miner/b3miner-rtl/SPEC.md`](../contrib/miner/b3miner-rtl/SPEC.md) |
| The PoW reference impl | [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) |
| The PoW C++ impl | [`src/crypto/b3pow_scratch.cpp`](../src/crypto/b3pow_scratch.cpp) |
| The PoW vectors | [`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json) |
| The whitepaper | [`doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](whitepaper/B3POW-SCRATCH-WHITEPAPER.md) |
| The hardware schematic | [`contrib/miner/b3miner-hardware/SCHEMATIC.md`](../contrib/miner/b3miner-hardware/SCHEMATIC.md) |
| The contributing guide | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
| The code of conduct | [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) |
| The security disclosure path | [`SECURITY.md`](../SECURITY.md) (root) → `security@b3chain.org` |
| The testnet runbook | [`doc/testnet-runbook.md`](testnet-runbook.md) |
| The pool operator guide | [`doc/pool-operator-guide.md`](pool-operator-guide.md) |
| The integration guide for third-party miners | [`contrib/miner/integration-guide.md`](../contrib/miner/integration-guide.md) |
