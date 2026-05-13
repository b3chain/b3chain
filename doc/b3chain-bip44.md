# B3Chain BIP44 Coin Type

| Field            | Value |
|------------------|-------|
| **coin_type**    | **9333** (mainnet)    |
| **coin_type**    | 1 (testnet, testnet4, signet, regtest — per BIP44 standard) |
| **path prefix (mainnet)**  | `m/44'/9333'/0'/0/0`  (P2PKH legacy) |
|                  | `m/49'/9333'/0'/0/0`  (P2SH-segwit) |
|                  | `m/84'/9333'/0'/0/0`  (Bech32 / native segwit) |
|                  | `m/86'/9333'/0'/0/0`  (Bech32m / Taproot) |
| **status**       | Proposed — pending SLIP-0044 registration |
| **first version** | B3Chain Core master (Phase 11) |

## Why 9333

B3Chain needs its own BIP44 `coin_type` so that hardware wallets, multi-coin
wallets, and seed-restore tools derive a different keyspace for B3Chain than
they would for Bitcoin. Using Bitcoin's `coin_type 0` would make B3Chain
private keys and Bitcoin private keys derive to the same xpub on the same
seed, which is dangerous (one signed transaction can be replayed across
chains in some recovery scenarios).

We picked **9333** with the following reasoning:

| Criterion | How 9333 satisfies it |
|-----------|------------------------|
| Not currently assigned by SLIP-0044 | The block `9216..16383` is unallocated as of the SLIP-0044 master list at the time of writing. |
| Mnemonic | `9` is the first decimal digit not occupied by Bitcoin (`0`); `333` is symbolic for "B3Chain" (the three "3"s). |
| Outside common chain ranges | Avoids the bands used by Ethereum (60), Litecoin (2), Bitcoin Cash (145), Zcash (133), DOGE (3) etc. |
| Easy to remember | All-decimal value, four characters. |
| Hex form | `0x2475` — no special meaning, but unique. |

## Rationale for the proposed value (vs reusing Bitcoin's coin_type 0)

Bitcoin Core's default descriptor wallet historically used `coin_type 0` on
mainnet. After the BLAKE3 PoW rebrand, B3Chain mainnet was the same. This
caused two practical problems:

1. **Seed reuse risk.** A user importing the same BIP39 mnemonic into a
   Bitcoin wallet and a B3Chain wallet would generate the same private keys
   on both. A naive transaction tool could broadcast a properly-encoded
   B3Chain transaction to Bitcoin (the consensus rules differ enough that
   the chain would reject it, but the *spending* signature would be valid
   for the same UTXO if it existed on Bitcoin). The likelier failure mode
   is that users accidentally treat B3Chain xpubs as Bitcoin xpubs in
   external tooling.
2. **Hardware wallet integration.** SLIP-0044 is the discovery key for
   wallets like Trezor, Ledger, and Coldcard. Using `0` makes B3Chain
   indistinguishable from Bitcoin to those wallets, which is undesirable.

## SLIP-0044 registration plan

`9333` is **proposed** — it has not yet been assigned by the SLIP-0044
maintainers. The following are the next steps and rollback plan:

1. **Submit a PR** to the [SLIP-0044 repository](https://github.com/satoshilabs/slips/blob/master/slip-0044.md)
   requesting `9333` for B3Chain. (Filed as a follow-up after Phase 11.)
2. **If 9333 is accepted as-is**, no migration is needed.
3. **If SLIP-0044 assigns a different number** (say `X`), B3Chain Core will:
   - Add a wallet migration that re-derives addresses at `m/44'/X'/0'/...`,
     funds them by sweeping from the `9333`-derived addresses, and marks
     the wallet as upgraded.
   - Continue accepting `9333`-derived xpubs in `importdescriptors` for
     backward compatibility.
4. **If SLIP-0044 takes more than 12 months to respond**, we will publicly
   commit to `9333` and document the discrepancy.

## How the choice is implemented

The change lives in
[`src/wallet/walletutil.cpp::GenerateWalletDescriptor`](../src/wallet/walletutil.cpp).
On any `IsTestChain()` chain (testnet, testnet4, signet, regtest) the
descriptor uses `/1h` (per BIP44 standard). On every other chain (mainnet
today, future post-fork chains too) it uses `/9333h`.

## How to verify

The audit script
[`contrib/testing/audit/audit-hd-coin-type.py`](../contrib/testing/audit/audit-hd-coin-type.py)
checks:

1. The literal string `9333h` appears in `walletutil.cpp` exactly once and
   is gated by `!IsTestChain()`.
2. Building B3Chain in mainnet mode and creating a fresh descriptor wallet
   produces descriptors containing `/9333h/`.
3. Independently re-deriving the address with a 3rd-party BIP32 library
   (Python `pycoin` or `bip_utils`) at `m/84'/9333'/0'/0/0` matches the
   address the wallet returned.
4. Re-deriving at `m/84'/0'/0'/0/0` (Bitcoin's coin_type) produces a
   *different* address — proves the namespaces are isolated.

## Out of scope

- **Wallet UI changes.** No changes to the `b3chain-qt` GUI are needed; the
  derivation path is hidden from end-users behind `getaddressinfo`.
- **PSBT format.** Unchanged — BIP174 stores the full path, not a coin_type.
- **Existing wallets created before this change.** They will continue to
  derive at `0h` until the user deliberately creates a new descriptor with
  `createwalletdescriptor` or migrates the wallet. The wallet code never
  rewrites stored descriptors.
