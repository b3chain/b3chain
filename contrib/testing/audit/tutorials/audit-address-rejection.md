# Tutorial — Cross-chain address confusion is the #1 user-reported fork bug

## The problem in one sentence
Users routinely paste Bitcoin addresses into B3Chain wallets (and vice
versa); a fork that silently accepts them is asking to lose money for
those users.

## The theory

Two address formats coexist on Bitcoin:

- **Base58Check P2PKH / P2SH** — version byte `0x00` (P2PKH, `1...`),
  `0x05` (P2SH, `3...`).
- **Bech32 / Bech32m** — HRP `bc` for mainnet (`bc1q...` for SegWit v0,
  `bc1p...` for Taproot), `tb` for testnet.

B3Chain reuses Base58 mathematics with a different version byte and
Bech32 mathematics with HRP `b3` (mainnet) / `tb3` (testnet). The
algorithm is unchanged; the prefix differs.

This is enough that an attacker cannot trivially make a B3Chain
address validate as a Bitcoin address. But it is **not** enough on its
own — RPC commands like `validateaddress`, `sendtoaddress`,
`importdescriptors` must each independently reject the wrong-network
input. A single missed code path means a user can lose funds by typing
in a Bitcoin address that the wallet politely accepts.

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-address-rejection.py
```

The script tries 36 real Bitcoin addresses (12 P2PKH, 8 P2SH, 8 Bech32
v0, 4 Bech32m Taproot, plus 4 invalid edge cases) against:

- `validateaddress`
- `sendtoaddress` (with `-fallbackfee` set, no-op if rejected)
- `importdescriptors` with a Bitcoin xpub

Every test must produce `isvalid: false` or an RPC error.

## Exercise

In `src/key_io.cpp`, locate `DecodeDestination`. Add a fallback that
also tries decoding with HRP `bc`:

```cpp
// Before
auto dest = DecodeBech32(str, params.Bech32HRP());
// After (BAD)
auto dest = DecodeBech32(str, params.Bech32HRP());
if (!IsValidDestination(dest)) {
    dest = DecodeBech32(str, "bc");  // accept Bitcoin too "for compatibility"
}
```

Rebuild, re-run the audit. Expected output:

```
  FAIL  [W-1] Bitcoin address bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4 was accepted
  FAIL  [W-1] sendtoaddress to bc1q... succeeded (should have rejected)
AUDIT RESULT: FAIL  [W-1]
```

## Defence in depth

Even with all 36 addresses rejected at the RPC layer, the audit also
checks the cross-derivation property: a B3Chain xpub at coin_type 9333
must produce different addresses than the same seed at Bitcoin's
coin_type 0. This catches the much subtler bug where the address
*format* is correctly rejected, but the *underlying private key* is
shared with a Bitcoin wallet — making any signed B3Chain transaction
potentially replayable on Bitcoin.

## Further reading

- BIP-173 Bech32 and SegWit address format
- BIP-350 Bech32m for Taproot
- BIP-44 multi-account hierarchy (and why coin_type matters)
- "I sent BSV to a BTC address" / "I sent ETH to a BTC address" — every
  exchange's customer-support FAQ has a section on this; B3Chain should
  not contribute to it.
