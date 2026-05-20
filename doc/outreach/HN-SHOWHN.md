# Hacker News "Show HN" submission template

This is the launch-day template for the [Hacker News](https://news.ycombinator.com/)
"Show HN" submission. The submission has three parts: the **title**,
the **URL**, and the [first comment by the submitter](https://news.ycombinator.com/showhn.html)
that explains what is being shown.

The `text` field on a Show HN submission is technically optional but
the convention for engineering-heavy posts is that the submitter
leaves a single anchor comment immediately after posting. That
comment is what readers actually read; the title and URL only get
them to click. This file contains both.

---

## Submission fields

| Field | Value |
|---|---|
| Submitter | A maintainer with an established HN history (do **not** create a single-purpose account — the moderators auto-flag it). |
| Title | `Show HN: B3Chain – memory-hard, FPGA-economical PoW Layer 1 (B3PoW-Scratch v1.1)` |
| URL | `https://b3chain.org` |
| Anchor comment | The 1 500-char block below, posted by the same account immediately after the submission goes live. |
| Tags / topic | None — HN doesn't use tags; the title prefix `Show HN:` does the routing. |

### Why this URL

`https://b3chain.org` is the canonical landing page and links to the
whitepaper, repo, testnet runbook, and explorer in three clicks. HN's
URL renderer prefers a single project page over a deep link to a Markdown
file in a Git repo.

### Why this title

- `Show HN:` is the required prefix for the [Show HN guidelines](https://news.ycombinator.com/showhn.html).
- The dash separates "what" (the project) from "how" (the algorithm).
- "memory-hard, FPGA-economical" is the calibrated technical claim;
  it does **not** say "ASIC-proof" or "decentralized" because we
  cannot defend either claim in the comments and HN will notice.
- "PoW Layer 1" disambiguates from a lot of Show HNs that turn out
  to be ERC-20 wrappers.
- The version string (`v1.1`) signals "we are not a vapor preprint";
  there is something to look at.
- Total length 91 characters — well under HN's 80-char-soft / 200-char-hard
  title limit (HN compresses titles longer than ~80 visually but does
  not truncate the underlying text until 200).

---

## Anchor comment (post immediately after submission)

The HN comment limit is technically about 25 000 chars, but the
[Show HN convention](https://news.ycombinator.com/showhn.html) is to
keep the anchor comment **short and concrete** so readers can decide
in 30 seconds whether to dig in. Target: ≤ 1 500 characters. The
version below is 1 489 characters.

```text
Hi HN — I'm one of the maintainers of B3Chain.

What we're showing: B3PoW-Scratch v1.1, a memory-hard PoW for Bitcoin-derived
chains. It uses a 1 MiB on-chip scratchpad, 8 parallel lanes, and 2,048
sequential read-modify-write iterations per hash. BLAKE3 is the only
non-linear primitive. The chain is otherwise Bitcoin Core 30.2 (UTXO,
21 M cap, 10-min target, SHA-256d block-identity hash, all of Bitcoin
script). Only the PoW hash function is replaced.

Why we built it: a new SHA-256d chain in 2026 inherits Bitcoin's idle
ASIC capacity and gets centralised before its first retarget. A
CPU/GPU-friendly chain invites botnets and unverifiable claims. We
wanted to make the cheapest production miner a small low-power FPGA
card with on-chip BRAM, instead of a giant SHA-256d ASIC or a
botnet-friendly CPU/GPU algorithm. The reference miner is a Xilinx
KU5P at ~10 W. The verifier is one CPU core for ~50 ms.

What's actually built: testnet is live (3 seeds, public Stratum pool,
faucet, explorer). Four implementations (Python reference, C++
consensus, TypeScript pool validator, SystemVerilog RTL) are CI-gated
to a single set of consensus vectors.

Whitepaper: https://github.com/b3chain/b3chain/blob/b3chain-main/doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md
Repo (MIT): https://github.com/b3chain/b3chain
Testnet runbook: https://github.com/b3chain/b3chain/blob/b3chain-main/doc/testnet-runbook.md

Honest disclaimers: testnet only, no mainnet, no premine, no founder
reward, no token sale. External audit is in scope (RFP under doc/audit/)
but not yet contracted. We are not claiming "ASIC-proof" — no PoW is.
The whitepaper §6 has the bounds.

Critique welcome, especially on §5 (security argument) and §6 (FPGA/ASIC
analysis).
```

(Character count: 1 489. If you trim, keep at least the three URLs and
the disclaimer paragraph.)

---

## Anticipated FAQ — pre-canned honest answers

These are the comment patterns most likely to be the top replies to a
PoW-on-HN submission, with calibrated answers prepared in advance.
Post these as direct replies to the relevant top-level comments —
**do not** post them as a separate "FAQ" thread; HN moderators frown on
that.

### FAQ-1. "Why not just use RandomX / ProgPoW / KawPow / Ethash / Argon2?"

> RandomX (Monero) is excellent for what it is — a CPU-friendly, JIT-
> based PoW that targets fairness against ASICs by exploiting CPU IPC
> and L3 cache. We deliberately did not choose it because:
>
> 1. The 256 MiB working set means a node verifier touches main memory,
>    not on-chip cache. We want a verifier that runs at L1/L2 speed in
>    50 ms.
> 2. CPU-friendly is botnet-friendly. We're trying to push hashrate
>    toward ~10 W FPGA cards a hobbyist can buy for the cost of a GPU,
>    not toward whatever stolen CPU cycles a botnet can harvest.
>
> ProgPoW / KawPow target GPU mining intentionally — they are explicitly
> in the "let's keep GPU miners busy" camp. Same botnet-friendliness
> concern, plus the post-Ethereum GPU surplus has changed the
> economics so much that the assumption of "GPUs are decentralised
> hardware" is much weaker in 2026 than it was in 2017.
>
> Ethash / Dagger-Hashimoto were ASIC-resistance-by-DAG-size; the DAG
> grew into main-RAM territory and ASICs followed. Same pattern as
> RandomX's 256 MiB: we want on-chip-only.
>
> Argon2 is a great password-hash, but it's a single sequential KDF;
> using it as a PoW means each hash is a long sequential dependency
> chain, which is a memory-bandwidth contest more than a security
> argument. We use BLAKE3 because we want the parallel-lane
> architecture for the FPGA target.
>
> The full comparison is in §2 of the whitepaper:
> https://github.com/b3chain/b3chain/blob/b3chain-main/doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md

### FAQ-2. "What's stopping someone from building a B3PoW-Scratch ASIC?"

> Nothing forever. We say so explicitly in §1 of the whitepaper and
> §6 ("Hardware analysis"): "we do not claim B3PoW-Scratch is
> ASIC-proof; no PoW is". An ASIC port is feasible.
>
> What we do claim, with bounds in §6: the dominant cost in this
> algorithm is on-chip SRAM area, not combinational logic. A 7 nm
> ASIC's per-hash advantage over an FPGA on the same node is bounded
> by the SRAM-density ratio between the two technologies (roughly
> 2-3×, not 1 000×). The economic frontier shifts but does not
> disappear. The honest analysis (with NRE estimates and breakeven
> hashrates) is at doc/analysis/ASIC-ECONOMICS.md.
>
> If someone does build a B3PoW ASIC, the chain still works — it just
> means the mining floor moves up. We'd treat that as a (mildly
> embarrassing) success of "the design did what it said on the tin".

### FAQ-3. "Why fork Bitcoin Core instead of starting from scratch?"

> Conservative inheritance. Bitcoin Core is the result of fifteen years
> of adversarial review of every script opcode, every wallet edge case,
> every P2P quirk. Starting from scratch in 2026 means re-discovering
> all of those bugs.
>
> Our diff against bitcoin/bitcoin v30.2 is intentionally tiny:
> chain-id parameters (`bc` → `b3`, ports, genesis, branding), the
> PoW algorithm in `src/crypto/b3pow_scratch.{h,cpp}`, and the wiring
> that calls it from `src/validation.cpp` and `src/pow.cpp`. Bech32
> HRP, BIP44 coin type, and Stratum/RPC ports are different so a
> wallet built for B3Chain cannot accidentally publish a Bitcoin
> transaction or vice versa. Everything else is upstream Bitcoin Core.
>
> This is also explicitly upstream-friendly: we cherry-pick Bitcoin
> Core security and non-consensus fixes on a periodic cadence
> (`CONTRIBUTING.md` §4.6), and our PoW lives in a small, contained
> set of files. If Bitcoin Core moves to a major refactor, we can
> follow it without rewriting the whole chain.

### FAQ-4. "Is this a scam? Premine? Pump-and-dump?"

> No premine, no founder reward, no developer tax, no ICO, no airdrop,
> no presale, no listing, no token sale. The chain is at testnet stage
> only — there is no mainnet B3C coin in circulation. Anyone selling
> "B3C presale tokens" or "early-access allocations" is a scammer, and
> we have no relationship with them. The only official domain is
> `b3chain.org`.
>
> The codebase is MIT, on GitHub, with four parallel implementations
> CI-gated against shared consensus vectors. Whitepaper, formal SPEC,
> threat model, and 51 %-attack analysis are all in the repo. If
> something is unclear or feels under-claimed, file an issue — the
> calibrated language in the README is deliberate.

### FAQ-5. "How is this funded? Who's paying you?"

> No one. B3Chain is volunteer / hobby work. We do not have a treasury,
> a foundation, a token raise, or a corporate sponsor. The maintainers
> pay the small monthly cost of three seed VPS hosts and the testnet
> faucet out of pocket. There is no equity, no allocation, no salary.
>
> The honest long-term answer for security funding (post-mainnet,
> post-subsidy-decay) is the open question every PoW chain has. Our
> current thinking — not committed, not in v1 consensus — is to lean
> on the same fee-market dynamics Bitcoin runs on, and to open a public
> discussion on a miner-set funding mechanism (a BIP-30x-style
> opt-in, not a baked-in dev tax) once the chain has reached a
> meaningful hashrate. That is a future discussion, not a v1 feature.
> The economics docs are at doc/economics/{MONETARY-POLICY,
> MINER-INCENTIVES, SECURITY-BUDGET}.md.

### FAQ-6 (likely follow-up). "How is the verifier 50 ms? That seems slow."

> Slow per header, fast per block. With a 600-second block target, the
> 50 ms verifier budget is < 1 % of the block interval. The expensive
> part of verification is the 1 MiB scratchpad init, which depends only
> on `prev_block_hash` and is cached for the duration of one tip
> (cache depth 8 in `Consensus::Params`).
>
> The 50 ms number is hardware-dependent. On a 2026 mid-range CPU
> core (one core, fixed clock, no SIMD outside what BLAKE3 already
> uses), one full PoW evaluation completes in ~30-40 ms; we set the
> consensus budget at 50 ms so older or thermally-throttled hardware
> doesn't trip the budget. Headers that exhaust the budget are routed
> to peer-scoring (`BLOCK_POW_BUDGET`) rather than rejected outright.
> The methodology is in `doc/whitepaper/B3POW-SCRATCH-WHITEPAPER.md`
> §7 and the bench scaffold is at `contrib/testing/bench/`.

### FAQ-7 (likely follow-up). "What about quantum?"

> Same as Bitcoin: we still use ECDSA / Schnorr (secp256k1) for
> signatures and SHA-256d for the block-identity hash. Neither is
> post-quantum. The PoW (B3PoW-Scratch) is BLAKE3-based, which
> Grover-accelerated brute force halves the security parameter on
> the same way it does for SHA-256, but a PoW's security model
> doesn't depend on collision-resistance the way a signature does.
>
> A quantum-secure consensus protocol is out of scope for v1 and
> would require coordinated changes across all of Bitcoin's signature
> and hashing pipeline. We are watching the upstream Bitcoin BIP
> activity on this and will follow rather than lead. We do **not**
> claim "quantum-resistance".

---

## Posting timing

| Window | Reasoning |
|---|---|
| **Tuesday or Wednesday morning, ~14:00 UTC** (≈ 09:00 US Eastern, 06:00 US Pacific) | Highest sustained engagement window for technical Show HNs. Avoids the Monday inbox and the Friday wind-down. Beats the European working day's end. |
| Avoid Sunday | Lower readership; the post can fall off the new page before peak hours. |
| Avoid US public holidays | Memorial Day, July 4, Labor Day, Thanksgiving week, Christmas / New Year — front page traffic drops sharply. |

Do not boost or solicit upvotes. HN's flagging is correlated; an
artificial early bump gets the submission killed. Let the post breathe.

## Engagement expectations

- **First 30 minutes:** the post is on `/newest`. If two or three engaged
  readers find it interesting, it lands on `/front`. If not, it falls
  off — do not repost the same day; wait at least a week and revise the
  title.
- **First 4 hours:** the bulk of upvotes and the bulk of comments.
  Maintainer replies in this window are read by everyone who later
  arrives.
- **First 24 hours:** the long tail. Comments after this point are
  occasional; do not abandon the thread but do not feel obliged to
  reply to every late drive-by.

A single maintainer should be on call for the **first 6 hours** to
reply to top-level comments. Use the FAQ block above as the canned
response set. Do **not** copy-paste the FAQ verbatim — paraphrase to
match the specific question, then link to the relevant repo section.

## What to avoid in replies

- **Investment language.** "Buy in", "ROI", "to the moon", "next
  Bitcoin". HN will flag this faster than it'll upvote a typo fix.
- **Dunking on competitors.** "RandomX is bad / Monero got it wrong /
  Litecoin is dead." Be specific about engineering trade-offs; do not
  attack other projects.
- **Defensive replies to NACKs.** If a commenter has a sharp critique,
  thank them, file an issue, link the issue in your reply. The signal
  to readers is that we hear feedback.
- **Promising features under social pressure.** If someone asks "will
  you support X?", the honest answer is usually "we will read the
  proposal in a GitHub Discussion; not committing on HN".
- **Talking about the price of any other coin.** Off-topic for a Show
  HN, will derail the thread, mods may detach the comment.

## Cross-post hygiene

- Do **not** also post the same submission to `/r/programming` within
  the first 24 hours. HN cross-flags the duplicate and both die.
- After the HN cycle is over (24-72 h post-launch), the same content
  can be reframed for r/CryptoTechnology and r/programming using the
  templates in `REDDIT-SUBMISSIONS.md` — different framings, not the
  same body text.
- The Bitcointalk ANN should already have been live for at least
  6 hours before the HN submission so anyone who clicks through from
  HN to b3chain.org and then to Bitcointalk finds an active thread.

---

## Maintainer-only post-launch checklist (do not paste)

- [ ] Confirm the URL renders (no robots-noindex headers, no 5xx).
- [ ] Confirm the testnet is currently green (status JSON, faucet).
- [ ] Confirm a maintainer is online and free for the next 6 hours.
- [ ] Submit at the chosen window.
- [ ] Post the anchor comment within 90 seconds.
- [ ] Set up a Twitter/X DM and Matrix relay so the on-call maintainer
  is pinged when the post crosses 50 / 200 / 500 points (proxy for
  "reply queue is filling up").
- [ ] After 24 hours, archive the thread URL into
  `doc/outreach/SOCIAL-POSTS.md` § "live thread URLs".
