# `contrib/oss-fuzz/b3chain/` — OSS-Fuzz onboarding scaffold

This directory is a **build scaffold**, not a live OSS-Fuzz project.
It mirrors the upstream Bitcoin Core layout at
[`google/oss-fuzz/projects/bitcoin-core/`](https://github.com/google/oss-fuzz/tree/master/projects/bitcoin-core)
so that enabling continuous fuzzing for b3chain is reduced to a
copy-paste PR against
[`google/oss-fuzz`](https://github.com/google/oss-fuzz).

It is the in-tree half of SECURITY-ROADMAP §1 ("formal OSS-Fuzz
onboarding").  The upstream PR is the other half and is tracked
separately.

## Files

| File | Purpose |
|---|---|
| [`project.yaml`](project.yaml) | OSS-Fuzz project metadata (language, sanitizers, contacts). |
| [`Dockerfile`](Dockerfile) | Builder image based on `gcr.io/oss-fuzz-base/base-builder`. Clones b3chain inside the container; expects `build.sh` to be copied alongside. |
| [`build.sh`](build.sh) | Invoked by OSS-Fuzz inside the container. Builds the `depends/` toolchain, configures CMake with `-DBUILD_FOR_FUZZING=ON`, builds the fuzz binary, and writes one per-target binary to `$OUT/`. |
| [`README.md`](README.md) | This file. |

## To enable OSS-Fuzz for b3chain

1. **Fork** [`google/oss-fuzz`](https://github.com/google/oss-fuzz).
2. **Create** `projects/b3chain/` in the fork.
3. **Copy** every file from `contrib/oss-fuzz/b3chain/` (this directory)
   into `projects/b3chain/`.
4. **Verify locally** with the official OSS-Fuzz harness:

   ```sh
   git clone https://github.com/google/oss-fuzz
   cd oss-fuzz
   cp -r /path/to/b3chain/contrib/oss-fuzz/b3chain projects/b3chain
   python3 infra/helper.py build_image    b3chain
   python3 infra/helper.py build_fuzzers  --sanitizer address b3chain
   python3 infra/helper.py check_build    b3chain
   ```

   `check_build` must pass before opening the PR.
5. **Open the PR** against `google/oss-fuzz:master` titled
   `"projects/b3chain: add b3chain"` and CC the b3chain team via the
   `auto_ccs:` list in `project.yaml`.
6. Once merged, ClusterFuzz starts running the b3chain fuzz suite
   nightly; the resulting findings appear under
   `https://oss-fuzz.com/` and at the contact email.

## Differences from upstream Bitcoin Core's scaffold

The script and Dockerfile diverge from `bitcoin-core/` in three small
ways:

1. **Repo URL**: clones `https://github.com/b3chain/b3chain.git`
   tracking the `b3chain-main` branch (Bitcoin Core's default branch
   is `master`).
2. **Vendored secp256k1**: bitcoin-core clones a separate
   `bitcoin-core/secp256k1` repo.  b3chain ships its own copy under
   `src/secp256k1/` (as a sub-repo), so the separate `git clone` is
   omitted.
3. **No `bitcoin-core/qa-assets`**: the seed-corpus repo for b3chain
   doesn't exist yet.  The corpus / dictionary copy loops are kept as
   no-ops so the integration path is identical once we create a
   `b3chain/qa-assets`.

Everything else (the `depends/` build, the magic-string trick for
producing one binary per fuzz target, the sanitizers, the fuzzing
engines) is intentionally kept identical so future syncs with the
upstream layout are mechanical.

## Status

- `project.yaml`, `Dockerfile`, `build.sh` — drafted, **not yet
  submitted upstream**.
- ClusterFuzz integration — pending the PR above.
- The first b3chain-specific fuzz harness (B3PoW-Scratch verifier)
  lands in a separate commit under `src/test/fuzz/` and is exercised
  via the existing Bitcoin Core fuzz framework; nothing in this
  directory needs to change when new harnesses are added.

See also
[`doc/SECURITY-ROADMAP.md`](../../../doc/SECURITY-ROADMAP.md) item 1.
