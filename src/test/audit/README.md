# C++ audit tests

C++ counterpart of the Phase 11 self-audit scripts in
`contrib/testing/audit/`. These tests run inside the existing CTest suite so
every CI build verifies the consensus invariants.

| File | Audit IDs covered |
|------|-------------------|
| `consensus_invariants_tests.cpp` | C-1, C-2, C-3 (subsidy schedule, total cap, halving-64 zero), H-1 (block ID vs PoW hash), N-1 (mainnet/regtest magic isn't Bitcoin's, mainnet DNS seeds aren't bitcoin) |

To run only the audit tests:

```bash
cd build
ctest -R consensus_invariants_tests --output-on-failure
```

The Python audit scripts in `contrib/testing/audit/` cover the same
invariants but additionally exercise live regtest behaviour (RPC, P2P,
mining), things this in-process suite cannot easily test.
