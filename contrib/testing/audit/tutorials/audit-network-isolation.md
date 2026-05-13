# Tutorial — Why network isolation matters more than people realise

## The problem in one sentence
If a B3Chain node accidentally peers with a Bitcoin node, the Bitcoin
node's headers can poison the B3Chain node's view of the chain — even
though the chains will never converge — wasting bandwidth and
confusing operators.

## The theory

Two pieces of data make a node a B3Chain node rather than a Bitcoin
node:

1. **Magic bytes** — the four-byte network identifier sent at the start
   of every P2P message. Bitcoin mainnet uses `f9beb4d9`. Anything
   else, B3Chain ignores.
2. **DNS seeds** — the bootstrap addresses a node uses on first start.
   Bitcoin's seeds (e.g. `seed.bitcoin.sipa.be`) return Bitcoin nodes;
   B3Chain's seeds (when set) must return B3Chain nodes only.

Both are constants in `src/kernel/chainparams.cpp`. A copy-paste error
that left a Bitcoin seed in the B3Chain mainnet `vSeeds` list would
silently funnel new nodes into trying to talk to the Bitcoin network
on every start.

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-network-isolation.py
```

The script:

1. Spawns a regtest node, sends a Bitcoin mainnet `version` message
   with magic `f9beb4d9`. Expects the connection to be dropped without
   acknowledgment.
2. Reads `chainparams.cpp` and verifies that the mainnet `vSeeds`
   vector contains zero hostnames matching the Bitcoin seed pattern
   (`bitcoin`, `bluematt`, `dashjr`, etc.) and zero entries from
   Bitcoin's `chainparams.cpp` directly.

## Exercise

Edit `src/kernel/chainparams.cpp`, in the `MAIN` chain branch, add a
line:

```cpp
vSeeds.emplace_back("seed.bitcoin.sipa.be");
```

Rebuild and re-run the audit. Expected output:

```
  FAIL  [N-1] mainnet vSeeds contains 'seed.bitcoin.sipa.be' (Bitcoin seed)
AUDIT RESULT: FAIL  [N-1]
```

## Why magic bytes alone don't save you

Even if your node correctly rejects Bitcoin's magic bytes at the wire
protocol, you still want it to never *try* to connect to a Bitcoin
node, because:

- Many port scanners flag the connection attempt and your IP gets on
  block lists.
- The Bitcoin node may waste CPU on the handshake before disconnecting.
- Your operator sees noise in their logs and starts to mistrust the
  software.

So the audit checks both layers.

## Further reading

- Bitcoin Core network constants: `src/kernel/chainparams.cpp`
  in [bitcoin/bitcoin](https://github.com/bitcoin/bitcoin)
- BIP-37 connection-bloom filter (early example of cross-chain
  protocol-level confusion concerns):
  github.com/bitcoin/bips/blob/master/bip-0037.mediawiki
- Tor exit-node policy notes — same principle: networks should refuse
  to forward traffic that doesn't belong to them.
