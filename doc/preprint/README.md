# B3PoW-Scratch v1.1 — IACR ePrint preprint

This directory holds the LaTeX source for the IACR ePrint preprint
of B3PoW-Scratch v1.1.

| File | Role |
|---|---|
| [`B3POW-SCRATCH-PREPRINT.tex`](B3POW-SCRATCH-PREPRINT.tex) | Preprint source (XeLaTeX). |
| [`references.bib`](references.bib) | BibTeX bibliography. |
| [`Makefile`](Makefile) | `make` builds the PDF; `make check` runs lint. |
| [`.gitignore`](.gitignore) | LaTeX build artefacts; the PDF is built locally and not committed. |

## What this is

The [launch whitepaper](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) is
the **public-facing** description of B3PoW-Scratch v1.1. This
**preprint** is its academic-format cousin: shorter, denser, in
Springer LNCS layout, with proper citations and reduced marketing
framing. It targets:

- IACR ePrint archive (<https://eprint.iacr.org/>) as the first
  publication step;
- subsequent submission to a peer-reviewed venue (see
  "Suggested venues" below);
- review by named cryptographers and PoW researchers (see
  "Reviewer outreach list" below).

The **normative** specification remains
[`contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md),
and the executable reference remains
[`ref/b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py).
This preprint is informative; if the preprint and the spec disagree,
the spec wins.

## LNCS class — local vs submission

The preprint reads as LNCS but does **not** include `\documentclass{llncs}`
by default, because `llncs.cls` is not part of a standard TeX Live
install (it ships as a separate download from Springer). The header
of the `.tex` file documents the four-line swap needed to switch to
`llncs.cls` when targeting the IACR ePrint or LNCS submission.
The fallback `article` class with the same usepackage set
(`amsmath, amsthm, amssymb, graphicx, url, booktabs, listings,
hyperref, microtype, algorithm, algpseudocode`) is what runs in CI
and on a vanilla TeX Live 2023+ install.

## Build

```sh
# Debian/Ubuntu:
sudo apt install texlive-xetex texlive-latex-extra texlive-science \
                 texlive-fonts-recommended latexmk biber

# macOS:
brew install --cask mactex-no-gui     # or full mactex

# Windows:
# Install TeX Live or MiKTeX; add the bin directory to PATH.

# Inspect what build tools you have:
make tools

# Build B3POW-SCRATCH-PREPRINT.pdf:
make

# Cleanup intermediate files (.aux, .log, .bbl, ...):
make clean

# Also remove the built PDF:
make distclean

# Optional advisory lint (no warnings = no output):
make check
```

`make` prefers `latexmk`, which handles re-runs and the bibtex pass
automatically. If `latexmk` is missing, the Makefile falls back to a
manual `xelatex → bibtex → xelatex → xelatex` sequence, which
produces the same output.

## Submitting to IACR ePrint

1. Build the PDF locally and verify it.
2. Submit at <https://eprint.iacr.org/submit> (one-time author
   account required; see <https://eprint.iacr.org/submit.html> for
   the submission form fields).
3. ePrint accepts: PDF, plus a single archive (`.zip` / `.tar.gz`)
   of LaTeX source. Include `B3POW-SCRATCH-PREPRINT.tex`,
   `references.bib`, and the `Makefile`. Do **not** include build
   artefacts (the `.gitignore` here matches what ePrint asks you to
   exclude).
4. ePrint review is editorial, not peer review; turnaround is
   typically 1–3 business days. Posting on ePrint does **not**
   conflict with subsequent venue submission, and most cryptography
   venues encourage it.

## Suggested venues post-ePrint

This list mirrors the "Phase 3.4 target venues" in
[the launch plan](../../.cursor/plans/) and adds notes on why each
is a fit and what the typical lead time looks like. We do not yet
have a target venue chosen.

| Venue | Audience | Notes / typical lead time |
|---|---|---|
| **IACR ePrint** | The crypto-research community at large. | Immediate; no review gate; mandatory first step. |
| **Real World Crypto (RWC)** | Industry+academic, bridge venue. | Annual, January. Short talks; well-suited to a "calibrated PoW design" submission. |
| **USENIX Security** | Systems security. | Annual; submission deadlines staggered across the year. Strong fit for the verifier-DoS and 51%-attack sections. |
| **ACM CCS** | Crypto + systems. | Annual, November. Page limits favour the dense preprint format. |
| **AFT (Advances in Financial Technology)** | Blockchain / DeFi systems. | Annual; explicitly welcomes PoW / consensus work. |
| **Financial Cryptography (FC)** | Crypto + economics + blockchain. | Annual; the Eyal–Sirer selfish-mining paper appeared here. Natural fit. |
| **IEEE S&P ("Oakland")** | Top-tier security. | Annual, May. High bar; would target if a formal indifferentiability proof for the mix step lands. |
| **NDSS** | Network and distributed systems security. | Annual, February. Equihash debuted here. |
| **Communications of the ACM** | Cross-disciplinary digest. | Lower priority but useful for a calibrated-design rebuttal piece if there is one. |

The first concrete action item is **ePrint submission**. The venue
choice can wait until reviewer feedback shapes the preprint.

## Reviewer outreach list

The list below names cryptographers, PoW researchers, BLAKE3
authors, and FPGA / mining-protocol engineers whose review we would
value. This list is **aspirational**: we have not contacted any of
these individuals as of this commit, and we expect a low response
rate for cold outreach to academics on a project preprint. The list
is here so that we can track outreach attempts and so that future
contributors know who has already been asked.

For each entry: name, affiliation, why we would value their review,
and the lowest-friction medium for first contact. (Email and
ePrint-comment threads outperform Twitter/Mastodon DMs for academic
reviewer recruitment; the lower-friction social channels are noted
as fallback only.)

| # | Name | Affiliation (2026) | Why we would value their review | Suggested first contact |
|---|---|---|---|---|
| 1 | **Joseph Bonneau** | NYU + a16z research | Co-author of the canonical *SoK: Research Perspectives and Challenges for Bitcoin* (IEEE S&P 2015); long track record on PoW security and miner incentives. | Email via NYU faculty page; ePrint comment thread; conference cold-approach at RWC or FC. |
| 2 | **Sarah Meiklejohn** | UCL + Google | Blockchain measurement, anonymity, mining-pool topology. Her empirical lens is exactly what would stress-test the "FPGA-economical at launch hashrate" calibration. | Email via UCL faculty page; conference cold-approach at IEEE S&P. |
| 3 | **Ittay Eyal** | Technion | Co-author of the original *Majority Is Not Enough* selfish-mining paper (FC 2014). Would directly engage §5.6 and §5.7 of the preprint. | Email via Technion faculty page; FC cold-approach. |
| 4 | **Aviv Yaish** | Tel Aviv University | Recent peer-reviewed work on PoW attack vectors (selfish-mining refinements, fee-market manipulation). | Email via TAU faculty page; conference cold-approach at FC or AFT. |
| 5 | **Loi Luu** | Independent / Kyber Network co-founder | Early selfish-mining and smart-contract security publications; pragmatic blockchain-systems lens. | Email; LinkedIn DM as fallback. |
| 6 | **Jack O'Connor** | Independent (BLAKE3 author) | Co-author of BLAKE3; the only person who can authoritatively comment on whether the way we use reduced-round BLAKE3 in the mix step preserves the relevant security properties. | Email via the BLAKE3-team GitHub; the project's bug-bounty channel as a structured alternative. |
| 7 | **Tevador** *(pseud.)* | Independent (RandomX author) | Author of RandomX, the most thoroughly-engineered memory-hard PoW deployed in production. Direct peer for the calibration argument; would be the most credible critic of the "FPGA-economical" framing. | GitHub issue on the b3chain repo cross-linking the preprint; Monero-research forum thread as fallback. |
| 8 | **Marek Sýs** | Masaryk University | Symmetric-crypto and PRNG analysis; the F-4 chi-squared uniformity gate on `derive_addresses` is in his wheelhouse. | Email via Masaryk faculty page. |
| 9 | **Roger Wattenhofer** | ETH Zürich | Distributed systems and blockchain consensus; would stress-test the consensus-layer arguments in §3.4 and §5.5. | Email via ETH faculty page; conference cold-approach at AFT. |
| 10 | **Ariel Gabizon** | StarkWare / independent | Zero-knowledge and hash-function review; valuable second opinion on whether the reduced-round BLAKE3 composition has any non-obvious algebraic structure. | Email; ePrint comment thread. |
| 11 | **Bryan Bishop** | Independent (Stratum V2 / Bitcoin infrastructure) | Stratum protocol historian; would best evaluate §8 "Stratum V2 + Noise XX" item against the wider mining-protocol landscape. | Email; Bitcoin-dev mailing-list thread as fallback. |
| 12 | **Pavel Moravec** | Slush Pool / Braiins (Stratum V2 working group) | Practitioner-side reviewer for the pool-validator parity argument and the SV2 hardening plan. | Email via Braiins; Stratum V2 working-group channel. |
| 13 | **Filippo Sergeev / Filippo Merli** | Stratum V2 working group | Same domain as above; the working group's spec-side maintainers. | Stratum V2 working-group channel; GitHub. |
| 14 | **Andre Klöckner** | Academic FPGA / hardware engineering | The KU5P resource budget (Table~\ref{tab:fpga}) and the per-cycle pipeline arithmetic deserve a hardware-engineer second opinion. | Conference cold-approach (FCCM, FPL); cold email. |

Notes:

- The two "pseudonym + handle" entries (Tevador, Zawy12 in the
  bibliography) are listed because they remain the appropriate
  technical correspondents in their respective domains, despite
  the absence of a formal affiliation.
- Multiple names above will (correctly) decline; the list is
  intentionally long so that a 10–20 % response rate still gives us
  useful coverage.
- We expect that the most actionable feedback will come from the
  BLAKE3 team and the RandomX / memory-hard-PoW lineage, not from
  the broader cryptography academy.
- The 51%-attack and verifier-DoS sections (§5.5, §5.3) are the
  components most likely to attract follow-up systems-security
  publications; the algorithm-construction sections (§4, §5.1–5.2)
  are the ones most likely to attract crypto-side commentary.

## How this fits with the rest of the documentation

- [`../whitepaper/B3POW-SCRATCH-WHITEPAPER.md`](../whitepaper/B3POW-SCRATCH-WHITEPAPER.md) — public-facing whitepaper; longer, more pedagogical.
- [`../../contrib/miner/b3miner-rtl/SPEC.md`](../../contrib/miner/b3miner-rtl/SPEC.md) — normative algorithm specification.
- [`../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../../contrib/miner/b3miner-rtl/ref/b3pow_ref.py) — bit-exact executable reference.
- [`../security/B3POW-51-ATTACK-ANALYSIS.md`](../security/B3POW-51-ATTACK-ANALYSIS.md) — the 51%-attack threat model cited from §5.5.
- [`../audit/SCOPE.md`](../audit/SCOPE.md) — the external audit RFP package referenced as the place where the open items in §5 and §8 get formal treatment.
- [`../b3chain-pow-design.md`](../b3chain-pow-design.md) — shorter rationale document.
