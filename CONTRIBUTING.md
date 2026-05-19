# Contributing to B3Chain Core

B3Chain Core is forked from Bitcoin Core and inherits Bitcoin Core's
open contributor model: anyone is welcome to contribute through peer
review, testing, and patches. This document explains the practical
process and expectations for landing a change.

The tone is deliberately conservative. B3Chain is a Layer 1 PoW
blockchain that holds user funds; we will rather take longer to merge a
patch than land one we do not understand.

## Contents

- [1. Getting started](#1-getting-started)
- [2. Repository layout](#2-repository-layout)
- [3. Communication channels](#3-communication-channels)
- [4. Branching and pull-request workflow](#4-branching-and-pull-request-workflow)
- [5. Commit hygiene](#5-commit-hygiene)
- [6. Sign-offs, DCO, and signed commits](#6-sign-offs-dco-and-signed-commits)
- [7. Required tests by change class](#7-required-tests-by-change-class)
- [8. Code style](#8-code-style)
- [9. What NOT to commit](#9-what-not-to-commit)
- [10. Security disclosure](#10-security-disclosure)
- [11. License](#11-license)
- [12. Maintainers and review](#12-maintainers-and-review)

---

## 1. Getting started

### 1.1 Build

Building B3Chain Core uses the same toolchain as Bitcoin Core. Pick the
guide for your platform:

| Platform | Doc |
|---|---|
| Linux | [`doc/build-unix.md`](doc/build-unix.md) |
| macOS | [`doc/build-osx.md`](doc/build-osx.md) |
| Windows (cross) | [`doc/build-windows.md`](doc/build-windows.md) |
| Windows (MSVC) | [`doc/build-windows-msvc.md`](doc/build-windows-msvc.md) |
| FreeBSD | [`doc/build-freebsd.md`](doc/build-freebsd.md) |
| NetBSD | [`doc/build-netbsd.md`](doc/build-netbsd.md) |
| OpenBSD | [`doc/build-openbsd.md`](doc/build-openbsd.md) |

A typical Linux build:

```bash
mkdir build && cd build
cmake ..
cmake --build . -j$(nproc)
```

Binaries are emitted as `b3chaind`, `b3chain-cli`, `b3chain-tx`,
`b3chain-wallet`, and (when configured) `b3chain-qt`.

### 1.2 Run the test suites

Before opening a PR, run the test suites your change is likely to touch.
See section [7. Required tests by change class](#7-required-tests-by-change-class)
for a full per-change matrix; at minimum:

```bash
cd build

# C++ unit tests (catch + boost::test)
ctest --output-on-failure

# Python functional tests
python3 ../test/functional/test_runner.py

# B3PoW-Scratch end-to-end verifier (consensus vectors)
pip3 install blake3
python3 ../contrib/testing/verify-b3pow.py
```

Reference current status from `README.md`: 148 C++ unit tests pass,
258 functional tests pass, 17/17 B3PoW-Scratch consensus vectors pass.

### 1.3 Regtest

A scripted three-node regtest network is provided:

```bash
bash contrib/testing/regtest-simulation.sh
```

It mines 2,016 blocks, exercises wallet send/receive across nodes, and
verifies chain consistency. Current expected output: 19/19 checks pass.

### 1.4 Finding something to work on

- Issues labelled `good first issue` on
  <https://github.com/b3chain/b3chain/issues> are deliberately scoped
  for new contributors.
- The roadmap and open audit items live in
  [`doc/SECURITY-ROADMAP.md`](doc/SECURITY-ROADMAP.md).
- Each subtree under `contrib/` carries its own README with open
  fill-in items (e.g.
  [`contrib/miner/b3miner-firmware/README.md`](contrib/miner/b3miner-firmware/README.md)
  has a "Fill-in checklist (skeleton → production)" section).

You do not need permission to start work. Leaving a comment on the
issue is encouraged so others can see it is being addressed.

---

## 2. Repository layout

A topographic map of the repo lives in
[`doc/REPO-MAP.md`](doc/REPO-MAP.md). Read it before your first
non-trivial change — it tells you where consensus code, RPC, wallet,
PoW, RTL, firmware, pool, tests, and docs each live, and includes a
"where do I add X?" decision matrix.

If you make a change that adds, removes, or moves a top-level subtree,
update `doc/REPO-MAP.md` in the same PR.

---

## 3. Communication channels

The project uses these channels (in approximate descending order of
formality and persistence):

| Channel | Purpose |
|---|---|
| GitHub issues — <https://github.com/b3chain/b3chain/issues> | Bugs, feature requests, design discussions. Use issues for anything that should outlive a chat thread. |
| GitHub pull requests | Code review. |
| GitHub Discussions — <https://github.com/b3chain/b3chain/discussions> | Open-ended questions, RFCs prior to issue. |
| Discord / Matrix (announced post-launch) | Real-time chat. Bridge URLs added to this document once the bridge is stood up. |
| `dev@b3chain.org` mailing list (post-launch) | Long-form discussion. Mirrors the Bitcoin Core `bitcoindev` model. |
| `security@b3chain.org` | Security disclosure only — see section [10](#10-security-disclosure). |

Do not use Discord or Matrix for anything load-bearing (decisions,
specs, agreements). Any decision that affects merged code must be
recorded in an issue or PR.

For complex or potentially-controversial consensus or P2P changes,
post a short design RFC as a GitHub Discussion *before* opening a PR.
A PR is not the right place to debate whether something should exist.

---

## 4. Branching and pull-request workflow

B3Chain follows the **fork-PR model**:

1. Fork <https://github.com/b3chain/b3chain> on GitHub.
2. Create a topic branch off the latest `b3chain-main`. Branch names
   are not normative; descriptive is better than clever
   (`fix-stratum-vardiff-race`, not `fix-thing`).
3. Push to your fork.
4. Open a PR against `upstream/b3chain-main`.

`b3chain-main` is the integration branch. It is intended to be
buildable and test-clean at every commit; if you find it isn't, that's
a bug worth filing.

### 4.1 Rebasing vs merging

Rebase your topic branch on top of `b3chain-main` before requesting
review. Do **not** add merge commits from upstream into your topic
branch — they make the history hard to read. Force-pushing your topic
branch after review feedback is expected and welcome; reviewers will
look at the "Files changed" tab, not at individual commits.

### 4.2 PR scope

A good PR does one thing. If your change is a refactor *and* a feature,
split it. The reviewer's question "could I review the refactor alone
without thinking about the feature?" should be answerable yes.

For very large changes (anything over ~1,500 lines diff, or any
consensus change of any size), open an issue or RFC discussion first.

### 4.3 PR description

The PR description is the contract you offer the reviewer. Include:

- **What** changed (1-2 sentences).
- **Why** it changed (the actual motivation, not "fix bug").
- **How** to verify (commands, vectors, regtest steps).
- **Risk** assessment (consensus / P2P / wallet / non-consensus
  /docs-only). Spell it out — the reviewer will not infer.
- For consensus changes, the **deployment** plan (pre-genesis hard fork
  / soft fork via versionbits / activation height).

If a PR closes an issue, use the GitHub `Closes #N` syntax.

### 4.4 Conventional-commits-lite

We do not enforce strict
[Conventional Commits](https://www.conventionalcommits.org/), but
commit subjects should start with a scope tag drawn from the table
below, followed by a colon and an imperative present-tense summary:

| Scope | Used for |
|---|---|
| `consensus:` | Consensus-affecting code. Triggers extra review and the consensus test matrix. |
| `pow:` | B3PoW-Scratch reference, C++, TS, RTL, or firmware changes. |
| `p2p:` | Network protocol, peer management. |
| `wallet:` | Wallet, descriptors, key management. |
| `rpc:` | RPC interface. |
| `node:` | `b3chaind`, init, chain state. |
| `mempool:` | Mempool, transaction relay. |
| `qt:` | Qt GUI. |
| `build:` | CMake, depends, packaging. |
| `ci:` | CI configuration (`.github/workflows/`). |
| `test:` | Tests-only changes. |
| `doc:` | Documentation-only changes (no code). |
| `rtl:` | `contrib/miner/b3miner-rtl/`. |
| `firmware:` | `contrib/miner/b3miner-firmware/`. |
| `hardware:` | `contrib/miner/b3miner-hardware/`. |
| `pool:` | `contrib/testnet/pool/`. |
| `miner:` | `contrib/miner/b3chain-cpuminer.py`, `b3chain-gpuminer/`. |
| `chore:` | Tooling, formatting, deps without behaviour change. |

Examples:

```
pow: tighten ITER_MUL[7] uniformity gate to 2^22 samples
consensus: enforce max_reorg_depth = 200 at activation height
doc: REPO-MAP add audit subtree
pool: fix vardiff retune race on disconnect during set_difficulty
```

Subject lines are ≤ 72 characters. Body is wrapped at 72 characters.

### 4.5 Review

Two reviewer ACKs are required for any consensus change; one for
anything else. ACKs use Bitcoin-Core-style nomenclature:

| Marker | Meaning |
|---|---|
| `ACK <hash>` | "I have reviewed this commit hash and am satisfied with its content." |
| `utACK <hash>` | "Untested ACK — I read the code and it looks right; I did not run it." |
| `tACK <hash>` | "Tested ACK — I ran it (specify how)." |
| `Concept ACK` | "I agree with the goal; I have not finished reviewing the code." |
| `NACK` | "I object." NACKs must explain *why*. |

Maintainers will only merge a PR with at least one explicit ACK on the
final commit hash. A `Concept ACK` is not sufficient to merge.

### 4.6 Backports

Upstream Bitcoin Core security and non-consensus fixes are cherry-picked
into B3Chain on a periodic cadence. If you spot a missing backport, open
an issue. PRs that cherry-pick should keep the original author's
attribution and prefix the subject `(cherry-pick) ` if the patch was
modified, leaving the original Bitcoin Core commit message intact.

---

## 5. Commit hygiene

- Each commit must compile and pass its directly-affected tests. We
  use `git bisect` to find regressions; broken intermediate commits
  defeat it.
- Avoid drive-by reformatting in the same commit as a logic change.
- Keep diff hunks small and reviewable. Reviewers do not have infinite
  patience.
- Reference issue or PR numbers in the commit body only when relevant;
  do not pollute the subject with `(#1234)`.
- If you generate code (e.g. with a code-generation script), commit the
  generator change and the generated change as separate commits.

### 5.1 Commit message template

```
<scope>: <imperative present-tense subject, ≤72 chars>

<longer body, wrapped at 72 chars; explain WHY, not just what.
Reference relevant SPEC sections, issues, or upstream commits.>

<optional footer with metadata, blank-line-separated, e.g.>

Closes: #123
Refs: doc/security/B3POW-51-ATTACK-ANALYSIS.md §3.4

Signed-off-by: Pat Contributor <pat@example.com>
```

---

## 6. Sign-offs, DCO, and signed commits

### 6.1 DCO sign-off (required)

Every commit must carry a Developer Certificate of Origin sign-off
line:

```
Signed-off-by: Pat Contributor <pat@example.com>
```

You can append it automatically with `git commit -s`. The name and
email must match a real identity that you are willing to be reached at;
pseudonyms are accepted provided the address resolves to you.

By signing off, you certify the
[DCO v1.1](https://developercertificate.org/) — in short, that you have
the right to submit the patch under the project's MIT license.

A PR with unsigned commits will be asked to amend. Use
`git rebase --signoff` to add sign-offs retroactively.

### 6.2 Signed commits (recommended)

Cryptographically-signed commits are strongly recommended, especially
for anyone seeking commit access in the future. Use GPG or SSH commit
signing as supported by GitHub:

```bash
git config commit.gpgsign true
git config user.signingkey <KEYID>
```

The maintainer GPG fingerprints will be published in
[`doc/security/MAINTAINER-KEYS.md`](doc/security/MAINTAINER-KEYS.md)
(*placeholder — to be populated at launch*). Until then, the only key
fingerprints that should be trusted for release artifacts are the ones
published on <https://b3chain.org> over TLS.

### 6.3 Merging maintainer's view

When a maintainer merges, they will:

1. Verify the PR has the required ACKs on the final commit hash.
2. Squash only at the author's request (default is to preserve
   individual commits).
3. Add a merge commit with the PR number and a summary of the review
   trail in the body.
4. Push to `b3chain-main`.

---

## 7. Required tests by change class

Treat this table as the minimum bar. A PR may need *more* than this if
the maintainer asks; it should rarely need less.

| Change class | What it is | Tests required |
|---|---|---|
| Consensus | Anything in `src/consensus/`, `src/pow.cpp`, `src/validation.cpp`, `src/chainparams.cpp`, `src/crypto/b3pow_scratch.cpp`, `src/script/`, `src/primitives/`, `src/policy/` consensus-impacting paths. | Full `ctest` + full functional test runner + `verify-b3pow.py` + `regtest-simulation.sh` + a new functional test that demonstrates the new behaviour. Two-reviewer ACK and explicit risk analysis in the PR body. |
| Non-consensus C++ | RPC, P2P, wallet, mempool relay policy. | `ctest` on changed targets + relevant functional tests + new tests covering the change. One-reviewer ACK. |
| Documentation | Anything under `doc/`, `README.md`, `CONTRIBUTING.md`, `*.md` in `contrib/`. | Build the doc locally if it is rendered (e.g. Doxygen-touching changes). Pure-text changes need only a careful re-read. |
| Build / CI | `CMakeLists.txt`, `cmake/`, `.github/workflows/`, `depends/`, `ci/`. | Demonstrate that the affected CI job passes on your fork before requesting review. For depends changes, link to a successful Guix-reproducible build. |
| RTL | `contrib/miner/b3miner-rtl/rtl/`. | `make ref-test`, `make lint`, `make sim`. For changes that affect interpretation, also run the parity tests against `src/test/data/b3pow_consensus_vectors.json`. |
| Firmware | `contrib/miner/b3miner-firmware/`. | ESP-IDF build clean on `esp32s3`. Where applicable, hardware-in-loop bring-up against a real B3Miner-1 board (note in PR description). |
| Pool (TypeScript) | `contrib/testnet/pool/`. | `npm test`. Include the parity test against `b3pow_consensus_vectors.json`. For Stratum-protocol changes, a recorded session against the reference cpuminer. |
| Miners | `contrib/miner/b3chain-cpuminer.py`, `contrib/miner/b3chain-gpuminer/`. | `contrib/miner/tests/run_tests.py` clean. JSONL replay against `verify-b3pow.py`. |
| Reference Python | `contrib/miner/b3miner-rtl/ref/`. | `pytest contrib/miner/b3miner-rtl/ref/tests/` clean. Re-derive every entry in `b3pow_consensus_vectors.json`. |

### 7.1 Consensus changes — extra hurdles

A consensus change is a change to the rules of valid blocks or
transactions. Examples: tweaking
`Consensus::Params::b3pow_verify_budget_ms`, modifying the LWMA-3
difficulty algorithm, altering script validation, changing the
B3PoW-Scratch algorithm parameters.

Consensus PRs must additionally:

1. Be opened against `b3chain-main` only (no consensus changes are
   merged through `release/*` branches without a fresh PR).
2. Include a **deployment plan**: pre-genesis hard fork; soft fork via
   versionbits with a specified activation height window; emergency
   activation. Reference
   [`doc/SECURITY-ROADMAP.md`](doc/SECURITY-ROADMAP.md) for in-flight
   plans.
3. Include a **rollback story**: how would the change be unwound if it
   misbehaves? Some changes cannot be unwound; say so explicitly.
4. Carry two reviewer ACKs from distinct maintainers, at least one of
   whom should have *not* been involved in writing the patch.
5. Be sanity-checked against the **51% threat model**:
   [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](doc/security/B3POW-51-ATTACK-ANALYSIS.md).
   Explain in the PR body whether the change weakens, strengthens, or
   leaves unchanged each of the mitigations M-1 through M-13.

### 7.2 Reproducible builds

Releases are built via the Guix-pinned `depends/` system. Changes
under `depends/` need a reproducible-build demonstration before merge.
See [`doc/release-process.md`](doc/release-process.md) for the binary
release procedure.

---

## 8. Code style

We inherit Bitcoin Core's style discipline. The summary below is the
minimum bar; if in doubt, read [`doc/developer-notes.md`](doc/developer-notes.md).

### 8.1 C++ (C++17)

- Standard: **C++17**, same as Bitcoin Core.
- Style enforced by [`src/.clang-format`](src/.clang-format) and
  [`src/.clang-tidy`](src/.clang-tidy). Run `clang-format --style=file`
  on new files; do not reformat unrelated lines.
- Pointer/reference style: `Type* var`, `Type& var` (asterisk and
  ampersand bind to the type, not the name).
- 4-space indentation, no tabs, LF line endings.
- Prefer `enum class` over plain `enum`.
- Prefer `std::span` / `std::string_view` over `(ptr, len)` pairs.
- Never use `using namespace std;` at file scope.
- No exceptions in consensus-critical paths; return values or
  `std::optional` instead. Existing exceptions in non-consensus code
  are tolerated where they replace what would otherwise be a `throw`
  several layers up.
- Header guards: `#ifndef BITCOIN_<PATH>_H` (preserved from upstream
  Bitcoin Core; we do not retag these).
- New consensus code must use the `Consensus::*` namespace and live
  under `src/consensus/` or `src/crypto/` as appropriate.

### 8.2 Python (PEP 8)

- Target Python 3.10+ (the `.python-version` file pins the test
  framework's version).
- Follow PEP 8 + Bitcoin Core's test-framework conventions.
- 4-space indentation, no tabs.
- Use `f-strings`; do not use `%`-style formatting in new code.
- Type hints are encouraged for non-trivial functions (`def foo(x:
  bytes) -> int:`).
- For test framework changes, follow the patterns in
  `test/functional/test_framework/`.
- Linting: `flake8` config in `test/lint/`; run via `test/lint/lint-all.py`.

### 8.3 TypeScript (strict mode)

- Target: TypeScript 5.x, `strict: true`, `noImplicitAny: true`.
- `tsconfig.json` per package; do not loosen `strict` in a PR.
- Prefer `unknown` over `any`. Where `any` is unavoidable, comment
  why.
- Async code: `async/await`, never raw `.then()` chains in new code.
- Lints: `npm run lint` in each package directory.

### 8.4 SystemVerilog

- Style is enforced by the project's Verilator lint config
  (`contrib/miner/b3miner-rtl/ci/verilator.cfg`).
- Module headers use the convention shown in
  [`contrib/miner/b3miner-rtl/rtl/blake3_compress.sv`](contrib/miner/b3miner-rtl/rtl/blake3_compress.sv).
- All parameters live in `params_pkg.sv` and are mirrored in the C
  header `b3_fpga_regs.h`.

### 8.5 Shell / scripts

- POSIX `sh` where portable. Bash extensions are acceptable in scripts
  that are clearly tagged `#!/usr/bin/env bash`.
- ShellCheck-clean. Configure via `.shellcheckrc` where needed.

### 8.6 Markdown

- One sentence per line is **not** required; we wrap at ~72 characters
  for readability.
- Use ATX-style headers (`#`, `##`, ...).
- Tables use the GitHub-flavoured pipe syntax.
- Cross-reference siblings with relative links
  (`[stratum.md](stratum.md)`, not absolute URLs to GitHub).

---

## 9. What NOT to commit

The repo is source-only with tightly-scoped exceptions. Do not commit:

- **Binary build artifacts.** `*.o`, `*.a`, `*.so`, compiled bitstreams
  (`*.bit`, `*.bin` from RTL builds), `*.elf` firmware images,
  packaged installers. The `.gitignore` excludes the usual suspects;
  if you add a new artifact format, extend `.gitignore` instead of
  committing it.
- **Generated test vectors that have an in-tree generator.** Vectors
  are committed only at `src/test/data/b3pow_consensus_vectors.json`
  (canonical) and `contrib/miner/b3miner-rtl/sim/vectors/`. Both have
  generators. Edit the generator and re-derive.
- **Secrets.** API keys, private keys, `.env` files, JWT signing keys,
  ATECC608B provisioning keys. Use `.env.example` templates instead.
  The CI lint job will reject commits that match common secret
  patterns; do not try to work around it.
- **Personal IDE configuration.** `.vscode/`, `.idea/`, `*.swp`. These
  belong in your global `~/.gitignore`.
- **Large opaque blobs.** Anything > 1 MB that isn't text needs an
  explicit case in the PR description. Photographs of hardware live in
  `contrib/miner/b3miner-hardware/pcb/` and are tolerated; CI logs and
  recorded sessions do not.
- **Datasets that the project does not maintain.** Reference vectors
  for upstream-licensed primitives are fine; downloaded blockchains,
  RPC dumps, or audit-time recordings are not.
- **Auto-generated boilerplate from tools.** If your change includes
  thousands of lines of "regenerate-on-build" output, separate it from
  the source change and include the generator command in the commit
  body.
- **Copies of upstream code.** When pulling code from upstream Bitcoin
  Core, BLAKE3, or wyhash, retain the original license header
  unchanged and document the source in a top-of-file comment.

When in doubt, ask in the PR before pushing the artifact.

---

## 10. Security disclosure

Security issues are reported privately, not through GitHub issues.

### 10.1 Reporting channels

| Channel | Use |
|---|---|
| Email to `security@b3chain.org` (PGP-encrypted preferred) | The primary channel. The PGP key fingerprint is `(placeholder — to be published at launch, see security/SECURITY.md)`. |
| GitHub private vulnerability report (Security tab → "Report a vulnerability") | Equivalent fallback if email is impractical. |

Full policy in [`security/SECURITY.md`](security/SECURITY.md) (this is
the GitHub-convention top-level SECURITY.md the security tab will
link to).

### 10.2 Responsible disclosure

We use a **90-day responsible disclosure** timeline by default:

- Day 0: report received, acknowledgement within 24 hours.
- Days 0–7: triage and severity assessment (criteria in `security/SECURITY.md`).
- Days 7–60 (severity-dependent): fix developed under embargo with
  the reporter.
- Days 60–90: coordinated release window.
- Day 90: public disclosure, with or without reporter coordination if
  the embargo expires.

Critical vulnerabilities (e.g. consensus split, fund-loss) may justify
faster disclosure or a longer embargo by mutual agreement. The
reporter's preference is respected within the 90-day envelope.

### 10.3 What NOT to do

- Do not open a public GitHub issue describing an unpatched vulnerability.
- Do not test exploits on mainnet or any third-party node you do not own.
- Do not exfiltrate user data even where a vulnerability would
  trivially allow it.

### 10.4 Recognition

Credit is offered in two forms: a CVE-style advisory mention at the
fix's release (see `doc/release-notes/`) and inclusion in the bug
bounty hall of fame
([`security/bug-bounty.md`](security/bug-bounty.md)).

### 10.5 Bounties

A bug bounty programme is described in
[`security/bug-bounty.md`](security/bug-bounty.md). It is a programme
stub until mainnet launch, at which point a treasury-funded bounty
becomes active for the categories defined there.

---

## 11. License

B3Chain Core is released under the **MIT license**, inherited from
Bitcoin Core. See [`COPYING`](COPYING) for the full text and
<https://opensource.org/license/MIT> for the canonical license.

By submitting a patch with a DCO sign-off, you agree that your
contribution is licensed under the MIT terms. We will not accept
contributions under a different license.

Third-party dependencies retain their own licenses:

- BLAKE3 reference C / assembly (`src/crypto/blake3/`) — CC0-1.0 or
  Apache-2.0, per the BLAKE3 project.
- LevelDB (`src/leveldb/`) — BSD-3-Clause.
- minisketch (`src/minisketch/`) — MIT.
- secp256k1 (`src/secp256k1/`) — MIT.

Each subtree retains its original `LICENSE`/`COPYING` file unchanged.

---

## 12. Maintainers and review

There is no privileged class of "B3Chain developers". The project is a
meritocracy: trust is earned through review, testing, and merged
contributions. A short list of repository maintainers — the people with
merge access — is published in
[`doc/MAINTAINERS.md`](doc/MAINTAINERS.md) (*placeholder — to be
populated at launch*).

Maintainer responsibilities:

- Review and merge PRs against `b3chain-main`.
- Drive the release cycle described in
  [`doc/release-process.md`](doc/release-process.md).
- Coordinate security disclosure (see section 10).
- Maintain `doc/CHANGELOG.md` and the per-release notes under
  `doc/release-notes/`.

Becoming a maintainer is not a goal in itself. The route is:
contribute substantively, review substantively, and demonstrate
consistent good judgement over a period of months. There is no fixed
threshold; current maintainers will propose candidates publicly and
gather feedback before extending merge access.

---

## Appendix A — Quick reference

| Task | Command |
|---|---|
| Build (Linux) | `mkdir build && cd build && cmake .. && cmake --build . -j$(nproc)` |
| C++ unit tests | `ctest --output-on-failure` (from `build/`) |
| Functional tests | `python3 ../test/functional/test_runner.py` |
| B3PoW verifier (vectors) | `python3 contrib/testing/verify-b3pow.py` |
| B3PoW verifier (live) | `python3 contrib/testing/verify-b3pow.py --rpc-port=18545` |
| Regtest sim | `bash contrib/testing/regtest-simulation.sh` |
| Lint Python | `test/lint/lint-all.py` |
| Lint shell | `shellcheck contrib/**/*.sh` |
| Sign off a commit | `git commit -s -m "..."` |
| Re-sign a series | `git rebase --signoff <base>` |
| GPG-sign a commit | `git commit -S -m "..."` |
| Find good first issues | <https://github.com/b3chain/b3chain/issues?q=is%3Aopen+label%3A%22good+first+issue%22> |

## Appendix B — Frequently-asked questions

**Q. My PR's CI is failing in a job I didn't touch. Is that my problem?**

Yes, until proven otherwise. Pull the latest `b3chain-main`, rebase,
and re-push. If the failure persists, comment in the PR with the CI
log link.

**Q. Can I open a PR that just adds tests?**

Yes, and we love these. Open as `test:` with a description of what
gap is being closed.

**Q. Can I open a PR that just fixes typos in documentation?**

Yes, and we love these even more. Open as `doc:`.

**Q. Can I open a PR that just deletes code?**

Probably, if the code is dead and unreferenced. Demonstrate it is dead
in the PR description (search results, build-after-delete, tests pass).
Removing live code requires the same scrutiny as adding it.

**Q. I want to port a Bitcoin Core PR. How do I do that?**

Cherry-pick the upstream commits, resolve conflicts (especially around
PoW-touching files), update the commit body with the upstream PR
number, and open as a PR with subject `(cherry-pick from bitcoin#N) ...`.
Include in the PR description the upstream URL and any deviations.

**Q. The reference cpuminer is too slow. Can I add a Rust implementation?**

If you want to: yes, but in your own fork first. The maintained
reference implementations are the ones listed in
[`contrib/miner/b3miner-rtl/SPEC.md`](contrib/miner/b3miner-rtl/SPEC.md)
§11. Adding a new reference implementation to the in-tree set requires
parity tests against the JSON consensus vectors and a maintainer's
agreement that the project benefits from carrying it.

---

For anything not covered above, ask in a GitHub Discussion or open an
issue. We would rather answer the question than have the work
duplicated.
