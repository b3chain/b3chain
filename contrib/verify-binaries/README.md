### Verify Binaries

> **B3Chain note.** This script targets the historical Bitcoin Core
> `SHA256SUMS` + multi-builder PGP flow, kept here for users following that
> recipe. **The canonical B3Chain release-verification flow is documented
> at [`doc/reproducible-builds.md`](../../doc/reproducible-builds.md)**,
> which covers cosign keyless verification of both release blobs and
> container images, `sha256sum -c SHA256SUMS`, the optional `SHA256SUMS.asc`
> PGP path, and CycloneDX SBOM consumption. The two flows are
> complementary — cosign + `SHA256SUMS` are emitted on every release; a
> Guix-style multi-builder PGP attestation set is only emitted once enough
> independent builders sign a given tag.

#### Preparation

As of Bitcoin Core v22.0, releases are signed by a number of public keys on the basis
of the [guix.sigs repository](https://github.com/bitcoin-core/guix.sigs/). When
verifying binary downloads, you (the end user) decide which of these public keys you
trust and then use that trust model to evaluate the signature on a file that contains
hashes of the release binaries. The downloaded binaries are then hashed and compared to
the signed checksum file.

First, you have to figure out which public keys to recognize. Browse the [list of frequent
builder-keys](https://github.com/bitcoin-core/guix.sigs/tree/main/builder-keys) and
decide which of these keys you would like to trust. For each key you want to trust, you
must obtain that key for your local GPG installation.

You can obtain these keys by
  - through a browser using a key server (e.g. keyserver.ubuntu.com),
  - manually using the `gpg --keyserver <url> --recv-keys <key>` command, or
  - you can run the packaged `verify.py --import-keys ...` script to
    have it automatically retrieve unrecognized keys.

#### Usage

This script attempts to download the checksum file (`SHA256SUMS`) and corresponding
signature file `SHA256SUMS.asc` from https://bitcoincore.org and https://bitcoin.org.

It first checks if the checksum file is valid based upon a plurality of signatures, and
then downloads the release files specified in the checksum file, and checks if the
hashes of the release files are as expected.

If we encounter pubkeys in the signature file that we do not recognize, the script
can prompt the user as to whether they'd like to download the pubkeys. To enable
this behavior, use the `--import-keys` flag.

The script returns 0 if everything passes the checks. It returns 1 if either the
signature check or the hash check doesn't pass. An exit code of >2 indicates an error.

See the `Config` object for various options.

#### Examples

Validate releases with default settings:
```sh
./contrib/verify-binaries/verify.py pub 22.0
./contrib/verify-binaries/verify.py pub 22.0-rc3
```

Get JSON output and don't prompt for user input (no auto key import):

```sh
./contrib/verify-binaries/verify.py --json pub 22.0-x86
./contrib/verify-binaries/verify.py --json pub 23.0-rc5-linux-gnu
```

Rely only on local GPG state and manually specified keys, while requiring a
threshold of at least 10 trusted signatures:
```sh
./contrib/verify-binaries/verify.py \
    --trusted-keys 74E2DEF5D77260B98BC19438099BAD163C70FBFA,9D3CC86A72F8494342EA5FD10A41BDC3F4FAFF1C \
    --min-good-sigs 10 pub 22.0-linux
```

If you only want to download the binaries for a certain architecture and/or platform, add the corresponding suffix, e.g.:

```sh
./contrib/verify-binaries/verify.py pub 25.2-x86_64-linux
./contrib/verify-binaries/verify.py pub 24.1-rc1-darwin
./contrib/verify-binaries/verify.py pub 27.0-win64-setup.exe
```

If you do not want to keep the downloaded binaries, specify the cleanup option.

```sh
./contrib/verify-binaries/verify.py pub --cleanup 22.0
```

Use the bin subcommand to verify all files listed in a local checksum file

```sh
./contrib/verify-binaries/verify.py bin SHA256SUMS
```

Verify only a subset of the files listed in a local checksum file

```sh
./contrib/verify-binaries/verify.py bin ~/Downloads/SHA256SUMS \
    ~/Downloads/bitcoin-24.0.1-x86_64-linux-gnu.tar.gz \
    ~/Downloads/bitcoin-24.0.1-arm-linux-gnueabihf.tar.gz
```

#### B3Chain release verification (quick reference)

The full flow, including container-image verification and SBOM
consumption, is in [`doc/reproducible-builds.md`](../../doc/reproducible-builds.md).
Quick recipe for a tagged B3Chain release:

```sh
# 1. From a GitHub Release page for tag v<X.Y.Z>, download the binary
#    archive(s) you want, the matching .sig + .crt, plus SHA256SUMS,
#    SHA256SUMS.sig, and SHA256SUMS.crt.

# 2. Cosign-verify SHA256SUMS itself:
cosign verify-blob \
  --signature   SHA256SUMS.sig \
  --certificate SHA256SUMS.crt \
  --certificate-identity-regexp '^https://github.com/b3chain/b3chain/\.github/workflows/release\.yml@refs/tags/v.*$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  SHA256SUMS

# 3. Verify every downloaded binary against SHA256SUMS:
sha256sum -c --ignore-missing SHA256SUMS

# 4. (Optional) Also cosign-verify each individual blob to anchor it
#    independently of SHA256SUMS:
cosign verify-blob \
  --signature   b3chain-<version>-<host>.tar.gz.sig \
  --certificate b3chain-<version>-<host>.tar.gz.crt \
  --certificate-identity-regexp '^https://github.com/b3chain/b3chain/\.github/workflows/release\.yml@refs/tags/v.*$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  b3chain-<version>-<host>.tar.gz

# 5. (Optional) When a maintainer PGP signature is shipped, also verify:
gpg --verify SHA256SUMS.asc SHA256SUMS
```

See [`doc/reproducible-builds.md`](../../doc/reproducible-builds.md) for
the container-image (`cosign verify ghcr.io/b3chain/...`) and SBOM
(`syft` / `grype`) verification paths.
