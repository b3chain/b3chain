# Tutorial — Why BIP44 coin_type matters more than just "a number"

## The problem in one sentence
Two wallets that derive from the same BIP39 seed but at different
`coin_type`s produce **completely different private keys**, so getting
this number right (and proving it) is the boundary between a B3Chain
wallet and an accidentally-Bitcoin wallet.

## The theory

BIP44 derivation paths look like:

```
m / 44' / coin_type' / account' / change / address_index
```

Bitcoin's `coin_type` is `0`. Litecoin's is `2`. Ethereum's is `60`.
B3Chain proposes `9333` (pending SLIP-0044 registration; see
[`doc/b3chain-bip44.md`](https://github.com/b3chain/b3chain/blob/b3chain-main/doc/b3chain-bip44.md)).

If two chains accidentally use the same `coin_type`:

- The same seed in both wallets derives the same private key.
- A signed transaction's spending signature is valid for the same
  UTXO on either chain (if it exists).
- The likelier failure mode: users treat one chain's xpub as the
  other's in external tooling, lose track of funds.

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-hd-coin-type.py
```

The script:

1. Greps `src/wallet/walletutil.cpp` for the literal `9333h`,
   verifies it appears once and is gated by `!IsTestChain()`.
2. Spawns a regtest node, creates a fresh descriptor wallet, calls
   `getaddressinfo` on a freshly-derived address, asserts the
   `hdkeypath` contains `9333'` (mainnet) or `1'` (testnet/regtest).
3. Independently re-derives the address with the Python `bip_utils`
   library at `m/84'/9333'/0'/0/0`, verifies the bytes match.
4. Re-derives at `m/84'/0'/0'/0/0` (Bitcoin's coin_type), verifies the
   address is **different**.

## Exercise

In `src/wallet/walletutil.cpp`, edit the `coin_type` literal back to
`0h`:

```cpp
// Before
const std::string coin_type = IsTestChain() ? "1h" : "9333h";
// After (BAD - silently makes B3Chain mainnet wallets identical to Bitcoin)
const std::string coin_type = IsTestChain() ? "1h" : "0h";
```

Rebuild, re-run the audit. Expected output:

```
  FAIL  [W-2] descriptor uses coin_type 0 (Bitcoin), expected 9333
  FAIL  [W-2] cross-derivation: B3Chain address matches Bitcoin coin_type 0 derivation
AUDIT RESULT: FAIL  [W-2]
```

The second failure is the important one — even if you missed the
literal, the cross-derivation test catches the actual semantic bug.

## What if SLIP-0044 assigns a different number?

`9333` is a proposal, not an assignment. The migration plan is in
`doc/b3chain-bip44.md`:

1. Submit a PR to the SLIP-0044 repo requesting `9333` for B3Chain.
2. If accepted as-is: no migration.
3. If a different number `X` is assigned: ship a wallet migration
   that sweeps from `9333`-derived addresses to `X`-derived addresses,
   continues accepting `9333` xpubs in `importdescriptors` for
   backward compatibility.
4. If SLIP-0044 takes >12 months: publicly commit to `9333`.

Either way, this audit pins the choice and prevents silent drift.

## Further reading

- BIP-44 multi-account hierarchy:
  github.com/bitcoin/bips/blob/master/bip-0044.mediawiki
- SLIP-0044 (Trezor / coin_type registry):
  github.com/satoshilabs/slips/blob/master/slip-0044.md
- BIP-32 hierarchical deterministic wallets:
  github.com/bitcoin/bips/blob/master/bip-0032.mediawiki
- BIP-39 mnemonic seed phrases:
  github.com/bitcoin/bips/blob/master/bip-0039.mediawiki
