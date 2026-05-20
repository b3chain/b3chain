# Copyright (c) 2023-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

# Wallet functionality used by bitcoind and bitcoin-wallet executables.
add_library(bitcoin_wallet STATIC EXCLUDE_FROM_ALL
  coincontrol.cpp
  coinselection.cpp
  context.cpp
  crypter.cpp
  db.cpp
  dump.cpp
  external_signer_scriptpubkeyman.cpp
  feebumper.cpp
  fees.cpp
  interfaces.cpp
  load.cpp
  migrate.cpp
  receive.cpp
  rpc/addresses.cpp
  rpc/backup.cpp
  rpc/coins.cpp
  rpc/encrypt.cpp
  rpc/signmessage.cpp
  rpc/spend.cpp
  rpc/transactions.cpp
  rpc/util.cpp
  rpc/wallet.cpp
  scriptpubkeyman.cpp
  spend.cpp
  sqlite.cpp
  transaction.cpp
  wallet.cpp
  walletdb.cpp
  walletutil.cpp
)
# CMake's stock `FindSQLite3` module historically exported its IMPORTED
# target as `SQLite::SQLite3`.  CMake 3.27+ renamed it to the canonical
# `SQLite3::SQLite3` (matching the package name) and kept the legacy
# name as a *deprecated alias*.  Linking against the deprecated alias
# is fatal under `-Werror=dev` (used by every CI build), so we cannot
# unconditionally reference both.
#
# Strategy:
#   1. Prefer `SQLite3::SQLite3`     (CMake >= 3.27, vcpkg, Conan, ...)
#   2. Fall back to `SQLite::SQLite3` (older CMake, e.g. Ubuntu 22.04
#      ships CMake 3.22 where only the legacy name exists)
#   3. `unofficial::sqlite3::sqlite3` is the vcpkg port name
#
# `if(TARGET ...)` evaluates at configure time, so the target name
# baked into `bitcoin_wallet`'s link line is never the deprecated
# alias on a CMake that already exposes the canonical one.
set(_b3_sqlite3_target "")
if(TARGET SQLite3::SQLite3)
  set(_b3_sqlite3_target SQLite3::SQLite3)
elseif(TARGET SQLite::SQLite3)
  set(_b3_sqlite3_target SQLite::SQLite3)
endif()

target_link_libraries(bitcoin_wallet
  PRIVATE
    core_interface
    bitcoin_common
    $<TARGET_NAME_IF_EXISTS:unofficial::sqlite3::sqlite3>
    ${_b3_sqlite3_target}
    univalue
    Boost::headers
    $<TARGET_NAME_IF_EXISTS:USDT::headers>
)
