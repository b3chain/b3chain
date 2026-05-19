# Security policy

## Supported versions

B3Chain Core is currently in pre-launch development. All versions on
the `b3chain-main` branch receive security updates. Past releases
will be supported per [`doc/release-process.md`](doc/release-process.md)
once the first signed release ships.

## Reporting a vulnerability

To report a security issue, email **security@b3chain.org**. Do not
file a public GitHub issue for anything you believe affects
consensus, fund safety, or remote-code execution.

For the full process — what's in scope, severity tiers, the testnet-coin
payout posture, PGP encryption status, safe-harbour wording, and the
90-day coordinated disclosure default — see
[`security/bug-bounty.md`](security/bug-bounty.md). The same policy
is advertised via the RFC 9116 `security.txt` at
[`https://b3chain.org/.well-known/security.txt`](https://b3chain.org/.well-known/security.txt).

We aim to:

- Acknowledge reports within 24 hours.
- Provide an initial assessment within 72 hours.
- Coordinate public disclosure after the fix is deployed.

## External audit package

The scope, threat model, and request-for-proposal documents we send
to external audit firms live in [`doc/audit/`](doc/audit/):

- [`doc/audit/SCOPE.md`](doc/audit/SCOPE.md) — scope of engagement.
- [`doc/audit/THREAT-MODEL.md`](doc/audit/THREAT-MODEL.md) — formal threat model.
- [`doc/audit/RFP.md`](doc/audit/RFP.md) — auditor RFP template.

In-tree security posture documents:

- [`doc/SECURITY-AUDIT.md`](doc/SECURITY-AUDIT.md) — self-audit baseline.
- [`doc/SECURITY-INHERITANCE.md`](doc/SECURITY-INHERITANCE.md) — what we still prove that Bitcoin proves.
- [`doc/SECURITY-ROADMAP.md`](doc/SECURITY-ROADMAP.md) — what we plan to harden next.
- [`doc/security/B3POW-51-ATTACK-ANALYSIS.md`](doc/security/B3POW-51-ATTACK-ANALYSIS.md) — 51%-attack threat model.
- [`doc/security/RESPONSE-RUNBOOK-51ATTACK.md`](doc/security/RESPONSE-RUNBOOK-51ATTACK.md) — incident response.

## Upstream security

B3Chain is based on Bitcoin Core 30.2.0. Security fixes from upstream
Bitcoin Core are cherry-picked promptly. For Bitcoin Core security
issues themselves, see
[`bitcoincore.org/en/lifecycle/`](https://bitcoincore.org/en/lifecycle/#schedule)
and report upstream first.
