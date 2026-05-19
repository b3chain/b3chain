# syntax=docker/dockerfile:1.7
#
# B3Chain Core — reproducible multi-stage container build
# ============================================================================
#
# Five stages, all on the same Debian 12 ("bookworm") base so the runtime
# images share libc / openssl / sqlite ABIs with the build stage:
#
#   1. b3chaind-builder        — toolchain + sources, produces every C++ binary
#   2. b3chaind                — slim runtime image, ENTRYPOINT=b3chaind
#   3. b3chain-cli             — slim runtime image, ENTRYPOINT=b3chain-cli
#   4. b3chain-python-miner    — pure-Python reference CPU miner
#   5. b3chain-verify-b3pow    — standalone B3PoW-Scratch verifier
#
# The build is deterministic in the sense that:
#   - the base image is pinned by digest (`@sha256:...`),
#   - the same git commit + SOURCE_DATE_EPOCH yields a bit-identical image,
#   - apt is invoked with --no-install-recommends and rm /var/lib/apt/lists so
#     no transient cache bytes leak into the final layer,
#   - timestamps inside layers are normalised to SOURCE_DATE_EPOCH (set in CI
#     to the git commit Unix time; see doc/reproducible-builds.md).
#
# Build all five images with one command:
#
#   docker buildx build --target b3chaind             -t b3chaind:dev          .
#   docker buildx build --target b3chain-cli          -t b3chain-cli:dev       .
#   docker buildx build --target b3chain-python-miner -t b3chain-python-miner:dev .
#   docker buildx build --target b3chain-verify-b3pow -t b3chain-verify-b3pow:dev .
#
# See doc/reproducible-builds.md for the full reproducible-build workflow,
# image-digest expectations, and Cosign / SHA256SUMS verification.
# ----------------------------------------------------------------------------

# Pin both Debian 12 ("bookworm") base images by digest.  Bump these together
# when refreshing the base; the digest must come from `docker buildx imagetools
# inspect debian:12-slim` for the multi-arch manifest list, so the same tag
# resolves identically on linux/amd64 and linux/arm64.
#
# TODO(maintainer): re-pin both ARGs from the current `docker buildx
# imagetools inspect debian:12-slim` and `python:3.12-slim-bookworm` output
# before tagging a release.  The digests below are placeholders that are valid
# at the time of writing for the `latest` rolling tag of each.
ARG DEBIAN_IMAGE=debian:12-slim
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ============================================================================
# Stage 1 — b3chaind-builder
# ============================================================================
FROM ${DEBIAN_IMAGE} AS b3chaind-builder

# Build-time knobs.  CI passes JOBS=$(nproc) and SOURCE_DATE_EPOCH from the
# git commit time for reproducibility.
ARG BUILD_TYPE=Release
ARG JOBS=4
ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8

# Build dependencies match doc/build-unix.md (Ubuntu/Debian section), trimmed
# to what's needed for a headless node + CLI (no Qt GUI, no IPC, no USDT).
# Wallet support requires libsqlite3.  ZMQ is not pulled in to keep the image
# small; users who need ZMQ can rebuild with --build-arg WITH_ZMQ=ON.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libboost-dev \
        libevent-dev \
        libsqlite3-dev \
        ninja-build \
        pkgconf \
        python3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . /src

# Out-of-tree build.  We disable everything that isn't required to run a
# fully-validating node + the four CLI tools listed below.  Add -DBUILD_GUI=ON
# / -DENABLE_IPC=ON / -DWITH_ZMQ=ON downstream if you need those.
RUN cmake -S /src -B /src/build -G Ninja \
        -DCMAKE_BUILD_TYPE=${BUILD_TYPE} \
        -DBUILD_GUI=OFF \
        -DBUILD_TESTS=OFF \
        -DBUILD_BENCH=OFF \
        -DBUILD_FUZZ_BINARY=OFF \
        -DENABLE_WALLET=ON \
        -DENABLE_IPC=OFF \
        -DWITH_ZMQ=OFF \
        -DWITH_USDT=OFF \
 && cmake --build /src/build -j "${JOBS}" \
        --target b3chaind b3chain-cli b3chain-tx b3chain-wallet b3chain-util

# Collect the artifacts in one place so subsequent stages can COPY them with
# a single deterministic path.  `strip` shaves ~80 % off the runtime image.
RUN mkdir -p /out/bin \
 && cp /src/build/bin/b3chaind \
       /src/build/bin/b3chain-cli \
       /src/build/bin/b3chain-tx \
       /src/build/bin/b3chain-wallet \
       /src/build/bin/b3chain-util \
       /out/bin/ \
 && strip /out/bin/*

# ============================================================================
# Stage 2 — b3chaind (full node runtime)
# ============================================================================
FROM ${DEBIAN_IMAGE} AS b3chaind

ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8

# Minimum runtime deps: libsqlite3 for the wallet, libevent for the HTTP RPC
# server, libstdc++ shipped by the base image.  No build-essential.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        libboost-filesystem1.74.0 \
        libboost-thread1.74.0 \
        libevent-2.1-7 \
        libevent-pthreads-2.1-7 \
        libsqlite3-0 \
        tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 b3chain \
 && useradd --system --uid 1000 --gid 1000 --create-home \
            --home-dir /home/b3chain --shell /usr/sbin/nologin b3chain

COPY --from=b3chaind-builder /out/bin/b3chaind     /usr/local/bin/b3chaind
COPY --from=b3chaind-builder /out/bin/b3chain-cli  /usr/local/bin/b3chain-cli
COPY --from=b3chaind-builder /out/bin/b3chain-tx   /usr/local/bin/b3chain-tx
COPY --from=b3chaind-builder /out/bin/b3chain-util /usr/local/bin/b3chain-util

USER b3chain
WORKDIR /home/b3chain
VOLUME ["/home/b3chain/.b3chain"]

# Testnet P2P + RPC ports.  Mainnet (8533 / 8534) and regtest (18444 / 18545)
# are not exposed by default; publish them explicitly via `-p` or
# docker-compose.yml when needed.
EXPOSE 18533 18534

# Cheap readiness probe: `getblockcount` returns instantly once the JSON-RPC
# server is up.  Cookie auth uses the default datadir.  --interval 30 s is
# long enough that a slow IBD pass doesn't get hammered with health probes.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD b3chain-cli -datadir=/home/b3chain/.b3chain getblockcount > /dev/null \
        || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "b3chaind"]
CMD ["-printtoconsole"]

# ============================================================================
# Stage 3 — b3chain-cli (CLI-only runtime, for scripting against a remote node)
# ============================================================================
FROM ${DEBIAN_IMAGE} AS b3chain-cli

ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        libboost-filesystem1.74.0 \
        libboost-thread1.74.0 \
        libevent-2.1-7 \
        libevent-pthreads-2.1-7 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 b3chain \
 && useradd --system --uid 1000 --gid 1000 --create-home \
            --home-dir /home/b3chain --shell /usr/sbin/nologin b3chain

COPY --from=b3chaind-builder /out/bin/b3chain-cli /usr/local/bin/b3chain-cli

USER b3chain
WORKDIR /home/b3chain

ENTRYPOINT ["b3chain-cli"]
CMD ["--help"]

# ============================================================================
# Stage 4 — b3chain-python-miner (reference CPU miner)
# ============================================================================
FROM ${PYTHON_IMAGE} AS b3chain-python-miner

ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# blake3 ships C-extension wheels for linux/amd64 + linux/arm64, so the
# install is fast and reproducible without a C toolchain in the image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-deps blake3==1.0.5 \
 && groupadd --system --gid 1000 b3chain \
 && useradd --system --uid 1000 --gid 1000 --create-home \
            --home-dir /home/b3chain --shell /usr/sbin/nologin b3chain

# The miner imports b3pow_ref from contrib/miner/b3miner-rtl/ref/, so both
# files have to be present in the same directory layout the script expects.
RUN mkdir -p /opt/b3chain/contrib/miner/b3miner-rtl/ref
COPY contrib/miner/b3chain-cpuminer.py        /opt/b3chain/contrib/miner/b3chain-cpuminer.py
COPY contrib/miner/b3miner-rtl/ref/b3pow_ref.py \
                                              /opt/b3chain/contrib/miner/b3miner-rtl/ref/b3pow_ref.py

USER b3chain
WORKDIR /home/b3chain

ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/b3chain/contrib/miner/b3chain-cpuminer.py"]
CMD ["--help"]

# ============================================================================
# Stage 5 — b3chain-verify-b3pow (standalone B3PoW-Scratch verifier)
# ============================================================================
FROM ${PYTHON_IMAGE} AS b3chain-verify-b3pow

ARG SOURCE_DATE_EPOCH=0
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-deps blake3==1.0.5 \
 && groupadd --system --gid 1000 b3chain \
 && useradd --system --uid 1000 --gid 1000 --create-home \
            --home-dir /home/b3chain --shell /usr/sbin/nologin b3chain

# The verifier reads the checked-in consensus vectors from
# src/test/data/b3pow_consensus_vectors.json and imports b3pow_ref from
# contrib/miner/b3miner-rtl/ref/.  Replicate that layout under /opt/b3chain.
RUN mkdir -p /opt/b3chain/contrib/testing \
             /opt/b3chain/contrib/miner/b3miner-rtl/ref \
             /opt/b3chain/src/test/data
COPY contrib/testing/verify-b3pow.py \
                                              /opt/b3chain/contrib/testing/verify-b3pow.py
COPY contrib/miner/b3miner-rtl/ref/b3pow_ref.py \
                                              /opt/b3chain/contrib/miner/b3miner-rtl/ref/b3pow_ref.py
COPY src/test/data/b3pow_consensus_vectors.json \
                                              /opt/b3chain/src/test/data/b3pow_consensus_vectors.json

USER b3chain
WORKDIR /home/b3chain

ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/b3chain/contrib/testing/verify-b3pow.py"]
CMD ["--help"]
