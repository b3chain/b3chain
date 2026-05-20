# 51% Attack on b3chain — One-Page Response Summary

**Audience:** node operators, exchanges, pool operators, on-call security.
**Purpose:** condensed answer to "what happens if α ≥ 50% appears, and what do
we do to recover?" Bridges the threat model and the operator runbook into a
single page suitable for war-room paste-in.
**Last updated:** 2026-05-19
**Companion documents:**
[`B3POW-51-ATTACK-ANALYSIS.md`](B3POW-51-ATTACK-ANALYSIS.md) (full threat model and per-mitigation rationale),
[`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md) (incident-response checklist),
[`51-MONITORING-OPS.md`](51-MONITORING-OPS.md) (detection wiring).

---

## TL;DR

B3PoW-Scratch is engineered so that a 51% attack **cannot rewrite arbitrary
history**. Its blast radius is bounded by consensus rules to ≈ 200 blocks
(≈ 33 h at 600 s spacing); the recovery procedure is a graded incident-response
playbook; the emergency checkpoint is the last resort and requires multi-party
agreement to invoke.

---

## 1. What actually happens if α ≥ 50% appears

Seven independent defensive layers activate automatically the moment an
attacker pushes a competing chain. They don't *prevent* the attempt; they
*bound* it.

| What the attacker tries | What B3Chain does | Reference |
|---|---|---|
| Mine a private chain >200 blocks deep and reveal it | Rejected as `BLOCK_DEEP_REORG` / `deep-reorg-attempt`. Hard consensus rule — no recompile, no human in the loop. | M-4 in `B3POW-51-ATTACK-ANALYSIS.md` §1.2; runbook §3 |
| Feed stale-tip headers to honest nodes | Depth-aware ban score: every stale-tip header costs progressively more peer score. Hostile peers self-eject. | M-5 |
| Time-warp the difficulty downward | BIP94 enforced on mainnet — closes the vector entirely. | M-2 |
| Drop out to crash difficulty, then attack at the floor | LWMA-3 retargets every block (~10 h response, vs Bitcoin's 14 days); `powLimit = 0x1d7fffff` + `operating_pow_floor_bits = 0x1d3fffff` cap how low difficulty can fall (M-13 / F-6 fix). | M-3, M-13 |
| Flood expensive headers (verifier DoS) | 50 ms wall-clock budget per header, depth-asymmetric (50/25/10 ms), 256-header batch cap, 2-tier pinned LRU cache. | D1/D2/D3 + M-6, M-7 |
| Selfish mining (withhold blocks) | LWMA-3 shrinks the compounding window; `max_reorg_depth = 200` caps maximum withholding to ≈ 33 h of work. | M-3, M-4 |
| Eclipse a victim's peer set | Default `-maxconnections = 200` (up from 125); `-paranoid-headers-sync` requires 3-peer confirmation. | M-9, M-10 |

**Bottom line.** The worst an attacker with α ≥ 50% can do on a B3Chain node
running default settings is **reorg the last ≈ 200 blocks (≈ 33 h at 600 s
spacing)**. Anything beyond that is rejected at the consensus layer. There is
no scenario in the threat model where attacker-controlled hashrate rewrites
finalized history.

---

## 2. Detection — what surfaces first

Canonical triggers (runbook §0):

| Signal | Where it surfaces | Threshold |
|---|---|---|
| Long deep reorg | RPC `getchaintips` | depth > 50, not yet at `max_reorg_depth = 200` cap |
| `BLOCK_DEEP_REORG` rejections | `debug.log` `deep-reorg-attempt` | any |
| Mass `BLOCK_POW_BUDGET` rejections | `debug.log` `b3pow-budget-exceeded` | > 100 / hour |
| Sustained hashrate drop (> 30%) | block timestamps vs LWMA-3 retarget | sustained > 1 hour |
| Stratum disconnect storm | miner-pool logs | > 50% of pool peers gone |
| Exchange double-spend report | out-of-band channel | any credible single report |

**Confirm the signal is real before acting** — runbook §0 explicitly warns
that false-positive runbook executions damage credibility with exchanges
and miners.

---

## 3. The recovery procedure (graded, not panic)

Four playbooks indexed by attack class. None require pushing a new binary
during the incident (which is itself a stated anti-pattern — runbook §1 step 4:
*"Do not push any binary patches yet."*).

### Phase A — Acknowledge & freeze (5 min, runbook §1)

1. Page on the secure war-room channel (Signal / Matrix / IRC — **not Twitter**):
   core security on-call, top-3 pool operators, top-5 exchange security contacts.
2. Timestamp the trigger.
3. Tell exchanges to raise confirmations (6 → 12 → 24) and pause deposits.

### Phase B — Diagnose (15 min, runbook §2)

```bash
b3chain-cli getchaintips
b3chain-cli getblockchaininfo
b3chain-cli getnetworkhashps 144
b3chain-cli getnetworkhashps 2016
b3chain-cli getpeerinfo | jq '.[].subver' | sort | uniq -c
grep -E 'deep-reorg-attempt|b3pow-budget-exceeded|stale-tip-headers|checkpoint-mismatch' \
     ~/.b3chain/debug.log | tail -200
```

Classify into one of: **steady-state reorg** (§3), **hashrate collapse** (§4),
**eclipse / Sybil** (§5), **pool-targeted DoS** (§6).

### Phase C — Operator actions per class

**Steady-state reorg** (the textbook 51% attack), runbook §3:

```bash
b3chaind -paranoid-headers-sync                # 3-peer confirm tip headers
b3chaind -paranoid-headers-quorum=5            # widen quorum for small peer sets
b3chaind -maxconnections=300                   # widen honest peer surface
```

Tell exchanges to raise confirmations to **24 blocks (≈ 4 h)** and pause
deposits.

**Eclipse / Sybil** (runbook §5):

```bash
b3chaind -addnode=seed1.b3chain.org \
         -addnode=seed2.b3chain.org \
         -addnode=seed3.b3chain.org

for peer in $(b3chain-cli getpeerinfo | jq -r '.[].id'); do
  b3chain-cli disconnectnode "" $peer
done
```

**Hashrate collapse** (runbook §4): **do nothing dramatic** — LWMA-3 recovers
automatically in ≈ 30 blocks. Coordinate with pool operators to confirm it's
deliberate vs. an outage.

### Phase D — Last resort: emergency checkpoint (runbook §3.1)

If the attack persists for **> 3 hours** despite the above, only then invoke
the `-assumevalidcheckpoints` break-glass. The binary ships **zero checkpoints
by default** — this is opt-in, off-by-default, and explicitly *cannot be
invoked unilaterally*:

> Use only after: top-3 mining pool operators agree on the (height, hash)
> pair; at least two exchanges agree to enforce the same pair; the pair is
> published on the b3chain.org status page and signed by the b3chain core
> security key.

JSON format:

```json
{
  "schema": 1,
  "checkpoints": [
    {"height": 47312, "hash": "0000000123abcdef...64-hex"}
  ]
}
```

Apply on cooperating nodes:

```bash
b3chaind -assumevalidcheckpoints=/etc/b3chain/emergency-2026-05.json
```

Nodes loaded with the file reject any chain that doesn't contain the listed
block at the listed height. **Remove the flag once the network has converged
for ≥ 1 week** — leaving it on permanently is itself a centralization risk.

---

## 4. Post-incident (runbook §7) — non-optional

Within 7 days:

1. Public post-mortem on b3chain.org with full timestamped timeline.
2. Open a PR updating `B3POW-51-ATTACK-ANALYSIS.md` with the new lessons
   (new vector / revised cost / new mitigation).
3. If an emergency checkpoint was used, **coordinate its removal** and file
   a follow-up to harden the protocol so the same attack can't recur. The
   analysis doc is explicit: that follow-up is *"the real cost of using
   a checkpoint; pay it."*

---

## 5. What we explicitly do **not** claim

From `B3POW-51-ATTACK-ANALYSIS.md` §9 — restating the unstated assumptions
other coin launches gloss over:

1. **B3PoW-Scratch is not "ASIC-proof"** — it is FPGA-economical and
   on-chip-memory-bound. The bound is economic (NRE cost vs. network reward),
   not algorithmic.
2. **A low-hashrate chain is reorganisable** — true of every PoW chain.
   The launch phase (weeks 0–12) is when V-5 bootstrap-reorg cost is lowest
   (`$1.5K–150K`, per §5 V-5 cost table).
3. **No PoW chain has absolute finality.** `max_reorg_depth = 200` introduces
   a **consensus-level** finality cap at ~33 h — a deliberate trade-off.
   Operators who reject this trade-off can opt out via `-no-max-reorg-depth`.
4. **No checkpoints ship by default.** Operators who want pinned-block
   protection during the vulnerable bootstrap weeks must opt in and curate
   the list themselves.

---

## 6. The point

Automatic consensus defenses do the heavy lifting; operators apply operational
knobs; the emergency checkpoint is the final break-glass and requires
multi-party agreement to invoke. **No single party — including b3chain
core — can unilaterally rewrite the chain to recover from an attack**, which
is the design intent.

---

*Document version 1.0.0. Source consolidation of
[`B3POW-51-ATTACK-ANALYSIS.md`](B3POW-51-ATTACK-ANALYSIS.md) and
[`RESPONSE-RUNBOOK-51ATTACK.md`](RESPONSE-RUNBOOK-51ATTACK.md).*
