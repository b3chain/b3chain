Reproducible Builds
===================

This document describes how a release engineer assembles a B3Chain Core
release, and how a security-conscious user independently rebuilds those
artefacts from source and verifies them against the published signatures
and checksums.

Audience: anyone running B3Chain Core who wants more than the GitHub
Releases download UI offers — including auditors, operators of public
infrastructure (pools, explorers, exchanges), and security researchers.

For the release pipeline itself, see
[`.github/workflows/release.yml`](../.github/workflows/release.yml).

Contents
--------

1. [Overview — what we reproduce, what we don't](#overview)
2. [Docker reproducible build](#docker-reproducible-build)
3. [Guix reproducible build](#guix-reproducible-build)
4. [`SHA256SUMS` verification](#sha256sums-verification)
5. [Cosign / Sigstore verification](#cosign--sigstore-verification)
6. [PGP verification (when available)](#pgp-verification-when-available)
7. [SBOM consumption](#sbom-consumption)
8. [Continuous-build status](#continuous-build-status)
9. [Known caveats](#known-caveats)

Overview
--------

A release of B3Chain Core consists of:

| Asset | What it is |
|---|---|
| `b3chain-<version>-<host>.tar.gz` / `.zip` | Native binary archive for one OS/arch |
| `b3chain-<version>.cdx.json` | CycloneDX SBOM for the release |
| `*.sig`, `*.crt` | Sigstore/Cosign keyless signatures + certs for every blob |
| `ghcr.io/b3chain/{b3chaind,b3chain-cli,b3chain-python-miner,b3chain-verify-b3pow}` | Multi-arch container images, cosign-signed by digest |
| `SHA256SUMS` | SHA-256 of every release blob, one file per release |
| `SHA256SUMS.sig`, `SHA256SUMS.crt` | Cosign signature + cert over `SHA256SUMS` |
| `SHA256SUMS.asc` | Detached PGP signature over `SHA256SUMS` (only when a maintainer PGP key is configured) |

**What we reproduce.** Given the same git commit and the same
`SOURCE_DATE_EPOCH`, the Docker build path produces bit-identical
container image digests on Linux. The native-binary builds aim for the
same property under Guix (`contrib/guix/`); see the [Guix
section](#guix-reproducible-build) for that path.

**What we do not reproduce.** We do not, today, attempt bit-identical
reproducibility for:

- The macOS `.tar.gz` (the toolchain on `macos-14` runners is not
  pinned to a hash, and macOS code-signing — which we would need to ship
  signed binaries — requires an Apple Developer ID we do not have at
  launch).
- The Windows `.zip` built with MSVC 2022 on `windows-2022` runners
  (the MSVC redistributables and the SDK version pin floats with the
  runner image).

Both of those tracks gain reproducibility once the equivalent Guix
cross-build matrix lands; that work is tracked alongside Phase 2.3 of
the launch package.

Docker reproducible build
-------------------------

The top-level [`Dockerfile`](../Dockerfile) defines five build stages.
Stages 1–3 produce the C++ binaries and the slim runtime images; stages
4–5 produce the Python reference miner and the standalone verifier.

To produce a bit-identical image:

1. Check out the exact tag you want to verify:

    ```bash
    git fetch --tags
    git checkout v0.1.0
    ```

2. Capture the commit timestamp for `SOURCE_DATE_EPOCH`:

    ```bash
    export SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)
    ```

3. Build a single-arch image with `buildx`:

    ```bash
    docker buildx build \
      --platform linux/amd64 \
      --target b3chaind \
      --build-arg BUILD_TYPE=Release \
      --build-arg SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH}" \
      -t b3chaind:v0.1.0-local \
      .
    ```

4. Print the image digest and compare against the published one:

    ```bash
    docker buildx imagetools inspect b3chaind:v0.1.0-local --format '{{.Manifest.Digest}}'
    ```

   The expected digest is listed in the GitHub Release notes for the
   tag and is also signed in `SHA256SUMS`.

Repeat for the other four targets by changing `--target`. The same
`SOURCE_DATE_EPOCH` must be used for every stage.

For a multi-arch (`linux/amd64,linux/arm64`) build to GHCR — the exact
operation the release workflow performs — add `--platform
linux/amd64,linux/arm64 --push` and supply a registry path.

The release workflow stamps every image with three tags:

- `latest` (only on the default branch)
- `v<X.Y.Z>` (matching the git tag)
- `sha-<short-commit>`

Use the `sha-<short>` form when pinning to a specific build in
production.

Guix reproducible build
-----------------------

B3Chain inherits the Bitcoin Core Guix tooling under
[`contrib/guix/`](../contrib/guix/). The flow is the standard one
documented in [`contrib/guix/README.md`](../contrib/guix/README.md), with
two B3Chain-specific notes:

- The build manifest is at
  [`contrib/guix/manifest.scm`](../contrib/guix/manifest.scm). It is
  carried over from Bitcoin Core unchanged; B3PoW-Scratch consensus is
  pure C++ inside `src/`, so the dependency closure is unchanged.
- The B3PoW-Scratch consensus vector file
  [`src/test/data/b3pow_consensus_vectors.json`](../src/test/data/b3pow_consensus_vectors.json)
  is regenerated by `contrib/miner/b3miner-rtl/ref/gen_vectors.py` and
  must be in sync with `contrib/miner/b3miner-rtl/ref/vectors/`. The
  [`b3miner-rtl` CI workflow](../.github/workflows/b3miner-rtl.yml)
  enforces this; the Guix release flow assumes the check has already
  passed on the tagged commit.

For the actual Guix invocation:

```bash
cd /path/to/your/toplevel/build
git clone https://github.com/b3chain/b3chain.git
pushd ./b3chain
SIGNER='your-builder-id'
VERSION='0.1.0'
git fetch origin "v${VERSION}"
git checkout "v${VERSION}"
./contrib/guix/guix-build
./contrib/guix/guix-attest
popd
```

The `guix-attest` step produces a `noncodesigned.SHA256SUMS` and an
`.asc` signature using the local PGP key identified by `${SIGNER}`. See
[`doc/release-process.md`](./release-process.md) for the multi-builder
attestation flow inherited from Bitcoin Core.

`SHA256SUMS` verification
-------------------------

The release ships a single `SHA256SUMS` file listing every binary
tarball / zip, every SBOM, and every Sigstore signature + certificate.

```bash
# 1. Download the artefacts you intend to use + the SHA256SUMS file.
# 2. Put them in the same directory.
# 3. Verify:
sha256sum -c SHA256SUMS
```

A successful run prints `OK` next to each file. A mismatch prints
`FAILED`; do not run the binary in that case.

For partial verification (e.g. you only downloaded the Linux x86_64
binary), `sha256sum -c --ignore-missing SHA256SUMS` silently skips the
files you do not have.

Cosign / Sigstore verification
------------------------------

Every release blob and every container image is signed in [keyless
mode][cosign-keyless]: the signing identity is the GitHub Actions
workflow itself, not a long-lived key. Verifiers therefore check that:

- the signature is anchored to the Sigstore transparency log, **and**
- the signing certificate's subject identifies our release workflow,
  and the OIDC issuer is GitHub Actions.

Install cosign (≥ v2.5.0):

```bash
# Linux:
curl -sSL -o /usr/local/bin/cosign \
  https://github.com/sigstore/cosign/releases/download/v2.5.0/cosign-linux-amd64
chmod +x /usr/local/bin/cosign

# macOS:
brew install cosign
```

[cosign-keyless]: https://docs.sigstore.dev/cosign/signing/overview/

### Verifying a release blob

```bash
cosign verify-blob \
  --signature   b3chain-0.1.0-x86_64-linux-gnu.tar.gz.sig \
  --certificate b3chain-0.1.0-x86_64-linux-gnu.tar.gz.crt \
  --certificate-identity-regexp '^https://github.com/b3chain/b3chain/\.github/workflows/release\.yml@refs/tags/v.*$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  b3chain-0.1.0-x86_64-linux-gnu.tar.gz
```

The same form works for `*.cdx.json` (SBOM), `*.zip` (Windows release),
and `SHA256SUMS` itself.

### Verifying a container image

Verify the **digest**, not a floating tag:

```bash
# 1. Resolve the tag to a digest:
DIGEST=$(docker buildx imagetools inspect \
  ghcr.io/b3chain/b3chaind:v0.1.0 \
  --format '{{.Manifest.Digest}}')

# 2. Verify the signature on that digest:
cosign verify \
  --certificate-identity-regexp '^https://github.com/b3chain/b3chain/\.github/workflows/release\.yml@refs/tags/v.*$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "ghcr.io/b3chain/b3chaind@${DIGEST}"
```

Repeat for `b3chain-cli`, `b3chain-python-miner`, and
`b3chain-verify-b3pow`.

> **TODO(maintainer):** if the release-pipeline ref changes (for
> example, releases move from this repository to a fork or staging
> repo), update the `--certificate-identity-regexp` above and the
> `IMAGE_NAMESPACE` env var in `.github/workflows/release.yml`.

PGP verification (when available)
---------------------------------

When a maintainer PGP key is provisioned in the repository secrets
(`RELEASE_PGP_KEY`, optionally `RELEASE_PGP_PASSPHRASE`), the release
workflow additionally emits a detached PGP signature
`SHA256SUMS.asc`. Releases tagged before a maintainer key is configured
ship with only the cosign `SHA256SUMS.sig` / `SHA256SUMS.crt` pair.

To verify:

```bash
# 1. Import the maintainer key.  TODO(maintainer): replace the
#    fingerprint below with the production release key, and document
#    the key origin (keyserver, GitHub, etc.) in this section.
gpg --keyserver hkps://keys.openpgp.org \
    --recv-keys 0000000000000000000000000000000000000000

# 2. Verify the detached signature:
gpg --verify SHA256SUMS.asc SHA256SUMS
```

A successful run prints `Good signature from "<key user id>"`. A
warning about "no trusted signature" is expected on a fresh keyring;
verify the fingerprint matches the published one, then sign the key
locally if you want gpg to consider it trusted.

SBOM consumption
----------------

Every release includes a CycloneDX 1.5 JSON SBOM:

- `b3chain-<version>.cdx.json` is generated by
  [`anchore/sbom-action`][sbom-action] over the staged release blobs.

[sbom-action]: https://github.com/anchore/sbom-action

Typical consumers:

```bash
# Inspect the dependency graph with syft:
syft b3chain-0.1.0.cdx.json

# Match the dependency graph against known-vulnerable versions with grype:
grype sbom:b3chain-0.1.0.cdx.json

# Or upload to a long-running tracker (Dependency-Track, Snyk SBOM, etc.).
```

The container images additionally embed a per-image SBOM via buildx's
`sbom: true` flag; `cosign download sbom <image-digest>` retrieves it.

Continuous-build status
-----------------------

The latest tag's release pipeline runs are at
<https://github.com/b3chain/b3chain/actions/workflows/release.yml>.

A green run guarantees:

- every native binary built on its target runner without warnings,
- the container images pushed to GHCR with both `linux/amd64` and
  `linux/arm64` manifests,
- every blob and every image was successfully signed with cosign,
- `SHA256SUMS` was emitted, signed, and uploaded.

It does **not** guarantee that the binaries pass functional tests —
those run in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
and the per-release [`.github/workflows/b3miner-rtl.yml`][rtl-ci]
audit-mode gate. Treat the release pipeline's success as a packaging
check, not a correctness check.

[rtl-ci]: ../.github/workflows/b3miner-rtl.yml

Known caveats
-------------

- **macOS Gatekeeper.** The macOS release is signed with cosign but
  not codesigned with an Apple Developer ID. macOS will warn on first
  launch ("Apple cannot check this binary for malicious software").
  Right-click → Open, or `xattr -d com.apple.quarantine` to dismiss
  the warning once you have cosign-verified the binary. We will issue
  Apple-signed builds once a Developer ID is provisioned.
- **Windows SmartScreen.** Likewise, the Windows zip is not
  Authenticode-signed at launch; SmartScreen will flag it as
  "unrecognised publisher" until enough downloads accrue reputation,
  or until an Authenticode certificate is provisioned.
- **`latest` Docker tag.** `latest` floats with the default branch.
  Production deployments should pin to `sha-<commit>` or `v<X.Y.Z>`.
- **Floating base images.** `Dockerfile` references `debian:12-slim`
  and `python:3.12-slim-bookworm`. The release workflow currently
  resolves those at build time; a fully reproducible image requires
  pinning by digest (see the `ARG DEBIAN_IMAGE` / `ARG PYTHON_IMAGE`
  TODOs in `Dockerfile`).
- **Reproducibility scope.** Linux Docker images are bit-identical
  per `(commit, SOURCE_DATE_EPOCH, BUILDKIT_VERSION)`. Native macOS
  and Windows tarballs are not yet bit-reproducible; see
  [Overview](#overview).
- **Verifier identity.** The cosign `--certificate-identity-regexp`
  values above assume releases are tagged on
  `github.com/b3chain/b3chain`. If you fork the repo and produce your
  own builds, the certificate identity changes; verifiers must update
  the regexp accordingly.

Related documents
-----------------

- [`doc/release-process.md`](./release-process.md) — release-engineering
  checklist inherited from Bitcoin Core.
- [`contrib/guix/README.md`](../contrib/guix/README.md) — Guix
  reproducible-build tooling.
- [`contrib/verify-binaries/README.md`](../contrib/verify-binaries/README.md)
  — end-user verifier for the historical Bitcoin Core `SHA256SUMS`
  flow, kept for compatibility with users following that recipe.
- [`Dockerfile`](../Dockerfile) and
  [`docker-compose.yml`](../docker-compose.yml) — multi-stage image
  definitions and the local regtest stack.
- [`.github/workflows/release.yml`](../.github/workflows/release.yml)
  — the pipeline that produces every signed asset listed above.
