# Tutorial — Why the 21M cap matters and how it's enforced

## The problem in one sentence
Once a chain emits more than its declared supply, you cannot un-issue
the excess; this is the single most reputation-defining bug a fork can
ship.

## The theory

Bitcoin's supply formula is a geometric series:

\[ S = I \cdot \sum_{n=0}^{63} \lfloor (50 \cdot 10^8) / 2^n \rfloor \]

where `I` is the halving interval (`210000` blocks on mainnet) and the
sum is truncated at `n = 63` because the C++ expression `(50 * COIN) >> 64`
on a 64-bit type is **undefined behaviour**. The guard
`if (halvings >= 64) return 0;` is not optional; it changes the answer
on most compilers.

For B3Chain, all parameters are inherited unchanged. The cap evaluates
to `2099999997690000` satoshi exactly = `20999999.97690000 B3C`.

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-supply-cap.py
```

Expected output:

```
[C-1..C-4] Supply cap and halving schedule
========================================================================
  PASS  [C-2] geometric sum at mainnet interval (210000) equals 20999999.97690000
  PASS  [C-3] subsidy returns 0 at halving 64
  PASS  [C-4] CalculateNextWorkRequired retains the 4x retarget bounds
  Spawning regtest node and mining 600 blocks (4 halvings)...
  PASS  [C-1] subsidy at height 1 (halving 0) = 50.00000000 B3C
  PASS  [C-1] subsidy at height 151 (halving 1) = 25.00000000 B3C
  ...
AUDIT RESULT: PASS  [C-1..C-4]
```

## Exercise

Open `src/validation.cpp` and locate `GetBlockSubsidy()`. Remove the
`>= 64` guard, rebuild, re-run the audit. You should see C-3 fail
with a non-zero subsidy at high heights.

```cpp
// Before
if (halvings >= 64) return 0;
// After (introduces UB)
// (deleted)
```

Expected new output (compiler-dependent — gcc tends to wrap, clang
often optimises to `0` anyway):

```
  FAIL  [C-3] subsidy at halving 64 returned 50.00000000 B3C, expected 0
AUDIT RESULT: FAIL  [C-1..C-4]
```

This is exactly the kind of "looks like it works in your tests" bug
that has bitten other forks. The audit catches it.

## Further reading

- Bitcoin Core PR for the original guard:
  github.com/bitcoin/bitcoin/blob/master/src/validation.cpp
- Bitcoin Talk thread on the geometric-series cap (Satoshi 2010):
  bitcointalk.org/index.php?topic=583.0
- C++ standard on undefined right-shift (ISO/IEC 14882:2017 §8.7):
  open-std.org/jtc1/sc22/wg21/
