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
target_link_libraries(bitcoin_wallet
  PRIVATE
    core_interface
    bitcoin_common
    $<TARGET_NAME_IF_EXISTS:unofficial::sqlite3::sqlite3>
    # CMake's stock `FindSQLite3` module exports the IMPORTED target
    # under the name `SQLite::SQLite3`.  Some package providers (e.g.
    # Conan, certain vcpkg ports, distro CMake config files) instead
    # export `SQLite3::SQLite3` to match the package name.  Reference
    # both, gated by `TARGET_NAME_IF_EXISTS` so the missing one is
    # silently dropped, otherwise the wallet TU compiles but the
    # final executable fails to link with `undefined reference to
    # sqlite3_*` (e.g. on the 32-bit ARM cross-compile via depends).
    $<TARGET_NAME_IF_EXISTS:SQLite::SQLite3>
    $<TARGET_NAME_IF_EXISTS:SQLite3::SQLite3>
    univalue
    Boost::headers
    $<TARGET_NAME_IF_EXISTS:USDT::headers>
)
