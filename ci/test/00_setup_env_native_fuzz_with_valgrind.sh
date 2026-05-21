#!/usr/bin/env bash
#
# Copyright (c) 2019-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

export LC_ALL=C.UTF-8

export CI_IMAGE_NAME_TAG="mirror.gcr.io/ubuntu:24.04"
export CONTAINER_NAME=ci_native_fuzz_valgrind
export PACKAGES="libevent-dev libboost-dev libsqlite3-dev valgrind libcapnp-dev capnproto"
export NO_DEPENDS=1
export RUN_UNIT_TESTS=false
export RUN_FUNCTIONAL_TESTS=false
export RUN_FUZZ_TESTS=true
# b3chain: see comment in 00_setup_env_mac_native_fuzz.sh for why the
# *_package_eval targets are skipped.
export FUZZ_TESTS_CONFIG="--valgrind --exclude=ephemeral_package_eval,tx_package_eval,b3pow_random_header"
export GOAL="all"
export BITCOIN_CONFIG="\
 -DBUILD_FOR_FUZZING=ON \
 -DCMAKE_CXX_FLAGS='-Wno-error=array-bounds' \
"
