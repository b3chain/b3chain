#!/bin/bash -eu
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#
# OSS-Fuzz build script for b3chain.
#
# Invoked by the OSS-Fuzz infrastructure inside the container built
# from the sibling Dockerfile.  Mirrors the upstream Bitcoin Core
# build script (google/oss-fuzz/projects/bitcoin-core/build.sh) but
# uses the b3chain repo layout and the b3chain-vendored libsecp256k1.
#
# OSS-Fuzz contract:
#   * Expected to leave one self-contained fuzz binary per fuzz target
#     under $OUT/.
#   * $SANITIZER, $ARCHITECTURE, $CC, $CXX, $CFLAGS, $CXXFLAGS,
#     $LDFLAGS, $LIB_FUZZING_ENGINE are pre-set by the infrastructure.
#   * If $OSS_FUZZ_CI=1 we only have to build a sample of targets.

# Embed build timestamp into the log for easier debugging on the
# OSS-Fuzz dashboard.
date

cd "$SRC/b3chain/"

# Build dependencies via the `depends/` system.  This produces a
# fully-static toolchain so the resulting fuzz binaries don't pick up
# host shared-library versions that ClusterFuzz can't reproduce.
if [ "$ARCHITECTURE" = "i386" ]; then
    export BUILD_TRIPLET="i386-linux-gnu"
else
    export BUILD_TRIPLET="x86_64-pc-linux-gnu"
fi

export CFLAGS="$CFLAGS -flto=full"
export CXXFLAGS="$CXXFLAGS -flto=full"
export LDFLAGS="-fuse-ld=lld -flto=full"
export CPPFLAGS="-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_DEBUG \
                 -DBOOST_MULTI_INDEX_ENABLE_SAFE_MODE"

(
    cd depends
    sed -i --regexp-extended '/.*rm -rf .*extract_dir.*/d' ./funcs.mk
    make HOST="$BUILD_TRIPLET" DEBUG=1 NO_QT=1 NO_ZMQ=1 NO_USDT=1 \
         NO_IPC=1 \
         AR=llvm-ar NM=llvm-nm RANLIB=llvm-ranlib STRIP=llvm-strip \
         -j"$(nproc)"
)

# Configure the build to produce fuzz binaries.
sed -i "s|PROVIDE_FUZZ_MAIN_FUNCTION|NEVER_PROVIDE_MAIN_FOR_OSS_FUZZ|g" \
       "./src/test/fuzz/util/CMakeLists.txt"

EXTRA_BUILD_OPTIONS=
if [ "$SANITIZER" = "memory" ]; then
    # _FORTIFY_SOURCE is incompatible with MSAN.
    EXTRA_BUILD_OPTIONS="-DAPPEND_CPPFLAGS=-U_FORTIFY_SOURCE"
fi

cmake -B build_fuzz \
      --toolchain "depends/${BUILD_TRIPLET}/toolchain.cmake" \
      -DCMAKE_C_FLAGS_RELWITHDEBINFO="" \
      -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="" \
      -DBUILD_FOR_FUZZING=ON \
      -DFUZZ_LIBS="$LIB_FUZZING_ENGINE" \
      $EXTRA_BUILD_OPTIONS

cmake --build build_fuzz -j"$(nproc)"

# Enumerate all fuzz targets the build produced.
WRITE_ALL_FUZZ_TARGETS_AND_ABORT="/tmp/fuzz_targets.txt" \
    "./build_fuzz/bin/fuzz" || true
readarray FUZZ_TARGETS < "/tmp/fuzz_targets.txt"

if [ -n "${OSS_FUZZ_CI-}" ]; then
    FUZZ_TARGETS=( "${FUZZ_TARGETS[@]:0:2}" )
fi

# OSS-Fuzz wants one binary per target.  Use the same magic-string
# trick as bitcoin-core to avoid rebuilding once per target.
export MAGIC_STR="b5813eee2abc9d3358151f298b75a72264ffa119d2f71ae7fefa15c4b70b4bc5b38e87e3107a730f25891ea428b2b4fabe7a84f5bfa73c79e0479e085e4ff157"
sed -i "s|std::getenv(\"FUZZ\")|\"$MAGIC_STR\"|g" "./src/test/fuzz/fuzz.cpp"
cmake --build build_fuzz -j"$(nproc)"

for fuzz_target in "${FUZZ_TARGETS[@]}"; do
    df --human-readable ./src
    python3 -c "
c_str_target = b\"${fuzz_target}\x00\"
c_str_magic  = b\"$MAGIC_STR\"
dat = open('./build_fuzz/bin/fuzz', 'rb').read()
dat = dat.replace(c_str_magic, c_str_target + c_str_magic[len(c_str_target):])
open(\"$OUT/$fuzz_target\", 'wb').write(dat)
"
    chmod +x "$OUT/$fuzz_target"

    # Seed-corpus zip if we have one (the b3chain-qa repo is not yet
    # bootstrapped; this loop is a no-op until it is).
    if [ -d "assets/fuzz_corpora/$fuzz_target" ]; then
        (
            cd assets/fuzz_corpora
            zip --recurse-paths --quiet --junk-paths \
                "$OUT/${fuzz_target}_seed_corpus.zip" "${fuzz_target}"
        )
    fi
done

# Dictionaries (no-op until assets/fuzz_dicts/ exists).
if [ -d assets/fuzz_dicts ]; then
    cp assets/fuzz_dicts/*.dict "$OUT/" 2>/dev/null || true
fi
