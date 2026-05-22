# Bitcointalk ANN-thread template

**Live thread (official):** https://bitcointalk.org/index.php?topic=5583665.0  
**Forum account:** [b3chain](https://bitcointalk.org/index.php?action=profile;u=3757578) · posted 2026-05-22 · self-moderated

This file is the ready-to-paste body for the **Bitcointalk announcements**
thread (`https://bitcointalk.org/index.php?board=159.0`). It is written
in BBCode, the markup the Bitcointalk forum software uses.

The tone is calibrated to match [`README.md`](../../README.md) and
[`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md) — technical-first,
honest about what B3Chain is **and is not**, no unqualified
superlatives, no "ASIC-proof", no "perfect decentralization", no
investment language. Every claim points at a file in the repo, a
spec, or an external paper.

**Copy-paste files (no markdown wrapper):**

| File | Use |
|------|-----|
| [`BITCOINTALK-ANN-OP.bbcode`](BITCOINTALK-ANN-OP.bbcode) | Opening post body |
| [`BITCOINTALK-ANN-FIRST-REPLY.bbcode`](BITCOINTALK-ANN-FIRST-REPLY.bbcode) | First reply after OP |

Posting checklist (also referenced from [`README.md`](README.md) of
this directory):

1. Confirm every URL in the body resolves (no 404s).
2. Confirm the testnet status (height, faucet) at post time.
3. Post under the maintainers' established forum identity (do **not**
   create a single-purpose account — that pattern-matches every scam
   thread on the board).
4. Subscribe to the thread before posting so you see the first replies.
5. Post a first reply linking the pinned impersonation advisory
   ([issue #4](https://github.com/b3chain/b3chain/issues/4)) and subscribe
   to the thread.

---

## Subject

```
[ANN][POW] b3chain (B3C) — B3PoW-Scratch L1 | testnet live
```

(`[ANN]` is the convention the announcements board uses; `[POW]` helps
readers filter; "testnet live" sets expectations — there is no mainnet
coin yet.)

---

## Body (BBCode — paste verbatim)

```bbcode
[center][size=14pt][b]B3Chain[/b] (ticker: [b]B3C[/b])[/size]
[i]Conservative Bitcoin-Core-derived Layer 1 · B3PoW-Scratch v1.1 · testnet live[/i][/center]

[hr]

[size=12pt][b]Official links only[/b][/size]

[list]
[*][b]Website:[/b] [url=https://b3chain.org]b3chain.org[/url] — only domains linked from here are official
[*][b]Source:[/b] [url=https://github.com/b3chain/b3chain]github.com/b3chain/b3chain[/url] (branch [tt]b3chain-main[/tt])
[*][b]Impersonation advisory (pinned):[/b] [url=https://github.com/b3chain/b3chain/issues/4]github.com/b3chain/b3chain/issues/4[/url]
[/list]

[b][color=red]NOT us — do not use[/color][/b]
[list]
[*][url=https://github.com/b3cblockchain]github.com/b3cblockchain[/url] / [url=https://github.com/b3cblockchain/b3c-chain]b3c-chain[/url] — unrelated copy; stripped our links; do [b]not[/b] clone, build, or download wallets from that account
[/list]

[size=12pt][b]What is B3Chain?[/b][/size]

B3Chain Core is a fork of Bitcoin Core 30.2 that replaces Bitcoin's
SHA-256d mining algorithm with [b]B3PoW-Scratch v1.1[/b] — a memory-hard
BLAKE3-based PoW with a 1 MiB on-chip scratchpad, 8 parallel lanes, and
2 048 sequential read–modify–write iterations per hash. Everything else
(UTXO model, 21 M cap, 10-minute target, 210 k halving, Bitcoin script,
P2P protocol, transaction format) stays as close to Bitcoin as we can
keep it. The block-identity hash is still SHA-256d, so explorer UX,
merkle proofs, and the wire protocol look identical.

The chain is at [b]testnet stage[/b]. There is no mainnet, no premine,
no ICO, no airdrop, no token sale, no founder reward, no developer
tax. Test coins (`tB3C`) have no monetary value.

[size=12pt][b]Why a new PoW chain?[/b][/size]

Starting a new SHA-256d chain in 2026 means inheriting Bitcoin's idle
ASIC capacity on day one — any small mining outfit can centralise the
new chain before its first difficulty retarget. Choosing a CPU/GPU
algorithm trades that for botnet hashrate and unverifiable claims.
B3PoW-Scratch is one point on this trade-off curve. The explicit goal
is to make the most economical production miner a [i]small, low-power
FPGA card with on-chip memory[/i] (the reference is a Xilinx KU5P at
~10 W), and to bound the per-hash advantage of a custom ASIC by
making the algorithm memory-bandwidth-bound rather than compute-bound.
We do not claim "ASIC immunity" — none exists. The full argument is
in §1 and §6 of the whitepaper.

[size=12pt][b]Key parameters[/b][/size]

[table]
[tr][td][b]Field[/b][/td][td][b]Value[/b][/td][/tr]
[tr][td]Base[/td][td]Bitcoin Core 30.2.0 fork (MIT)[/td][/tr]
[tr][td]PoW algorithm[/td][td]B3PoW-Scratch v1.1 (1 MiB scratchpad, 8 lanes, 2 048 iterations, BLAKE3 primitive)[/td][/tr]
[tr][td]Block-identity hash[/td][td]SHA-256d (unchanged)[/td][/tr]
[tr][td]Block target[/td][td]600 s (10 min)[/td][/tr]
[tr][td]Difficulty algorithm[/td][td]LWMA-3 (Zawy LWMA-3)[/td][/tr]
[tr][td]Halving interval[/td][td]210 000 blocks (50 → 25 → 12.5 → ...)[/td][/tr]
[tr][td]Supply cap[/td][td]21 000 000 B3C[/td][/tr]
[tr][td]Bech32 HRP[/td][td][i]mainnet[/i] [b]b3[/b] / [i]testnet[/i] [b]tb3[/b][/td][/tr]
[tr][td]P2P port[/td][td][i]mainnet[/i] 8533 / [i]testnet[/i] 18533[/td][/tr]
[tr][td]RPC port[/td][td][i]mainnet[/i] 8534 / [i]testnet[/i] 18534[/td][/tr]
[tr][td]Stratum (testnet pool)[/td][td]stratum+tcp://pool.b3chain.org:3333[/td][/tr]
[tr][td]Testnet DNS seed[/td][td][tt]testnet-seed.b3chain.org[/tt][/td][/tr]
[tr][td]Testnet genesis hash[/td][td][tt]ebc117cd39760da3c8a3687484858e8ea2cfbc88990fb587957b4ba956a661c6[/tt] (v1.1.5)[/td][/tr]
[tr][td]Reorg-depth cap[/td][td]200 blocks (consensus-enforced)[/td][/tr]
[tr][td]Verifier budget[/td][td]50 ms / header (≪ 1 % of block interval)[/td][/tr]
[tr][td]Reference miner[/td][td]B3Miner-1 — Xilinx KU5P FPGA card, ~10 W TDP[/td][/tr]
[tr][td]Premine / founder reward[/td][td][b]none[/b][/td][/tr]
[/table]

[size=12pt][b]Read this first[/b][/size]

[list]
[*][b]Whitepaper:[/b] [url=https://github.com/b3chain/b3chain/blob/b3chain-main/doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md]doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md[/url] (Markdown source; PDF render via the in-tree pandoc rig)
[*][b]Formal spec:[/b] [url=https://github.com/b3chain/b3chain/blob/b3chain-main/contrib/miner/b3miner-rtl/SPEC.md]contrib/miner/b3miner-rtl/SPEC.md[/url] — single normative reference for the PoW
[*][b]Repository map:[/b] [url=https://github.com/b3chain/b3chain/blob/b3chain-main/doc/REPO-MAP.md]doc/REPO-MAP.md[/url]
[*][b]Why this exists (long-form):[/b] [url=https://github.com/b3chain/b3chain/blob/b3chain-main/doc/articles/why-b3pow-scratch.md]doc/articles/why-b3pow-scratch.md[/url]
[*][b]51 %-attack analysis:[/b] [url=https://github.com/b3chain/b3chain/blob/b3chain-main/doc/security/B3POW-51-ATTACK-ANALYSIS.md]doc/security/B3POW-51-ATTACK-ANALYSIS.md[/url]
[/list]

[size=12pt][b]Try it (testnet)[/b][/size]

[list]
[*][b]Testnet runbook:[/b] [url=https://github.com/b3chain/b3chain/blob/b3chain-main/doc/testnet-runbook.md]doc/testnet-runbook.md[/url]
[*][b]Block explorer:[/b] [url=https://explorer.b3chain.org]explorer.b3chain.org[/url]
[*][b]Faucet:[/b] [url=https://faucet.b3chain.org]faucet.b3chain.org[/url]
[*][b]Public Stratum pool:[/b] stratum+tcp://pool.b3chain.org:3333
[*][b]Pool dashboard:[/b] [url=https://pool.b3chain.org]pool.b3chain.org[/url]
[*][b]Live status JSON:[/b] [url=https://b3chain.org/testnet-status.json]b3chain.org/testnet-status.json[/url]
[/list]

[size=12pt][b]Source[/b][/size]

[list]
[*][b]Core repo:[/b] [url=https://github.com/b3chain/b3chain]github.com/b3chain/b3chain[/url] (MIT)
[*][b]Website repo:[/b] [url=https://github.com/b3chain/b3chain-website]github.com/b3chain/b3chain-website[/url] (MIT)
[*][b]Reference Python miner:[/b] [tt]contrib/miner/b3chain-cpuminer.py[/tt]
[*][b]Canonical Python reference:[/b] [tt]contrib/miner/b3miner-rtl/ref/b3pow_ref.py[/tt]
[*][b]C++ consensus implementation:[/b] [tt]src/crypto/b3pow_scratch.{h,cpp}[/tt]
[*][b]TypeScript pool validator:[/b] [tt]contrib/testnet/pool/src/lib/b3pow-scratch.ts[/tt]
[*][b]SystemVerilog RTL:[/b] [tt]contrib/miner/b3miner-rtl/rtl/[/tt]
[*][b]Hardware schematic (B3Miner-1):[/b] [tt]contrib/miner/b3miner-hardware/SCHEMATIC.md[/tt]
[/list]

All four PoW implementations are CI-gated against a single set of
consensus vectors at [tt]src/test/data/b3pow_consensus_vectors.json[/tt].

[size=12pt][b]Build from source (required)[/b][/size]

We do [b]not[/b] distribute prebuilt wallet binaries on Bitcointalk or via third-party GitHub accounts. Build [tt]b3chaind[/tt] yourself from the official repo:

[code]
git clone https://github.com/b3chain/b3chain.git
cd b3chain && git checkout b3chain-main
mkdir build && cd build
cmake .. && cmake --build . -j$(nproc)
./bin/b3chaind -chain=test
[/code]

The DNS seed [tt]testnet-seed.b3chain.org[/tt] returns the three operator seed nodes; your node syncs automatically.

[size=12pt][b]How to participate[/b][/size]

[list=1]
[*][b]Run a node.[/b] Build as above, then [tt]b3chaind -chain=test[/tt]. Add yourself to [tt]doc/testnet-runbook.md[/tt] §11 if you stand up a long-running peer — we will list community nodes.
[*][b]Mine.[/b] The reference Python miner is for protocol validation, not hashrate competition. Production miners run on the B3Miner-1 FPGA reference (RTL is open). A community KU5P bitstream is being assembled at [tt]contrib/miner/b3miner-rtl/sim/[/tt].
[*][b]Pool.[/b] You can solo-mine via [tt]getblocktemplate[/tt] or join [tt]pool.b3chain.org:3333[/tt]. Pool implementer contract: [tt]doc/stratum.md[/tt]. Operator guide for standing up your own pool: [tt]doc/pool-operator-guide.md[/tt].
[*][b]Mirror the reference implementation.[/b] The Python reference is single-file and small. Independent ports (Rust, Go, C, Zig, ...) help us shake out spec ambiguities. Open a PR with parity tests against [tt]b3pow_consensus_vectors.json[/tt] and we will list it.
[*][b]File issues.[/b] [url=https://github.com/b3chain/b3chain/issues]github.com/b3chain/b3chain/issues[/url] for bugs and feature requests. [url=https://github.com/b3chain/b3chain/discussions]github.com/b3chain/b3chain/discussions[/url] for design RFCs.
[*][b]Security.[/b] Private email to [tt]security@b3chain.org[/tt] (see [url=https://b3chain.org/.well-known/security.txt]security.txt[/url]). 90-day responsible-disclosure window (see [tt]CONTRIBUTING.md[/tt] §10). Do [b]not[/b] post unpatched-vulnerability details on this thread.
[/list]

[size=12pt][b]Roadmap (honest)[/b][/size]

[list]
[*][b]Now (testnet phase):[/b] B3Chain testnet is live with three seed nodes, a public Stratum pool, faucet, explorer, and a status monitor. Four PoW implementations are CI-gated to a shared vector set. The whitepaper, formal SPEC.md, 51 %-attack analysis, and threat-model docs are published.
[*][b]Next (mainnet candidate):[/b] external security audit (RFP package at [tt]doc/audit/[/tt]; auditor not yet contracted), reproducible-build pipeline (Guix/Docker, SBOM, Sigstore signing), benchmark suite hardware run, IACR ePrint preprint submission, third-party miner integrations (cpuminer-multi, BFGMiner). [b]Date: TBD.[/b] We will not name a mainnet date until the audit is contracted and the testnet has soaked under load for several months.
[*][b]Audit publication:[/b] all audit reports are intended to be published verbatim, with response notes, before mainnet activation. We do not pre-launch under embargo.
[*][b]Things we are deliberately [u]not[/u] promising:[/b] a mainnet date, a price, a listing, an ICO, an airdrop, a yield, an "ecosystem of partners". B3Chain is engineering work; everything in this paragraph is in scope for [b]other people[/b] to do, not us.
[/list]

[size=12pt][b]Disclaimers[/b][/size]

[list]
[*][b]This is testnet only.[/b] There is no mainnet B3C coin in circulation. Anyone selling a "B3C presale token" or "early-access allocation" is a scammer. The only official domain is [url=https://b3chain.org]b3chain.org[/url]. Impersonators may fork our GitHub tree — see the pinned advisory at [url=https://github.com/b3chain/b3chain/issues/4]issues/4[/url].
[*][b]No unofficial binaries.[/b] Do not download "B3Chain wallet" [tt].exe[/tt] files from typosquat GitHub accounts (notably [tt]b3cblockchain[/tt]). Build from [url=https://github.com/b3chain/b3chain]github.com/b3chain/b3chain[/url] only.
[*][b]No premine, no founder reward, no developer tax, no investment vehicle.[/b] B3Chain is a software project, not a security offering. We are not your investment adviser; this thread is not a solicitation.
[*][b]Audit not yet contracted.[/b] The C++, RTL, and TypeScript implementations are reviewed in-tree and parity-tested against the Python reference, but no third-party audit firm has been engaged yet. The audit RFP is at [tt]doc/audit/RFP.md[/tt].
[*][b]Bug bounty (testnet only at launch).[/b] Critical bugs in the testnet PoW pipeline are payable in [i]testnet[/i] B3C ([tt]tB3C[/tt], no monetary value) at launch — we are deliberately not paying mainnet bounties for testnet bugs. A treasury-funded mainnet bounty kicks in at mainnet launch. Scope and amounts: [tt]security/bug-bounty.md[/tt].
[*][b]Calibrated language.[/b] We do [b]not[/b] use the words "ASIC-proof", "permanently decentralised", "unhackable", "revolutionary", "moonshot", or "quantum-resistant" to describe B3Chain. The README, code-of-conduct, and whitepaper say what we [i]do[/i] claim, and the threat model says what we [i]don't[/i].
[/list]

[size=12pt][b]Maintainer contact[/b][/size]

[list]
[*][b]Project email:[/b] [tt]hello@b3chain.org[/tt]
[*][b]Security only:[/b] [tt]security@b3chain.org[/tt] (RFC 9116 [url=https://b3chain.org/.well-known/security.txt]security.txt[/url])
[*][b]Code of conduct concerns:[/b] [tt]coc@b3chain.org[/tt]
[*][b]GitHub:[/b] [url=https://github.com/b3chain]github.com/b3chain[/url]
[*][b]Real-time chat:[/b] Discord and Matrix are being stood up — invite link will be edited into this thread when ready (see [tt]doc/outreach/DISCORD-MATRIX.md[/tt] for the planned channel layout).
[*][b]This thread:[/b] preferred for protocol-level discussion. We read every reply for the first 12 hours and most replies after that. Please don't DM the maintainers' personal accounts on Twitter/Telegram with operational questions — file an issue or post here.
[/list]

[hr]

[size=10pt][i]Posted by the B3Chain maintainers. The text of this post is also tracked in the repository at [tt]doc/outreach/BITCOINTALK-ANN.md[/tt] — pull requests welcome if anything has gone stale.[/i][/size]
```

---

## First reply (BBCode — post immediately after OP)

```bbcode
[b]Quick links[/b]
[list]
[*]Impersonation / scam advisory (pinned on GitHub): [url=https://github.com/b3chain/b3chain/issues/4]b3chain/b3chain#4[/url]
[*]Testnet setup: [url=https://b3chain.org/testnet.html]b3chain.org/testnet.html[/url]
[*]Build from source only — [url=https://github.com/b3chain/b3chain]github.com/b3chain/b3chain[/url] — not [url=https://github.com/b3cblockchain]b3cblockchain[/url]
[/list]

Please post technical questions [b]in this thread[/b], not via PM. We do not offer "early access" or wallet downloads over DM.
```

---

## Maintainer-only post-launch checklist (do not paste)

Once the thread is live:

- [x] Live thread URL recorded (2026-05-22): https://bitcointalk.org/index.php?topic=5583665.0
- [ ] Reply with first comment containing: a) pinned impersonation
  advisory [issue #4](https://github.com/b3chain/b3chain/issues/4),
  b) testnet quick-start ([testnet.html](https://b3chain.org/testnet.html)),
  c) "post here, not via PM" note — paste from [`BITCOINTALK-ANN-FIRST-REPLY.bbcode`](BITCOINTALK-ANN-FIRST-REPLY.bbcode)
- [ ] Subscribe via the forum's notification system so the first
  hostile reply (there will be one) is seen and triaged within an hour.
- [ ] After the thread settles, mirror the OP into the project Discord
  `#announcements` channel and the Matrix `#b3chain-announce` room.

## Style notes for the maintainer

- BBCode tags are case-sensitive in some Bitcointalk widgets — keep
  them lowercase as written above.
- Bitcointalk renders inline `[tt]` in monospace; use it for paths
  and shell snippets rather than `[code]` blocks for short fragments
  (long blocks should still use `[code]`).
- The forum's URL renderer is happy with bare URLs but `[url=…]…[/url]`
  is the convention; we use the explicit form everywhere.
- The forum strips most whitespace; do not rely on indentation for
  meaning. Use lists.
- Headlines use `[size=12pt]` rather than the mostly-deprecated
  `[h2]`. The forum supports a few size tokens reliably; 14 (lead),
  12 (section), 10 (small text) is the safe set.

## What this template deliberately does NOT include

- **Price predictions, exchange-listing claims, "guaranteed return"**
  language. The CoC bans this and Bitcointalk moderators will lock the
  thread for it.
- **A specific mainnet date.** We don't have one, and announcing a
  fake one is the single fastest way to lose credibility on this board.
- **Founder identities by name beyond what is already public on
  GitHub.** Pseudonymity is a CoC-protected property of the project.
- **Comparison tables against named competitors.** Bitcointalk is full
  of those threads and they age badly. The whitepaper §2 has the
  technical comparison; that's where we send people who ask.
- **An invite to "DM the team for early access".** That is a scam
  signature and we don't do it.
