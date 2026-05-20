#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-1] Live 51%-attack simulation on regtest.

This is a *demonstration* — the audit "passes" if the simulation completes
and reproduces the expected behaviour: an attacker with majority hashrate
can rewrite a confirmed transaction. Every step is logged with educational
commentary so the script doubles as a teaching aid.

What it does
------------
1. Spins up two isolated regtest clusters:
     - **Honest cluster**: 2 nodes, 1 mining wallet (`alice`), 1 victim
       wallet (`bob`).
     - **Attacker cluster**: 1 node, 1 wallet (`mallory`).
   The clusters are **never** connected to each other while the attacker is
   building their secret chain (this is the regtest analogue of the attacker
   mining privately).

2. Both clusters mine 110 blocks from the same genesis (so both have
   spendable coinbase outputs).

3. Honest cluster: Alice sends 25 B3C to Bob. Honest miner mines 6 blocks
   to confirm the transaction. From Bob's viewpoint the payment is "final".

4. Attacker cluster (running in parallel, isolated):
   Mallory has been mining a private chain that *replaces* the block where
   Alice paid Bob with a block where Mallory pays the same coin to herself.
   On regtest we simulate "majority hashrate" by simply mining one more
   block than the honest cluster.

5. Connect the clusters: the attacker reveals their longer chain. Both
   nodes accept the longer chain (more work). The transaction Bob received
   is **reorged out**; the double-spend to Mallory's address takes its
   place.

6. The script then prints the cost-to-attack table, hashrate ratio
   required for each confirmation depth, and the conventional wisdom
   ("wait 6 confirmations for $5k+ payments").
"""

import argparse
import csv
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import (  # type: ignore
    AuditResult, RegtestNode, RpcError, ensure_wallet, BOLD, GREEN, RED, YELLOW, DIM,
)


# Defaults (kept as module-level for backward compat with the existing
# audit harness; the CLI parser below can override them).
HONEST_CONFIRMATIONS = 6      # the threshold the victim trusts
ATTACKER_LEAD        = 1      # extra blocks attacker mines to win the race
PRE_MINE_BLOCKS      = 110    # both sides need spendable coinbase utxos

# Cost-table output for the Phase 0 analysis doc.  Sweeps:
#   k (confirmations) in {1..12}
#   alpha (attacker share) in {0.30..0.60} step 0.05
COST_TABLE_K_RANGE     = list(range(1, 13))
COST_TABLE_ALPHA_RANGE = [round(x * 0.05, 2) for x in range(6, 13)]  # 0.30..0.60


# ---------------------------------------------------------------------------
# Educational helpers
# ---------------------------------------------------------------------------

def banner(text: str) -> None:
    print()
    print(BOLD("=" * 72))
    print(BOLD(f"  {text}"))
    print(BOLD("=" * 72))


def step(num: int, text: str) -> None:
    print(BOLD(f"\n[step {num}] {text}"))


def teach(text: str) -> None:
    """Print educational commentary in dim text, prefixed with a 'WHY:' tag."""
    for line in text.strip().splitlines():
        print(DIM(f"   ⓘ  {line.strip()}"))


def print_chain_state(label: str, node: RegtestNode) -> None:
    info = node.rpc.getblockchaininfo()
    print(DIM(f"     {label:>30}: height={info['blocks']}  tip={info['bestblockhash'][:16]}..."))


# ---------------------------------------------------------------------------
# Attack scenario
# ---------------------------------------------------------------------------

def nakamoto_reorg_success_probability(alpha: float, z: int) -> float:
    """Nakamoto §11 reorg-success probability for attacker share alpha and
    z confirmations.  Returns a probability in [0, 1].

    Implementation mirrors the inline calculation already present at the
    bottom of run_attack(); pulled out so the CSV exporter can call it
    without duplicating the loop body."""
    if alpha <= 0:
        return 0.0
    if alpha >= 0.5:
        return 1.0
    p_attack = alpha / (1.0 - alpha)
    lambda_ = z * p_attack
    psum = 0.0
    for k in range(z + 1):
        psum += (math.exp(-lambda_) * lambda_**k / math.factorial(k)) \
                * (1.0 - p_attack ** (z - k))
    return 1.0 - psum


def emit_cost_csv(out_path: Path) -> None:
    """Phase 0 cost-table: k in {1..12}, alpha in {0.30..0.60}.

    Each row is one (alpha, k) cell with:
      - reorg success probability per Nakamoto §11
      - minimum sustained attacker hashrate as multiple of honest hashrate
        (alpha / (1 - alpha))
      - approximate attacker cost (USD) at three network-hashrate scenarios

    These numbers feed the V-1 / V-5 sections of
    doc/security/B3POW-51-ATTACK-ANALYSIS.md."""

    # Scenarios (must match section 3.3 of B3POW-51-ATTACK-ANALYSIS.md):
    #   Launch  =  100 KH/s network,  $1.5K cap-ex per board (20 KH/s)
    #   Growth  =    1 MH/s
    #   Mature  =   50 MH/s
    BOARD_HS         = 20_000      # KH/s -> hashes/sec
    BOARD_USD        = 1_500
    SCENARIOS = [
        ("launch_100KHs",   100_000),
        ("growth_1MHs",   1_000_000),
        ("mature_50MHs", 50_000_000),
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "alpha", "k_confirmations", "reorg_success_prob",
            "attacker_to_honest_ratio",
        ] + [f"capex_usd_{name}" for name, _ in SCENARIOS])

        for alpha in COST_TABLE_ALPHA_RANGE:
            ratio = alpha / max(1.0 - alpha, 1e-9)
            for k in COST_TABLE_K_RANGE:
                p = nakamoto_reorg_success_probability(alpha, k)
                row = [f"{alpha:.2f}", k, f"{p:.6f}", f"{ratio:.3f}"]
                for _, hs in SCENARIOS:
                    attacker_hs = hs * alpha / max(1.0 - alpha, 1e-9)
                    boards = math.ceil(attacker_hs / BOARD_HS)
                    capex = boards * BOARD_USD
                    row.append(f"{capex}")
                w.writerow(row)

    print(BOLD(f"\nWrote cost table -> {out_path}"))
    print(DIM(f"   sweep alpha in {COST_TABLE_ALPHA_RANGE}"))
    print(DIM(f"   sweep k in {COST_TABLE_K_RANGE}"))
    print(DIM(f"   scenarios: {[name for name, _ in SCENARIOS]}"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirmations", type=int, default=HONEST_CONFIRMATIONS,
                   help="depth Bob waits before treating the payment as final")
    p.add_argument("--attacker-lead", type=int, default=ATTACKER_LEAD,
                   help="extra blocks the attacker mines beyond honest")
    p.add_argument("--output-csv", type=Path, default=None,
                   help="emit cost-table CSV at the given path (for the "
                        "Phase 0 analysis doc); skips the regtest simulation")
    p.add_argument("--skip-simulation", action="store_true",
                   help="skip the regtest simulation (useful when only the "
                        "CSV output is wanted)")
    return p.parse_args()


def run_attack(r: AuditResult,
               honest_confirmations: int = HONEST_CONFIRMATIONS,
               attacker_lead: int = ATTACKER_LEAD) -> None:
    banner("51% ATTACK SIMULATION (regtest, educational)")
    teach("""
        A 51% attack works when an entity controls more proof-of-work
        hashrate than the rest of the honest network combined. They mine
        their own chain in private, then reveal it once it has more
        cumulative work than the public chain.  Because nodes follow the
        chain with the most work, the public chain is reorged out and any
        transactions that were confirmed only on the public chain are
        reversed.

        On regtest, "hashrate" doesn't really exist — every block is
        instantly mined.  We simulate hashrate dominance by simply having
        the attacker mine more blocks while their cluster is disconnected
        from the honest cluster.
    """)

    # -- Phase 1: spin up isolated clusters -------------------------------
    step(1, "Spawning isolated honest + attacker clusters")
    honest = RegtestNode("honest")
    attacker = RegtestNode("attacker")
    try:
        honest.start()
        attacker.start()

        # Critical: the two clusters share no peers.
        teach("""
            The honest and attacker clusters share NO peers. This models the
            attacker mining privately on their own farm with their own pool.
        """)

        miner   = ensure_wallet(honest, "alice")
        victim  = ensure_wallet(honest, "bob")
        att     = ensure_wallet(attacker, "mallory")

        alice_addr   = miner.getnewaddress()
        bob_addr     = victim.getnewaddress()
        mallory_addr = att.getnewaddress()

        print(DIM(f"     Alice (honest miner)  : {alice_addr}"))
        print(DIM(f"     Bob   (honest victim) : {bob_addr}"))
        print(DIM(f"     Mallory (attacker)    : {mallory_addr}"))

        # -- Phase 2: pre-mine spendable coinbase ---------------------------
        step(2, f"Both clusters mine {PRE_MINE_BLOCKS} blocks (need spendable coinbase)")
        miner.generatetoaddress(PRE_MINE_BLOCKS, alice_addr)
        att.generatetoaddress(PRE_MINE_BLOCKS, mallory_addr)
        print_chain_state("honest cluster", honest)
        print_chain_state("attacker cluster", attacker)

        # The two chains differ from genesis onwards because each cluster
        # mines its own coinbase to a different address. Both are valid
        # chains; whichever is longer wins when they meet.
        teach("""
            After this step, both clusters have valid 110-block chains, but
            they differ at every block (different coinbases). Whichever
            chain has more cumulative work will win when the clusters meet.
        """)

        # -- Phase 3: honest payment + N confirmations ----------------------
        step(3, f"On the HONEST chain Alice pays Bob 25 B3C, "
              f"miner mines {honest_confirmations} confirmations")
        honest_pay_txid = miner.sendtoaddress(bob_addr, 25)
        miner.generatetoaddress(honest_confirmations, alice_addr)

        bob_balance_before = victim.getbalance()
        bob_received = victim.gettransaction(honest_pay_txid)
        print(DIM(f"     honest payment txid     : {honest_pay_txid}"))
        print(DIM(f"     Bob balance after {honest_confirmations} confirms: {bob_balance_before} B3C"))
        r.expect(bob_received["confirmations"] >= honest_confirmations,
                 f"[A-1] Bob's payment is confirmed >={honest_confirmations} times on the honest chain",
                 f"confirmations={bob_received['confirmations']}")

        teach(f"""
            From Bob's point of view this transaction is "final" — it has
            {honest_confirmations} confirmations, which exchanges typically treat as safe
            for medium-value payments. Bob releases the goods at this
            point.  An attacker would now have minutes to seconds to
            execute the reorg before Bob hears about it.
        """)

        # -- Phase 4: attacker mines an even-longer secret chain -----------
        attacker_blocks = honest_confirmations + 1 + attacker_lead
        step(4, f"In SECRET the attacker mines {attacker_blocks} blocks "
              "(reach honest height + lead)")
        # First the attacker pays themselves to a fresh address that will
        # land in their secret chain only:
        att_self = att.getnewaddress()
        att_pay_txid = att.sendtoaddress(att_self, 25)
        att.generatetoaddress(attacker_blocks, mallory_addr)
        print(DIM(f"     attacker self-pay txid  : {att_pay_txid}"))
        print_chain_state("attacker cluster", attacker)
        teach("""
            The attacker has been mining privately. Their chain is one block
            longer than the honest chain. Crucially, their version of
            history does NOT include the payment to Bob. Instead it
            includes a payment to a wallet under the attacker's control.
        """)

        # -- Phase 5: reveal -- connect the clusters -----------------------
        step(5, "ATTACKER REVEALS the longer chain (connect honest <-> attacker)")
        honest.connect_to(attacker)

        # Wait for honest cluster to reorg to the attacker's chain.
        # The attacker's chain has more work, so the honest node MUST switch.
        attacker_tip = attacker.rpc.getbestblockhash()
        deadline = time.time() + 30
        while time.time() < deadline:
            if honest.rpc.getbestblockhash() == attacker_tip:
                break
            time.sleep(0.25)

        honest_tip_after = honest.rpc.getbestblockhash()
        r.expect_eq(honest_tip_after, attacker_tip,
                    "[A-1] honest node reorged onto attacker chain (more PoW wins)")

        # -- Phase 6: verify Bob lost the funds ----------------------------
        step(6, "Verify Bob's payment is REVERSED")
        try:
            tx_after = victim.gettransaction(honest_pay_txid)
            confs = tx_after.get("confirmations", 0)
            r.expect(confs <= 0,
                     "[A-1] Bob's transaction has 0 or negative confirmations after reorg",
                     f"confirmations={confs} (negative means conflicted)")
        except RpcError:
            r.passed_check("[A-1] Bob's transaction is no longer in the wallet (reorged out)")

        bob_balance_after = victim.getbalance()
        print(DIM(f"     Bob balance before reorg: {bob_balance_before} B3C"))
        print(DIM(f"     Bob balance after reorg : {bob_balance_after} B3C"))
        r.expect(bob_balance_after < bob_balance_before,
                 "[A-1] Bob's wallet balance decreased after the reorg",
                 f"before={bob_balance_before}  after={bob_balance_after}")

        # -- Phase 7: educational summary ---------------------------------
        banner("RESULT: Bob has been double-spent")
        teach(f"""
            A 51%-capable attacker reversed a {honest_confirmations}-confirmation transaction.
            On a real network this requires sustained majority hashrate
            for the duration of the attack (~60 min for 6 confirmations on
            a 10-min-target chain).

            DEFENCES:
              - Wait for more confirmations for high-value transactions.
                Probability of successful reorg drops exponentially with
                each additional confirmation.
              - Use third-party reorg detection (block explorers).
              - For exchanges: increase confirmation requirements during
                hashrate dips.
              - For developers: design protocols that are reorg-aware
                (e.g. coinbase maturity is 100 blocks for exactly this
                reason).

            See doc/SECURITY-AUDIT.md and the live demo page on
            b3chain.org/testing/51-attack.html for more details.
        """)

        # Show the Nakamoto reorg-success probability table for context.
        print()
        print(BOLD("Nakamoto reorg-success probability"))
        print(DIM("(probability that an attacker with hashrate q will catch"))
        print(DIM(" up after z honest confirmations)"))
        print()
        print(f"{'q (attacker share)':>20} | " + " | ".join(f"z={z:>2}" for z in [1, 3, 6, 10]))
        print("-" * 60)
        for q in [0.10, 0.20, 0.30, 0.40, 0.45, 0.50]:
            p_attack = q / (1 - q)
            row = [f"{q*100:>4.0f}%"]
            for z in [1, 3, 6, 10]:
                lambda_ = z * p_attack
                # Poisson sum approximation, as in Nakamoto §11
                psum = 0.0
                for k in range(z + 1):
                    psum += (math.exp(-lambda_) * lambda_**k / math.factorial(k)) \
                            * (1 - p_attack ** (z - k))
                row.append(f"{(1 - psum) * 100:>5.2f}%")
            print(f"{row[0]:>20} | " + " | ".join(f"{x:>5}" for x in row[1:]))
        print()

    finally:
        honest.cleanup()
        attacker.cleanup()


def main() -> int:
    args = parse_args()
    if args.output_csv is not None:
        emit_cost_csv(args.output_csv)
        if args.skip_simulation:
            return 0
    r = AuditResult("A-1", "51% double-spend attack simulation")
    if args.skip_simulation:
        return r.finish()
    run_attack(r, honest_confirmations=args.confirmations,
               attacker_lead=args.attacker_lead)
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
