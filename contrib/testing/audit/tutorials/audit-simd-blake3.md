# Tutorial — Why SIMD differential testing is non-negotiable for new hash code

## The problem in one sentence
SIMD code paths and portable C code paths for the same algorithm must
produce **byte-identical** output, and a single off-by-one in lane
loading silently corrupts the chain forever.

## The theory

The official BLAKE3 C library has multiple compression-loop
implementations:

- Portable C (always built; reference behaviour)
- SSE2 (Intel/AMD baseline x86_64, 4 lanes)
- SSE4.1 (4 lanes, faster)
- AVX2 (8 lanes)
- AVX-512 (16 lanes)
- NEON (ARM)

A runtime dispatcher picks the best implementation for the host CPU.
If any of these has a bug — a lane swap, a misaligned load, a missing
final round — *some* nodes will produce different hashes, and the
network will fork along CPU type. This has happened in real chains
(notably an Ethereum SECP256K1 SIMD bug in 2017 that nearly forked the
network).

## Hands-on demo

```bash
python3 contrib/testing/audit/audit-simd-blake3.py
```

The script:

1. Picks a list of edge-case input sizes: 0, 1, 31, 32, 33, 63, 64, 65,
   80 (block-header), 127, 128, 129, 255, 256, 257, 1023, 1024, 1025,
   4096, 8192, 65535, 65536, 100000.
2. Generates 1000 additional random-sized inputs from a fixed seed
   (so the run is reproducible).
3. Hashes every input with BLAKE3 in:
   - default mode (whatever SIMD the dispatcher picks)
   - `BLAKE3_NO_SIMD=1` portable mode
4. Compares byte-for-byte. Any mismatch is an immediate FAIL.

## Exercise

This one needs you to break the BLAKE3 C library, which lives under
`src/crypto/blake3/c/`. As a non-destructive demonstration, you can
*temporarily* set the env var that disables SIMD and confirm the
audit still passes (because it's comparing portable to portable):

```bash
BLAKE3_NO_SIMD=1 python3 contrib/testing/audit/audit-simd-blake3.py
# Should still PASS — both sides are now portable.
```

To actually demonstrate a SIMD bug detection, the more realistic
exercise is: build with `-DBLAKE3_DEBUG_FORCE_SIMD_OUTPUT_MISMATCH`
(if the library is patched to support it) and observe the differential
fail. In production, this exercise is what catches real upstream
regressions when we sync the BLAKE3 library to a newer upstream
release.

## Why we re-test on every release

The BLAKE3 C library is vendored at a specific commit. Every time we
bump that commit, we re-run this audit *before* tagging a release.
A SIMD regression upstream (rare but real — see CVE-2023-28447 for a
historical example) must be caught by us, not by the network.

## Further reading

- BLAKE3 specification: github.com/BLAKE3-team/BLAKE3-specs
- BLAKE3 C library: github.com/BLAKE3-team/BLAKE3/tree/master/c
- CVE-2023-28447 — historical AVX-512 buffer-handling bug, fixed in
  BLAKE3 v1.4.1.
- Ethereum 2017 SECP256K1 fork-near-miss writeup:
  ethereum.org/en/history/
