#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

idf.py -B build-ci-real \
    -D SDKCONFIG=sdkconfig.ci.real \
    -D SDKCONFIG_DEFAULTS=sdkconfig.defaults \
    build

idf.py -B build-ci-sim \
    -D SDKCONFIG=sdkconfig.ci.sim \
    -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.sim.defaults' \
    build
