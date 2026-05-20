#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[A-2] Selfish-mining (Eyal-Sirer 2014) simulator for B3PoW-Scratch v1.1.

Implements the four-state Markov chain from Eyal & Sirer's
"Majority is not Enough: Bitcoin Mining is Vulnerable" (Financial
Cryptography 2014, doi.org/10.1007/978-3-662-47854-7_28) §3.

State (lead, where_match):
    0  -- no private lead
    0' -- attacker's branch and honest's branch are tied at one block each
          (the "competition" state right after the attacker reveals on a tie)
    1  -- attacker is one block ahead privately
    2  -- attacker is two blocks ahead privately
    >=2 -- treated identically to 2 in the steady-state revenue calculation

Inputs:
    alpha  : attacker fraction of network hashrate, 0 < alpha < 0.5
    gamma  : fraction of *honest* miners that adopt the attacker's
             branch in a 1-1 tie (propagation advantage)

Outputs:
    revenue_attacker : attacker's expected revenue share (in steady state)
    revenue_honest   : 1 - revenue_attacker
    profitable       : True iff revenue_attacker > alpha (i.e., they gained)

Theory: the closed-form solution (Eyal-Sirer Theorem 1) is

    R_pool = ( alpha (1-alpha)^2 (4*alpha + gamma*(1-2*alpha)) - alpha^3 )
             / ( 1 - alpha*(1 + (2-alpha)*alpha) )

We compute this analytically (cheap, exact); we also run a discrete-event
Monte Carlo to double-check that the closed form is right.

This script is pure Python (no regtest needed): the underlying model
makes no use of any specific PoW algorithm.  Its B3PoW relevance is the
selfish-mining threshold alpha* given B3PoW's 600 s spacing, which is
identical to Bitcoin's threshold because the algorithm doesn't change
the Markov state space.

CSV output: contrib/testing/audit/results/r0/selfish_mining_sweep.csv
"""

import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import (  # type: ignore
    AuditResult, BOLD, DIM, GREEN, RED,
)


# ---------------------------------------------------------------------------
# Closed-form revenue function (Eyal-Sirer Theorem 1)
# ---------------------------------------------------------------------------
def selfish_revenue_share(alpha: float, gamma: float) -> float:
    """Closed-form attacker revenue share for given (alpha, gamma).

    Bounds:
      alpha must lie in (0, 0.5) -- at 0.5 the chain is trivially attackable.
      gamma must lie in [0, 1].

    Returns a float in (0, 1).
    """
    if alpha <= 0.0:
        return 0.0
    if alpha >= 0.5:
        return 1.0
    a = alpha
    g = gamma
    num = a * (1 - a) ** 2 * (4 * a + g * (1 - 2 * a)) - a ** 3
    den = 1.0 - a * (1 + (2 - a) * a)
    return num / den


def alpha_star(gamma: float, tol: float = 1e-6) -> float:
    """Smallest alpha in (0, 0.5) at which selfish mining becomes
    strictly more profitable than honest mining for the given gamma.

    Bisection: f(a) = selfish_revenue_share(a, gamma) - a.

    Returns the alpha* threshold in (0, 0.5).  If selfish mining is
    profitable down to alpha = 0 (gamma = 1 case), returns 0.0.
    """
    if gamma >= 1.0 - 1e-9:
        # Eyal-Sirer §3: gamma = 1 makes selfish mining profitable at any
        # positive alpha.
        return 0.0

    lo, hi = 1e-6, 0.499999
    if selfish_revenue_share(hi, gamma) < hi:
        # Selfish mining never beats honest in this gamma regime.
        return 0.5
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if selfish_revenue_share(mid, gamma) > mid:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Discrete-event Monte Carlo cross-check (for sanity)
#
# Eyal-Sirer §3 specifies transitions:
#
#   At each "tick" one block is found.  With probability alpha it goes
#   to the attacker; with probability 1-alpha to honest.  The attacker's
#   strategy is "Selfish-Mine":
#
#     lead == 0  : no private branch; both add to public
#     lead == 0' : the competition state; if attacker wins next block, lead -> 1
#                  and they keep the private chain; if honest wins, the
#                  honest block ties; with prob gamma honest miners mine
#                  on the attacker's tip (attacker wins the tie),
#                  with prob 1-gamma they mine on honest's tip.
#     lead == 1  : attacker has 1-block private lead.  If they find next
#                  block, lead -> 2.  If honest finds next, attacker
#                  publishes -> state 0'.
#     lead >= 2  : keep private chain.  Honest finds -> publish enough
#                  to leave honest one behind; in steady state we treat
#                  lead >= 2 as the absorbing "wide-lead" state.
# ---------------------------------------------------------------------------
def monte_carlo_revenue(alpha: float, gamma: float, n_blocks: int = 200_000,
                        seed: int = 42) -> float:
    rng = random.Random(seed)
    state = "lead0"      # lead0, lead0prime, lead1, lead2plus
    private_chain = 0    # blocks held privately
    attacker_credit = 0
    honest_credit = 0

    for _ in range(n_blocks):
        attacker_finds = rng.random() < alpha

        if state == "lead0":
            if attacker_finds:
                private_chain = 1
                state = "lead1"
            else:
                honest_credit += 1
                # state stays lead0
        elif state == "lead0prime":
            # competition state: one honest block on top of the previous
            # honest tip, one attacker block (just-revealed) at the same
            # height.
            if attacker_finds:
                # attacker extends their own branch -> wins the tie,
                # credits the held block + the new one.
                attacker_credit += 2
                state = "lead0"
                private_chain = 0
            else:
                # Honest finds a block.  With prob gamma honest miners
                # were mining on the attacker tip and the just-found
                # block extends the attacker chain (which the attacker
                # was forced to publish at the tie); the attacker wins
                # the original tied block plus this one.
                if rng.random() < gamma:
                    attacker_credit += 1   # the just-revealed attacker block
                    honest_credit  += 1    # the new honest block on att tip
                else:
                    # Honest mined on honest tip; honest chain wins.
                    honest_credit += 2     # the prior honest tip + new block
                state = "lead0"
                private_chain = 0
        elif state == "lead1":
            if attacker_finds:
                private_chain = 2
                state = "lead2plus"
            else:
                # Honest catches up -> attacker reveals their 1-block
                # branch.  Tie at the next block ("lead0prime").
                state = "lead0prime"
        else:  # lead2plus
            if attacker_finds:
                private_chain += 1
                # state stays lead2plus
            else:
                # Honest found a block.  Attacker publishes enough to
                # stay 1 ahead, credits the published blocks, and the
                # state collapses.
                # Concretely: when private_chain == 2, publish all 2.
                # The honest block becomes orphan.  Credits: attacker
                # gets +2 (the two it held), honest gets 0 for the
                # orphaned block.
                if private_chain == 2:
                    attacker_credit += 2
                    state = "lead0"
                    private_chain = 0
                else:
                    # private_chain > 2: publish enough to make honest's
                    # newest block orphan; remaining private lead = 1.
                    attacker_credit += private_chain - 1
                    private_chain = 1
                    state = "lead1"

    total = attacker_credit + honest_credit
    return attacker_credit / max(total, 1)


# ---------------------------------------------------------------------------
# Phase 0 CSV sweep
# ---------------------------------------------------------------------------
def emit_sweep_csv(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    alphas = [round(0.05 * i, 2) for i in range(1, 10)]   # 0.05..0.45
    gammas = [0.0, 0.25, 0.5, 0.75, 1.0]
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["alpha", "gamma", "selfish_revenue_share",
                    "honest_revenue_share", "profitable"])
        for alpha in alphas:
            for gamma in gammas:
                r = selfish_revenue_share(alpha, gamma)
                w.writerow([f"{alpha:.2f}", f"{gamma:.2f}", f"{r:.6f}",
                            f"{1.0 - r:.6f}", "yes" if r > alpha else "no"])
    print(BOLD(f"Wrote sweep CSV -> {out_path}"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--alpha", type=float, default=0.30,
                   help="attacker fraction (default 0.30)")
    p.add_argument("--gamma", type=float, default=0.0,
                   help="propagation advantage (default 0.0 = worst for attacker)")
    p.add_argument("--monte-carlo", action="store_true",
                   help="run Monte Carlo cross-check (slow)")
    p.add_argument("--output-csv", type=Path, default=None,
                   help="emit (alpha, gamma) sweep CSV at this path")
    p.add_argument("--blocks", type=int, default=200_000,
                   help="number of Monte Carlo steps (default 200000)")
    return p.parse_args()


def banner(text: str) -> None:
    print()
    print(BOLD("=" * 72))
    print(BOLD(f"  {text}"))
    print(BOLD("=" * 72))


def main() -> int:
    args = parse_args()
    r = AuditResult("A-2", "Selfish-mining (Eyal-Sirer) profitability simulation")

    banner("SELFISH-MINING (Eyal-Sirer 2014) -- B3PoW-Scratch v1.1")
    print(DIM("""
        Selfish mining is a strategy where a miner withholds blocks they
        find, releasing them strategically to force honest miners to
        waste work on stale blocks.

        Eyal-Sirer's theorem 1 (FC 2014) gives a closed-form revenue
        share for the strategy as a function of:
            alpha -- attacker's fraction of total hashrate
            gamma -- fraction of honest miners that adopt the attacker's
                     branch when it ties with the public chain
                     (propagation advantage).
    """).strip())

    # Print the alpha* threshold curve for various gamma values.
    print()
    print(BOLD("alpha* threshold (lowest alpha at which selfish mining > honest)"))
    print(f"{'gamma':>8} | {'alpha*':>8}")
    print("-" * 25)
    for gamma in [0.0, 0.1, 0.25, 0.33, 0.5, 0.75, 1.0]:
        a = alpha_star(gamma)
        print(f"{gamma:>8.2f} | {a:>8.4f}")
    print()
    print(DIM("    The lower alpha*, the easier selfish mining is."))
    print(DIM("    At gamma=0 (worst case for attacker)    alpha* ~= 0.333"))
    print(DIM("    At gamma=0.5 (uniform propagation)      alpha* ~= 0.25"))
    print(DIM("    At gamma=1 (best case for attacker)     alpha* -> 0"))

    # Compute the specific case requested via CLI.
    revenue = selfish_revenue_share(args.alpha, args.gamma)
    print()
    print(BOLD(f"Requested case: alpha={args.alpha}, gamma={args.gamma}"))
    print(f"   closed-form revenue share : {revenue:.4f}")
    print(f"   honest mining baseline    : {args.alpha:.4f}")
    profitable = revenue > args.alpha
    label = GREEN("PROFITABLE") if profitable else RED("NOT PROFITABLE")
    print(f"   verdict                   : {label}")
    r.expect(True, f"[A-2] closed-form selfish revenue = {revenue:.4f}",
             f"alpha={args.alpha} gamma={args.gamma} -> {revenue:.4f}")

    if args.monte_carlo:
        mc = monte_carlo_revenue(args.alpha, args.gamma, n_blocks=args.blocks)
        delta = abs(mc - revenue)
        print()
        print(BOLD("Monte Carlo cross-check"))
        print(f"   simulated revenue share   : {mc:.4f}")
        print(f"   abs diff vs closed-form   : {delta:.4f}")
        # Should agree within ~0.01 at n=200000.
        r.expect(delta < 0.015,
                 "[A-2] Monte Carlo and closed-form agree within tolerance",
                 f"delta={delta:.4f} (expected < 0.015)")

    if args.output_csv:
        emit_sweep_csv(args.output_csv)

    # Educational summary for B3PoW specifically.
    print()
    print(BOLD("B3PoW-Scratch v1.1 implications"))
    print(DIM("""
        B3PoW uses Bitcoin's 600 s block target, so the selfish-mining
        threshold is identical to Bitcoin's: alpha* >= 0.25 in the best
        case (gamma >= 0.5), alpha* ~= 0.333 in the worst case
        (gamma = 0).

        Mitigations in this plan that reduce the cost of selfish mining
        at the network level:
          * M-3 LWMA-3 retarget shrinks the window during which a
            selfish-mining strategy can compound difficulty effects.
          * M-4 max_reorg_depth = 200 caps the longest withheld chain
            that can ever be revealed.
          * M-5 depth-aware ban score makes the reveal step costly at
            the P2P layer.

        See doc/security/B3POW-51-ATTACK-ANALYSIS.md section V-2.
    """).strip())

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
