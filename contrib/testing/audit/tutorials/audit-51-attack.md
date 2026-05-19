# Tutorial — How a 51% attack actually works (and what stops it)

## The problem in one sentence
A miner with majority hashpower can always re-write recent history;
the question is "how recent" and "at what cost", and the answer is
testable on regtest with the demo here.

## The theory (Nakamoto's race)

If the attacker controls fraction `q` of total hashpower (`p = 1 - q`
honest), the probability of catching up from `z` confirmations is:

\[ P_z = \left( \frac{q}{p} \right)^z \quad \text{for } q < p \]

For `q < 0.5` this decays exponentially in `z`. For `q ≥ 0.5` it is
**1** — the attacker wins eventually, with high probability.

Practical confirmation thresholds (Satoshi 2008, simplified):

| q (attacker share) | confirmations for P_z < 0.001 |
|--------------------|-------------------------------|
| 10%                | 6                             |
| 20%                | 11                            |
| 30%                | 24                            |
| 40%                | 89                            |
| 49%                | thousands (impractical)       |

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-51-attack-sim.py
```

The script:

1. Spawns two isolated regtest clusters (3 nodes each):
   "honest" and "attacker".
2. Honest cluster mines 100 blocks; attacker mines 99 from the same
   parent in private.
3. Honest cluster sends a transaction to a third party, gets 6
   confirmations.
4. Attacker secretly mines 7 more blocks (8 total > honest's 6),
   double-spending the same UTXO to an attacker-controlled address.
5. Attacker reveals the longer chain. Both clusters reorganise.
6. The original tx is reversed; the attacker's double-spend is now
   in the canonical chain.
7. Output: blocks reorganised, time elapsed, hashrate ratio required.

The demo runs in ~30s on regtest. On mainnet at typical difficulty,
the same scenario would cost many millions of dollars in compute time
and electricity — that's the gap that keeps Bitcoin safe.

## Exercise: the cost calculator

Open the script. The `attacker_hashrate_ratio` parameter controls how
much faster the attacker mines than the honest cluster. With
`ratio=2.0` (attacker has 2/3 of total hashpower), the attack
finishes in ~10s on regtest. With `ratio=1.05` (attacker has barely
51%), the attack still always succeeds but takes much longer in
expected wall time.

Try:

```bash
python3 contrib/testing/audit/audit-51-attack-sim.py --ratio 1.05 --timeout 600
```

You should see the attack succeed but take hundreds of seconds,
matching the exponential decay above.

## What protects B3Chain

Three layers, in increasing order of importance:

1. **B3PoW-Scratch v1.1 is memory-hard, reducing ASIC concentration
   risk in early days.** The PoW spends most of its time in a 1 MB
   per-header scratchpad walk (see
   [`contrib/miner/b3miner-rtl/SPEC.md`](../../miner/b3miner-rtl/SPEC.md)),
   so on-die SRAM/L1 buying power dominates the hashrate-per-watt
   curve rather than raw arithmetic throughput. That makes
   B3PoW-Scratch ASICs *possible* but expensive and slow to
   profitably outpace commodity CPUs and GPUs - much harder than
   building a stock SHA-256 ASIC. Bitcoin's SHA-256 ASIC market is
   concentrated in 5 companies; those companies could (in principle)
   repurpose hardware to attack a SHA-256 fork from day one. B3PoW
   doesn't have that problem yet.
2. **Conservative confirmation defaults.** Wallets and exchanges should
   require more confirmations for high-value B3Chain transactions in
   year one, until total hashrate grows enough that the cost-of-attack
   is high.
3. **Checkpoint key ceremony** (planned, see
   [`SECURITY-ROADMAP.md`](https://github.com/b3chain/b3chain/blob/b3chain-main/doc/SECURITY-ROADMAP.md)). Trusted
   maintainers sign post-launch checkpoint hashes; nodes can opt in to
   refuse reorgs deeper than the most recent checkpoint. Centralising
   in a way, but the recovery option exists if a sustained attack
   appears.

## What does NOT protect against 51%

- "Just keep upgrading the difficulty algorithm" — doesn't help; the
  attacker also benefits from the higher difficulty.
- "Detect the attacker by IP" — they're using cloud rental and
  rotating IPs.
- "Charge a fee for reorgs" — there's no protocol mechanism to do this
  generically.
- "Switch to PoS" — different security model; B3Chain is committed to
  PoW.

## Further reading

- Satoshi Nakamoto, "Bitcoin: A Peer-to-Peer Electronic Cash System",
  section 11 ("Calculations"):
  bitcoin.org/bitcoin.pdf
- Eyal & Sirer, "Majority is not Enough: Bitcoin Mining is
  Vulnerable" (selfish mining attack):
  arxiv.org/abs/1311.0243
- Bonneau et al., "SoK: Research Perspectives and Challenges for
  Bitcoin and Cryptocurrencies" (2015 IEEE S&P):
  cseweb.ucsd.edu/~smeiklejohn/files/ieeesp15.pdf
- Ethereum Classic 51% attacks (2019, 2020) — real-world examples of
  the cost-of-attack curve at small chain sizes.
