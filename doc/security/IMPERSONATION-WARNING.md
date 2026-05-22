# Impersonation warning — b3cblockchain (not us)

**Status:** active as of 2026-05-22  
**Canonical issue:** [b3chain/b3chain#TBD](https://github.com/b3chain/b3chain/issues) — pin when filed

An unrelated GitHub account is impersonating B3Chain.

| | Official (us) | Impersonator (**not us**) |
|---|---|---|
| GitHub | [github.com/b3chain](https://github.com/b3chain) | [github.com/b3cblockchain](https://github.com/b3cblockchain) |
| Core repo | [b3chain/b3chain](https://github.com/b3chain/b3chain) | [b3cblockchain/b3c-chain](https://github.com/b3cblockchain/b3c-chain) |
| Website | [b3chain.org](https://b3chain.org) | not linked from their README |

**Do not clone, build, or download wallets from `github.com/b3cblockchain`.**

Public warning: [b3chain.org — Identity and impersonation](https://b3chain.org/index.html#identity)

---

## What we observed

- Account `b3cblockchain` created **2026-05-20**; profile display name **"B3Chain"**.
- Repo `b3c-chain` is a stale copy of our tree (pre–v1.1.5 testnet params), with official links removed from README (`b3chain.org`, `github.com/b3chain/b3chain`).
- Release titled [**"B3Chain wallets v1.0.0"**](https://github.com/b3cblockchain/b3c-chain/releases/tag/v1.0.0) — prebuilt wallet distribution is a common malware vector in this scam pattern.
- Also hosts a fork of `electrs` under the same account.
- Commit metadata uses forged author `B3Chain <aleighavaskes@gmail.com>` (not our team).

Typical pattern: fork an early-stage coin, strip identity links, promote elsewhere, drive users to unofficial binaries.

---

## What is safe

- Build only from **[github.com/b3chain/b3chain](https://github.com/b3chain/b3chain)** (branch `b3chain-main`).
- Follow **[b3chain.org/testnet.html](https://b3chain.org/testnet.html)** for testnet setup.
- Official testnet DNS seed: `testnet-seed.b3chain.org`.

---

## Report the impersonator

- GitHub: [Report abuse](https://github.com/contact/report-abuse) — reference user `b3cblockchain`, repo `b3c-chain`.
- Link moderators and users to the pinned GitHub issue on `b3chain/b3chain` when available.
