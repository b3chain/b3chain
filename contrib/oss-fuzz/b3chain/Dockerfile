# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# OSS-Fuzz builder image for b3chain.  Mirrors the upstream Bitcoin
# Core OSS-Fuzz project layout (`google/oss-fuzz/projects/bitcoin-core/`).
# When this directory is copied under `google/oss-fuzz/projects/b3chain/`
# in an upstream PR, the OSS-Fuzz infrastructure will treat it as a
# first-class fuzzed project.

FROM gcr.io/oss-fuzz-base/base-builder

# Build dependencies match doc/build-unix.md and depends/README.md.
RUN apt-get update && apt-get install -y \
    build-essential curl g++-multilib make \
    patch pkgconf python3 wget zip cmake ninja-build

# Pin to the b3chain-main branch.  The OSS-Fuzz build cluster does
# shallow clones daily; no need to vendor history.
RUN git clone --depth=1 -b b3chain-main \
    https://github.com/b3chain/b3chain.git b3chain

# Fuzz-corpora repo placeholder.  Initially empty -- the b3chain-qa
# repo will be created when the first fuzz target is added.
# RUN git clone --depth=1 https://github.com/b3chain/qa-assets \
#         b3chain/assets && \
#     rm -rf b3chain/assets/.git

# Use the b3chain-vendored libsecp256k1 (in src/secp256k1/).  No need
# to clone a separate copy, unlike bitcoin-core's Dockerfile.

WORKDIR b3chain
COPY build.sh $SRC/
