# Copyright (c) 2024-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

include(GNUInstallDirs)

# TODO: libbitcoinkernel is a work in progress consensus engine
#       library, as more and more modules are decoupled from the
#       consensus engine, this list will shrink to only those
#       which are absolutely necessary.
add_library(bitcoinkernel
  bitcoinkernel.cpp
  chain.cpp
  checks.cpp
  chainparams.cpp
  coinstats.cpp
  context.cpp
  cs_main.cpp
  disconnected_transactions.cpp
  mempool_removal_reason.cpp
  ../arith_uint256.cpp
  ../chain.cpp
  ../coins.cpp
  ../compressor.cpp
  ../consensus/merkle.cpp
  ../consensus/tx_check.cpp
  ../consensus/tx_verify.cpp
  ../core_read.cpp
  ../dbwrapper.cpp
  ../deploymentinfo.cpp
  ../deploymentstatus.cpp
  ../flatfile.cpp
  ../hash.cpp
  ../logging.cpp
  ../node/blockstorage.cpp
  ../node/chainstate.cpp
  # b3chain: emergency-checkpoints map is consulted from validation.cpp,
  # which is already linked into libbitcoinkernel.so, so the
  # implementation has to live in this library too.  Without it,
  # linking `b3chain-chainstate` (the kernel-API example) fails with
  # `undefined reference to node::EmergencyCheckpoints::*`.
  ../node/emergency_checkpoints.cpp
  ../node/utxo_snapshot.cpp
  # b3chain: LWMA-3 difficulty retargeting is referenced from pow.cpp
  # (which validation.cpp pulls in).  Without compiling lwma3.cpp into
  # the kernel library, libbitcoinkernel.so has dangling references to
  # `b3pow::CalculateLwma3Target`.
  ../pow/lwma3.cpp
  ../policy/ephemeral_policy.cpp
  ../policy/feerate.cpp
  ../policy/packages.cpp
  ../policy/policy.cpp
  ../policy/rbf.cpp
  ../policy/settings.cpp
  ../policy/truc_policy.cpp
  ../pow.cpp
  ../primitives/block.cpp
  ../primitives/transaction.cpp
  ../pubkey.cpp
  ../random.cpp
  ../randomenv.cpp
  ../script/interpreter.cpp
  ../script/script.cpp
  ../script/script_error.cpp
  ../script/sigcache.cpp
  ../script/solver.cpp
  ../signet.cpp
  ../streams.cpp
  ../support/lockedpool.cpp
  ../sync.cpp
  ../txdb.cpp
  ../txmempool.cpp
  ../uint256.cpp
  ../util/chaintype.cpp
  ../util/check.cpp
  ../util/feefrac.cpp
  ../util/fs.cpp
  ../util/fs_helpers.cpp
  ../util/hasher.cpp
  ../util/moneystr.cpp
  ../util/rbf.cpp
  ../util/serfloat.cpp
  ../util/signalinterrupt.cpp
  ../util/strencodings.cpp
  ../util/string.cpp
  ../util/syserror.cpp
  ../util/threadnames.cpp
  ../util/time.cpp
  ../util/tokenpipe.cpp
  ../validation.cpp
  ../validationinterface.cpp
  ../versionbits.cpp
  $<TARGET_OBJECTS:bitcoin_clientversion>
  $<TARGET_OBJECTS:bitcoin_crypto>
  # b3chain: bitcoin_crypto PUBLIC-links bitcoin_crypto_blake3, but
  # `$<TARGET_OBJECTS:...>` only extracts the *direct* object files of
  # the named target; transitive link dependencies of a STATIC library
  # are not propagated.  Pull the BLAKE3 objects in explicitly so
  # libbitcoinkernel.so has `blake3_hasher_init/update/finalize/...`
  # symbols that validation.cpp (and the rest of the b3chain consensus
  # engine) calls into.
  $<TARGET_OBJECTS:bitcoin_crypto_blake3>
  $<TARGET_OBJECTS:leveldb>
  $<TARGET_OBJECTS:crc32c>
)
target_link_libraries(bitcoinkernel
  PRIVATE
    core_interface
    secp256k1_objs
    # b3chain: emergency_checkpoints.cpp parses operator-supplied
    # JSON via UniValue, so the kernel needs to link against
    # univalue.  No upstream Bitcoin Core kernel source uses
    # UniValue, so this is purely a b3chain addition.
    univalue
    $<$<PLATFORM_ID:Windows>:bcrypt>
    $<TARGET_NAME_IF_EXISTS:USDT::headers>
  PUBLIC
    Boost::headers
)

target_include_directories(bitcoinkernel PRIVATE
  $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/src/leveldb/include>
  # b3chain: see univalue link above; the header lives next to
  # the generated target_include_directories of the univalue target,
  # but we add the explicit BUILD_INTERFACE path here to avoid relying
  # on transitive include propagation through `univalue` (the
  # univalue target itself only exports its include dir as PUBLIC,
  # which is fine, but we duplicate the path for clarity).
  $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/src/univalue/include>
)

# libbitcoinkernel requires default symbol visibility, explicitly
# specify that here so that things still work even when user
# configures with -DREDUCE_EXPORTS=ON
#
# Note this is a quick hack that will be removed as we
# incrementally define what to export from the library.
set_target_properties(bitcoinkernel PROPERTIES
  CXX_VISIBILITY_PRESET default
)

# Add a convenience libbitcoinkernel target as a synonym for bitcoinkernel.
add_custom_target(libbitcoinkernel)
add_dependencies(libbitcoinkernel bitcoinkernel)

configure_file(${PROJECT_SOURCE_DIR}/libbitcoinkernel.pc.in ${PROJECT_BINARY_DIR}/libbitcoinkernel.pc @ONLY)
install(FILES ${PROJECT_BINARY_DIR}/libbitcoinkernel.pc DESTINATION "${CMAKE_INSTALL_LIBDIR}/pkgconfig" COMPONENT libbitcoinkernel)

install(TARGETS bitcoinkernel
  RUNTIME
    DESTINATION ${CMAKE_INSTALL_BINDIR}
    COMPONENT libbitcoinkernel
  LIBRARY
    DESTINATION ${CMAKE_INSTALL_LIBDIR}
    COMPONENT libbitcoinkernel
  ARCHIVE
    DESTINATION ${CMAKE_INSTALL_LIBDIR}
    COMPONENT libbitcoinkernel
)
