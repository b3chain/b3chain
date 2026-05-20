# Copyright (c) 2023-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

function(generate_setup_nsi)
  set(abs_top_srcdir ${PROJECT_SOURCE_DIR})
  set(abs_top_builddir ${PROJECT_BINARY_DIR})
  set(CLIENT_URL ${PROJECT_HOMEPAGE_URL})
  # b3chain renames the upstream Bitcoin Core binaries.  The CMake
  # targets keep the upstream names (bitcoin-qt, bitcoind, ...), but
  # `set_target_properties(... OUTPUT_NAME b3chain-...)` makes the
  # actual installed/strippable .exe land under the renamed path.
  # The NSIS installer template references files via these
  # @VARS@, so we must use the *output* names here -- otherwise
  # `makensis` looks for `release/bitcoin-qt.exe`, which never
  # exists, and aborts with:
  #   File: ".../release/bitcoin-qt.exe" -> no files found.
  set(CLIENT_TARNAME "b3chain")
  set(BITCOIN_WRAPPER_NAME "b3chain")
  set(BITCOIN_GUI_NAME "b3chain-qt")
  set(BITCOIN_DAEMON_NAME "b3chaind")
  set(BITCOIN_CLI_NAME "b3chain-cli")
  set(BITCOIN_TX_NAME "b3chain-tx")
  set(BITCOIN_WALLET_TOOL_NAME "b3chain-wallet")
  set(BITCOIN_TEST_NAME "test_bitcoin")
  set(EXEEXT ${CMAKE_EXECUTABLE_SUFFIX})
  configure_file(${PROJECT_SOURCE_DIR}/share/setup.nsi.in ${PROJECT_BINARY_DIR}/bitcoin-win64-setup.nsi USE_SOURCE_PERMISSIONS @ONLY)
endfunction()
