# Response Runbook: 51%-Attack on b3chain

**Audience.** b3chain node operators, exchange wallet operators,
SPV-wallet providers, the b3chain core security team.

**Companion documents.**
- [`B3POW-51-ATTACK-ANALYSIS.md`](B3POW-51-ATTACK-ANALYSIS.md): full
  threat model and per-mitigation rationale.
- [`SECURITY-AUDIT.md`](../SECURITY-AUDIT.md): audit-row inventory.
- [`SECURITY-INHERITANCE.md`](../SECURITY-INHERITANCE.md): per-rule
  inheritance from Bitcoin Core.

This runbook is an **incident-response checklist**. It does not
attempt to teach the underlying defenses; for that see the analysis
document. The intent here is to give an on-call operator a single
page they can paste into a war-room without re-deriving the model.

## 0. Detection triggers

You should run this runbook when **any** of the following are true:

| Signal | Where it surfaces | Threshold |
|---|---|---|
| Long deep reorg | RPC `getchaintips` | depth > 50, NOT yet at `max_reorg_depth=200` cap |
| `BLOCK_DEEP_REORG` rejections | `debug.log` `deep-reorg-attempt` | any |
| Mass `BLOCK_POW_BUDGET` rejections | `debug.log` `b3pow-budget-exceeded` | > 100 / hour |
| Sudden hashrate drop (>30 %) | block timestamps vs LWMA-3 retarget | sustained for > 1 hour |
| Stratum disconnect storm | miner-pool logs | > 50 % of pool peers gone |
| Exchange double-spend report | out-of-band, e.g. exchange security email list | any credible single report |

**Stop. Confirm the trigger is real before acting.** False-positive
runbook executions damage credibility with exchanges and miners.

## 1. Acknowledge and freeze (5 min)

1. On the secure-channel war room (Signal / Matrix / IRC; not Twitter),
   page:
   - b3chain core security on-call
   - the top-3 mining pool operators
   - the top-5 exchange security contacts
2. Time-stamp the trigger in the war-room channel. The timestamp is
   the reference for every later step.
3. Tell exchanges: **raise their confirmation requirement immediately**
   (BTC convention is 6 → 12 → 24 confirmations). They control this in
   their own wallet stack; b3chain core cannot do it for them.
4. **Do not push any binary patches yet.** A surprise binary release
   during an attack is its own incident vector.

## 2. Diagnose (15 min)

Pull the following data into the war room:

```bash
# Confirm the attack shape.
b3chain-cli getchaintips             # list every known tip + depth
b3chain-cli getblockchaininfo        # active tip height + chainwork
b3chain-cli getnetworkhashps 144     # hashrate, last 144 blocks
b3chain-cli getnetworkhashps 2016    # hashrate, last 2016 blocks

# Did our peer set get eclipsed?
b3chain-cli getpeerinfo | jq '.[].subver' | sort | uniq -c
b3chain-cli getnetworkinfo

# Pull last hour of validation log.
grep -E 'deep-reorg-attempt|b3pow-budget-exceeded|stale-tip-headers|checkpoint-mismatch' \
     ~/.b3chain/debug.log | tail -200
```

**Classify** the attack into one of:

| Attack class | Fingerprint | Section |
|---|---|---|
| Steady-state reorg | deep reorg, no hashrate drop | §3 |
| Hashrate collapse (>50 %) | sustained spacing > 1500s, normal reorgs | §4 |
| Eclipse / Sybil | tiny per-peer subver fingerprint diversity, lots of fresh peers | §5 |
| Pool-targeted DoS | normal chain, mass Stratum disconnects | §6 |

## 3. Steady-state reorg playbook

Active mitigations already in the chain (do **NOT** re-enable; verify):

- `consensus.max_reorg_depth = 200`: any block that would force a
  reorg deeper than this is rejected as `deep-reorg-attempt`.
- LWMA-3 difficulty adjustment: even if the attacker has 60 % hashrate,
  difficulty re-adjusts within ~45 blocks.

Operator actions (mainnet binary, no recompile):

1. Pass `-paranoid-headers-sync` and restart the node. Tip-extending
   headers now require **3 peer confirmations** before commit.
   ```
   b3chaind -paranoid-headers-sync
   ```
2. Pass `-paranoid-headers-quorum=N` if your peer set is unusually
   small or large. Range \[1, 16\].
3. Raise `-maxconnections=300` (default 200) to widen the honest peer
   surface.
4. Tell exchanges to:
   - Raise confirmation requirement to 24 blocks (≈ 4 h at 600 s).
   - Pause deposits for the affected asset.

If the attack persists for more than **3 hours** despite the above,
escalate to §3.1.

### 3.0a. Operator-pinned recovery via M-14 RPCs (USE THIS FIRST)

Before escalating to §3.1 emergency checkpoint, try the per-node
M-14 RPCs landed in v1.1.3.  They are **reversible**, **per-node**
(no network-wide coordination required), and survive restart.  They
are the right answer when:

- You are confident the active tip on your node is canonical (you've
  diagnosed the attack and the reorg has not yet happened on your
  node), AND
- You want to refuse to accept any incoming candidate that would
  reorg past a chosen pin point, immediately, without waiting for
  the implicit M-4 cap (200 blocks ≈ 33 h) to fire.

#### Pin the current tip ("freeze recovery")

After §2 diagnosis confirms the chain you're on is the canonical one
and the recovery has begun building atop it:

```bash
# 1. Identify the block to pin.  Conservative choice: 6-deep below
#    the current tip, so legitimate same-day reorgs are unaffected.
TIP_HEIGHT=$(b3chain-cli getblockchaininfo | jq .blocks)
PIN_HEIGHT=$((TIP_HEIGHT - 6))
PIN_HASH=$(b3chain-cli getblockhash $PIN_HEIGHT)
echo "Pinning at height $PIN_HEIGHT, hash $PIN_HASH"

# 2. Finalize.
b3chain-cli finalizeblock "$PIN_HASH"

# 3. Sanity-check: source should now be "operator" and hash should
#    match PIN_HASH.
b3chain-cli getfinalizedblockhash
# -> { "hash": "...", "height": <PIN_HEIGHT>, "source": "operator" }
```

Any incoming candidate that would reorg past `PIN_HEIGHT` will now
be rejected with `BlockValidationResult::BLOCK_DEEP_REORG`, reason
`"reorg-past-finalized"`.  Net effect: same as an `M-4` cap fire at
the chosen pin point, applied per-node.

#### Park a suspect tip ("refuse to follow")

If you've identified a specific suspect chain (e.g. an attack-chain
candidate that just arrived on your peer feed), refuse to follow it
without permanently invalidating it:

```bash
# Suspect tip from `b3chain-cli getchaintips`
b3chain-cli parkblock "$SUSPECT_HASH"
```

This walks back from the active tip if the suspect IS the active
tip, disconnects to the parent, and marks the suspect (+ all its
descendants) with the `BLOCK_PARKED` flag.  Chain selection ignores
parked blocks; they are not propagated as invalid to peers.

#### Undo a finalize / park

Both operations are reversible:

```bash
# Undo finalizeblock
b3chain-cli unfinalizeblock
# (no argument; clears the single pin)

# Undo parkblock
b3chain-cli unparkblock "$BLOCK_HASH"
```

`unparkblock` walks the parked chain segment and clears `BLOCK_PARKED`
and any `BLOCK_FAILED_*` flags ParkBlock set, then re-activates the
best chain (which may reorg onto the previously-parked branch if it
has more work).  `unfinalizeblock` is a single-call clear of the
operator pin.

#### Continuous monitoring

The watcher daemon (`contrib/monitoring/51attack-watch.py`) will
emit alerts when the pin changes:

- `finalized_drift_source_flip` — informational, fires on every
  `finalizeblock` / `unfinalizeblock`.
- `finalized_drift_operator_change` — warning, fires on a
  re-finalize without first unfinalizing (= "did someone else with
  RPC access just touch the pin?").
- `finalized_drift_horizon_stall` — warning, fires when the implicit
  M-4 horizon stops advancing while tip does (= tip stalled vs cap).

#### When to escalate to §3.1 anyway

M-14 is per-node.  If your goal is **network-wide** rejection of an
attack chain so unrelated exchanges and SPV providers also refuse
it, that is what §3.1 (emergency checkpoint) is for, and the two
mechanisms are intentionally orthogonal:

- M-14 fastest, no coordination, no permanence; can re-finalize at
  any time.
- §3.1 slow, requires coordination, but applies network-wide once
  pools and exchanges all load the same JSON file.

In practice you may want to do M-14 immediately on your own infra
and start the §3.1 coordination call in parallel.

### 3.1. Emergency checkpoint (LAST RESORT)

The binary ships **ZERO checkpoints**. The
`-assumevalidcheckpoints=<path>` flag is a break-glass mechanism that
loads a JSON file of `(height, hash)` pairs and rejects any block
proposing a different hash at one of those heights.

**Do not use this unilaterally.** Use only after:

- Top-3 mining pool operators agree on the (height, hash) pair.
- At least two exchanges agree to enforce the same pair.
- The pair is published on the b3chain.org status page and signed by
  the b3chain core security key.

JSON format (UTF-8, see `src/node/emergency_checkpoints.h`):

```json
{
  "schema": 1,
  "checkpoints": [
    {"height": 47312, "hash": "0000000123abcdef...64-hex"}
  ]
}
```

Apply on every cooperating node:

```bash
b3chaind -assumevalidcheckpoints=/etc/b3chain/emergency-2026-05.json
```

Nodes that load the file reject any chain that does not contain the
listed block at the listed height. **This is a temporary measure.**
Remove the flag once the network has reorganised onto a single tip
for ≥ 1 week.

## 4. Hashrate collapse playbook

Triggered by a sustained slowdown (e.g. > 1500 s avg spacing for 1+ hour).

Active mitigations:

- LWMA-3 retargets every block, so within ~30 blocks (~5 h at 1000 s)
  difficulty falls to match the surviving hashrate.
- **M-13 (F-6 fix) bounds the floor.** During the collapse, LWMA-3
  cannot widen the target past `operating_pow_floor_bits = 0x1d3fffff`
  (post-bootstrap) or `powLimit = 0x1d7fffff` (during the early
  guard).  So even at the floor, one B3Miner-1 board still needs
  ≈ 27 min (powLimit) or ≈ 55 min (operating floor) to find a block.
  This caps how much "free hashrate" an attacker can extract from
  a coordinated drop-out by hiding a private fork at the floor.

Operator actions:

1. **Do not panic.** With LWMA-3, recovery is automatic.
2. Reach out to known mining pool operators on the war-room channel;
   confirm whether the missing hashrate is a coordinated halt or an
   ISP / exchange / region outage.
3. If the hashrate cliff is **deliberate** (e.g. coordinated abandonment
   by a single farm), prepare to invoke §3.1 (emergency checkpoint) if
   the abandoner shows up with a stale-but-deep fork later.

## 5. Eclipse / Sybil playbook

Active mitigations:

- `DEFAULT_MAX_PEER_CONNECTIONS = 200` (raised from Bitcoin's 125 for
  M-8).
- `-paranoid-headers-sync` requires multi-peer header confirmation.

Operator actions:

1. Enable both:
   ```
   b3chaind -paranoid-headers-sync -paranoid-headers-quorum=5
   ```
2. Manually pin known-good peers:
   ```
   b3chaind -addnode=seed1.b3chain.org -addnode=seed2.b3chain.org \
            -addnode=seed3.b3chain.org
   ```
3. Disconnect everything else:
   ```
   for peer in $(b3chain-cli getpeerinfo | jq -r '.[].id'); do
     b3chain-cli disconnectnode "" $peer
   done
   ```
   The node will reconnect to the pinned addnodes and to fresh
   randomly-discovered peers.
4. If you have ≥ 1 trusted out-of-band peer (a friend's node, a
   colocated bare-metal box on a different ISP), confirm tip hashes
   match between your node and theirs.

## 6. Pool-targeted DoS playbook

This is not strictly a 51%-attack, but it is a common precursor:
take down the largest mining pool's Stratum endpoint, scoop up the
freed hashrate at your own pool, then attack with the resulting share
of the network.

Operator actions (mining pool operators only):

1. Switch Stratum to an alternate IP / DNS endpoint.
2. Coordinate with peer pools to publish the new endpoint via the
   miner-relay channel.
3. Notify b3chain core security so they can alert other pools.

## 7. Post-incident

Within 7 days of a triggered runbook execution:

1. Author a public post-mortem on b3chain.org. Include the timestamped
   detection trigger, every step taken, and an honest assessment of
   what worked / didn't.
2. Update `B3POW-51-ATTACK-ANALYSIS.md` with new lessons (new attack
   vector / cost adjustment / etc.) — open a PR.
3. If an emergency checkpoint was used:
   - Coordinate its **removal** from operator configs after the
     network has converged for ≥ 1 week.
   - File a follow-up to harden the protocol so that the same attack
     can't recur (this is the real cost of using a checkpoint; pay it).

## 8. Reference: chain-config knobs

These do not require a recompile (set via command line / config file):

| Flag | Default | Crisis value | Notes |
|---|---|---|---|
| `-paranoid-headers-sync` | off | on | M-8 |
| `-paranoid-headers-quorum` | 3 | 5 | M-8 |
| `-maxconnections` | 200 | 300 | M-8 |
| `-assumevalidcheckpoints` | unset | path | M-9, last resort |
| `-addnode` | empty | pin known-good | always safe |
| `-banscore` (PeerManager) | 100 | unchanged | default already aggressive |

These do require a recompile (consensus parameters):

| Parameter | Mainnet | Notes |
|---|---|---|
| `consensus.max_reorg_depth` | 200 | M-4 / F-3 |
| `consensus.use_lwma3` | true | M-3 |
| `consensus.enforce_BIP94` | true | M-2 / F-2 |
| `consensus.b3pow_cache_depth` | 8 | M-6 / F-5 |
| `consensus.b3pow_verify_budget_ms` | 50 | D1/D2 |
| `consensus.powLimit` | `0x1d7fffff` | M-13 / F-6 |
| `consensus.operating_pow_floor_bits` | `0x1d3fffff` | M-13 / F-6 |

## 9. Contact

- b3chain core security: `security@b3chain.org` (PGP key on
  b3chain.org/security).
- Status page: https://b3chain.org/status
- Incident war-room: announced via the status page.

---

*Last updated: 2026-05-19. Document version 1.0.0.*
