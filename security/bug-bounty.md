# B3Chain Bug Bounty Programme

**Status:** active (launch posture: testnet-coin payouts only)
**Author:** b3chain
**Last updated:** 2026-05-19
**Companion documents:**
[`../SECURITY.md`](../SECURITY.md),
[`../doc/audit/SCOPE.md`](../doc/audit/SCOPE.md),
[`../doc/audit/THREAT-MODEL.md`](../doc/audit/THREAT-MODEL.md),
[`../doc/SECURITY-AUDIT.md`](../doc/SECURITY-AUDIT.md),
[`../doc/SECURITY-ROADMAP.md`](../doc/SECURITY-ROADMAP.md),
[`../doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../doc/security/B3POW-51-ATTACK-ANALYSIS.md).

---

## 1. Programme summary

B3Chain runs a self-hosted bug bounty programme. We accept reports
of security vulnerabilities in B3Chain Core, the B3PoW-Scratch
consensus implementations, the reference pool stack (testnet-scoped),
and the B3Miner-1 reference miner firmware. At launch — until the
project has a mainnet treasury — **payouts are denominated in
testnet coins (`tBTC`-equivalent on `b3chain-test`)** plus public
acknowledgement; USD payouts are reserved for future activation and
are noted per-tier below. We aim to acknowledge every good-faith
report within 24 hours and to coordinate disclosure on a 90-day
default window.

This programme is the standing-incentive counterpart to the one-off
external audit scoped in [`doc/audit/`](../doc/audit/). The audit
finds what we can pay for in a fixed window; the bounty finds what
we cannot anticipate.

## 2. Scope

### 2.1 In scope

- **B3Chain Core (`b3chaind`, `b3chain-cli`, RPC, wallet)** — the
  production node and its public RPC / wallet surfaces. Source:
  [`src/`](../src/). Specifically: anything that affects consensus,
  fund safety, RPC authentication, or wallet key handling.
- **B3PoW-Scratch consensus implementations** — the four parallel
  impls listed in [`doc/audit/SCOPE.md §3`](../doc/audit/SCOPE.md):
  - [`src/crypto/b3pow_scratch.{h,cpp}`](../src/crypto/), [`src/crypto/b3pow_cache.{h,cpp}`](../src/crypto/), [`src/pow/`](../src/pow/), the validation paths in [`src/validation.cpp`](../src/validation.cpp)/[`src/net_processing.cpp`](../src/net_processing.cpp).
  - [`contrib/miner/b3miner-rtl/ref/b3pow_ref.py`](../contrib/miner/b3miner-rtl/ref/b3pow_ref.py).
  - [`contrib/testnet/pool/src/lib/b3pow-scratch.ts`](../contrib/testnet/pool/src/lib/b3pow-scratch.ts), [`lib/pad-cache.ts`](../contrib/testnet/pool/src/lib/pad-cache.ts), [`src/stratum/share-validator.ts`](../contrib/testnet/pool/src/stratum/share-validator.ts).
  - [`contrib/miner/b3miner-rtl/rtl/`](../contrib/miner/b3miner-rtl/rtl/).
- **Reference pool stack** (testnet-scoped: `pool.b3chain.org`) —
  share validation, payout integrity, web-dashboard auth, Stratum V1
  / V2 protocol handling. Source: [`contrib/testnet/pool/`](../contrib/testnet/pool/).
- **B3Miner-1 firmware** — the ESP32-S3 host firmware that drives
  the FPGA. Source: [`contrib/miner/b3miner-firmware/`](../contrib/miner/b3miner-firmware/).
  Specifically: ATECC608B integration (`b3_sec` once landed), OTA
  manifest verification (`b3_ota`), Stratum V1 / V2 client paths
  (`b3_stratum_v1`, `b3_stratum_v2`), web admin UI (`b3_web`).

### 2.2 Out of scope

- **`b3chain.org` and the testing subpages** — handled by a separate
  programme. Static-website XSS / fingerprinting issues should be
  reported to the website maintainers via the standard report path
  but **are not bounty-eligible** under this programme. The website
  repository is `github.com/b3chain/b3chain-website`.
- **Inherited Bitcoin Core bugs** that affect B3Chain only because
  we forked. Please report these upstream at
  [`bitcoincore.org/en/lifecycle/`](https://bitcoincore.org/en/lifecycle/#schedule).
  We will of course backport upstream fixes promptly.
- **Denial-of-service against the operator-run pool endpoint**
  (`pool.b3chain.org`). DDoS, traffic flooding, and similar
  operational concerns are out of scope; they are not protocol
  bugs. A bug that causes the **share validator** to mis-accept or
  the **payout pipeline** to mis-pay *is* a protocol-level
  vulnerability and **is** in scope.
- **Social-engineering attacks** against maintainers, contributors,
  miners, pool operators, or exchange operators.
- **Physical attacks** on B3Miner-1 hardware (clock glitching,
  voltage glitching, EMFI, JTAG attacks on consumer-grade boards).
  Listed under "what we accept losing" in
  [`doc/audit/THREAT-MODEL.md §6`](../doc/audit/THREAT-MODEL.md).
- **Best-practice findings without a demonstrated vulnerability**
  (e.g. "this header could be hardened with X"). Helpful as
  Informational-tier reports but not bounty-eligible.

## 3. Severity tiers and payouts

> **Launch posture, stated explicitly.** Until the project has a
> mainnet treasury, all monetary rewards below are paid in **testnet
> coins (`tBTC`-equivalent on `b3chain-test`)**, sent to a B3Chain
> testnet address the researcher provides. Testnet coins have no
> market value and exist as a transparent placeholder for future USD
> payouts; they are not a security or an investment instrument.
> When and if the project's funding posture changes, the maintainers
> will publish a written amendment that converts the tiers to USD
> amounts. Until then, USD figures below are aspirational and
> non-binding (`"USD amounts at the maintainers' discretion"`).

### 3.1 Critical

**Examples:** consensus break (a valid B3PoW-Scratch share rejected
by `b3chaind` or vice versa across the four impls), fund loss
(unauthorised UTXO spend, theft of wallet keys), remote code
execution in `b3chaind` from a remote peer, remote code execution in
the pool's stratum server.

**Reward:** **10 000 t** testnet coins + public acknowledgement (with
researcher consent) + **future USD payment at the maintainers'
discretion if and when funded**.

### 3.2 High

**Examples:** remote denial-of-service against a node from a remote
peer (e.g. a header that causes `b3chaind` to crash, hang, or
consume unbounded resources), an attack that increases the
B3PoW-Scratch verification cost by ≥ 10× over the documented 50 ms
budget on a reference CPU, lateral movement on the miner firmware
(remote → local privilege escalation; ATECC608B key extraction
bypass), authentication bypass in the pool web UI that grants
operator privileges.

**Reward:** **1 000 t** testnet coins + public acknowledgement +
USD-at-discretion-if-funded as above.

### 3.3 Medium

**Examples:** memory leak in a long-running consensus path, crash on
malformed input that does **not** affect consensus or fund safety
(e.g. wallet RPC crash on a malformed PSBT), non-exploitable misuse
of cryptographic primitives, missing rate-limit on a non-critical
RPC, a parser that accepts a header the spec says should be
rejected but the network already rejects via a stricter later check.

**Reward:** **100 t** testnet coins + public acknowledgement.

### 3.4 Low / Informational

**Examples:** hardening suggestions, documentation gaps, style /
defensive-programming improvements that would have prevented a
finding had they been in place.

**Reward:** public acknowledgement, no testnet-coin payout.

### 3.5 Tier-assignment notes

- The maintainers assign the final tier on receipt. Researchers are
  welcome to argue for a higher tier with reasoning; we will reply
  with the rationale either way.
- Reports that combine multiple findings get tiered against the
  highest single component, then the additional findings are listed
  as separate medium / low reports.
- A duplicate report (same root cause as a finding already triaged
  or paid out) is acknowledged in the hall of fame and tiered as
  Informational; the first valid report gets the full payout.

## 4. Reporting

### 4.1 Channel

- **Email:** `security@b3chain.org`
- **PGP-encrypted** for any Critical or High finding. Plaintext is
  acceptable for Low / Informational; we still encourage encryption.

### 4.2 PGP key

- **Fingerprint:** `[PGP_FINGERPRINT_PLACEHOLDER]` — *to be
  published below the launch threshold.*
- **Publication channels (planned):**
  - [`https://b3chain.org/.well-known/security.txt`](https://b3chain.org/.well-known/security.txt) (`Encryption:` field — RFC 9116).
  - [`https://b3chain.org/pgp/security-pgp.txt`](https://b3chain.org/pgp/security-pgp.txt) (ASCII-armoured public key).
  - The maintainers' [`keys.openpgp.org`](https://keys.openpgp.org)
    profile (lookup by fingerprint).
- **Status note (2026-05-19):** the PGP key publication is pending.
  Until the key is published at the URLs above, send the email in
  plaintext with the body `PGP_PENDING — PLEASE_REPLY_WITH_KEY` and
  the maintainers will reply with a freshly minted key over the
  same thread within 24 hours. After the key is published, fold
  this paragraph out.

### 4.3 Report contents

Please include, where applicable:

1. **One-line summary** suitable as a CVE title.
2. **Severity** you believe applies (Critical / High / Medium / Low
   / Informational) and a short justification.
3. **Affected component(s)** — file path(s) at the current
   `b3chain-main` HEAD plus the commit you tested against.
4. **Reproducer** — a script, patch, or step-by-step recipe that
   makes the bug observable on regtest, testnet, or the operator's
   workstation. The more deterministic, the faster we can triage.
5. **Impact** — what the bug lets the attacker do, and what
   assumptions the attacker needs.
6. **Suggested fix** if you have one (optional; we will work out a
   fix even without).
7. **Payout address** — a B3Chain testnet address you control, if
   you want the testnet-coin reward; or a stated preference for
   acknowledgement-only.
8. **Disclosure preference** — your name / handle for the hall of
   fame, or pseudonymous, or fully private.

## 5. Safe-harbour language

The maintainers will not pursue legal action or law-enforcement
referral against any researcher who:

- Tests in good faith against components in scope (§ 2.1) on the
  researcher's own systems, on regtest, or on testnet
  (`b3chain-test`).
- Avoids destructive testing on `pool.b3chain.org` and on third-party
  infrastructure (other people's nodes, other pools, exchanges).
- Avoids accessing, modifying, exfiltrating, or destroying data
  belonging to anyone but the researcher.
- Does not exploit the vulnerability beyond what is necessary to
  demonstrate the issue.
- Does not publicly disclose the vulnerability before coordinated
  disclosure under § 6.

To the extent the maintainers can authorise it, this programme
constitutes authorisation under any applicable computer-misuse
statute for testing against the in-scope components on the
researcher's own systems or on `b3chain-test`. The maintainers
cannot waive third-party rights — testing against another pool,
another miner, or another node operator without that party's
permission is **not** authorised here.

This safe-harbour wording is adapted from the standard
[YesWeHack](https://yeswehack.com/programs#programs-vdp-policies)
and [Bugcrowd standard disclosure](https://bugcrowd.com/disclosure)
language; we follow industry convention.

## 6. Disclosure policy

- **Default coordinated-disclosure window:** 90 days from the date
  of the original report. The maintainers will work with the
  reporter on a public disclosure plan within the first 14 days.
- **Negotiable.** Both parties can agree to a longer window (e.g.
  if the fix requires a hard fork) or a shorter window (e.g. if the
  finding is already public).
- **Coordinated public disclosure is preferred.** We aim to publish
  a write-up, the patch, and a CVE (where appropriate) on the same
  day the fix ships.
- **Acknowledgements** appear in the [hall of fame](#hall-of-fame)
  below with researcher consent.

### 6.1 Out-of-band exceptions

The 90-day default does not apply when:

- **Active exploitation in the wild.** If the vulnerability is being
  actively exploited against B3Chain users, we will compress the
  disclosure window to the shortest period compatible with shipping
  a credible fix, and we will publish a workaround in the same hour
  the exploitation is confirmed.
- **Embargoed cross-project disclosure.** If the finding is shared
  with another project (e.g. an upstream Bitcoin Core finding or a
  vendored BLAKE3 finding), we will align with the embargo set by
  the affected project.
- **Operator-only mitigation possible.** If a workaround the
  operator can deploy without a code change exists, we will publish
  the workaround alongside the report and treat the code fix as a
  separate, later disclosure.

## 7. Hall of fame

Researchers who have reported in-scope vulnerabilities are
acknowledged here with their consent. The hall of fame is the
single authoritative list; we do not maintain a separate
acknowledgement page.

(No entries yet.)

---

## 8. Cross-references

- [`SECURITY.md`](../SECURITY.md) — top-level security policy stub.
- [`doc/audit/SCOPE.md`](../doc/audit/SCOPE.md) — external-audit scope of engagement.
- [`doc/audit/THREAT-MODEL.md`](../doc/audit/THREAT-MODEL.md) — formal threat model.
- [`doc/audit/RFP.md`](../doc/audit/RFP.md) — auditor request-for-proposal template.
- [`doc/SECURITY-AUDIT.md`](../doc/SECURITY-AUDIT.md) — in-tree self-audit baseline.
- [`doc/SECURITY-ROADMAP.md`](../doc/SECURITY-ROADMAP.md) §5 — the planned evolution of this programme.
- [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](../doc/security/B3POW-51-ATTACK-ANALYSIS.md) — the 51%-attack analysis covering the consensus mitigations.
- [`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](../doc/security/RESPONSE-RUNBOOK-51ATTACK.md) — the operational runbook a Critical finding may trigger.
