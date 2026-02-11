# Copyright (c) 2023-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

add_library(bitcoin_crypto STATIC EXCLUDE_FROM_ALL
  aes.cpp
  chacha20.cpp
  chacha20poly1305.cpp
  hex_base.cpp
  hkdf_sha256_32.cpp
  hmac_sha256.cpp
  hmac_sha512.cpp
  muhash.cpp
  poly1305.cpp
  ripemd160.cpp
  sha1.cpp
  sha256.cpp
  sha256_sse4.cpp
  sha3.cpp
  sha512.cpp
  siphash.cpp
  ../support/cleanse.cpp
)

target_link_libraries(bitcoin_crypto
  PRIVATE
    core_interface
)

# BLAKE3 implementation for b3chain PoW — with SIMD acceleration
# The dispatch layer auto-detects CPU features via CPUID at runtime and
# selects the fastest path: portable → SSE2 → SSE4.1 → AVX2 → AVX-512.
add_library(bitcoin_crypto_blake3 STATIC EXCLUDE_FROM_ALL
  blake3/blake3.c
  blake3/blake3_dispatch.c
  blake3/blake3_portable.c
)

# On x86-64 non-Windows, add hand-optimized assembly implementations.
# These provide 3-16x speedup over the portable C fallback depending on
# available CPU instruction sets (critical for PoW mining/validation).
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64" AND NOT WIN32)
  enable_language(ASM)
  target_sources(bitcoin_crypto_blake3 PRIVATE
    blake3/blake3_sse2_x86-64_unix.S
    blake3/blake3_sse41_x86-64_unix.S
    blake3/blake3_avx2_x86-64_unix.S
    blake3/blake3_avx512_x86-64_unix.S
  )
endif()

target_include_directories(bitcoin_crypto_blake3 PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/blake3)
target_link_libraries(bitcoin_crypto_blake3 PRIVATE core_interface)
target_link_libraries(bitcoin_crypto PUBLIC bitcoin_crypto_blake3)

if(HAVE_SSE41)
  target_compile_definitions(bitcoin_crypto PRIVATE ENABLE_SSE41)
  target_sources(bitcoin_crypto PRIVATE sha256_sse41.cpp)
  set_property(SOURCE sha256_sse41.cpp PROPERTY
    COMPILE_OPTIONS ${SSE41_CXXFLAGS}
  )
endif()

if(HAVE_AVX2)
  target_compile_definitions(bitcoin_crypto PRIVATE ENABLE_AVX2)
  target_sources(bitcoin_crypto PRIVATE sha256_avx2.cpp)
  set_property(SOURCE sha256_avx2.cpp PROPERTY
    COMPILE_OPTIONS ${AVX2_CXXFLAGS}
  )
endif()

if(HAVE_SSE41 AND HAVE_X86_SHANI)
  target_compile_definitions(bitcoin_crypto PRIVATE ENABLE_SSE41 ENABLE_X86_SHANI)
  target_sources(bitcoin_crypto PRIVATE sha256_x86_shani.cpp)
  set_property(SOURCE sha256_x86_shani.cpp PROPERTY
    COMPILE_OPTIONS ${SSE41_CXXFLAGS} ${X86_SHANI_CXXFLAGS}
  )
endif()

if(HAVE_ARM_SHANI)
  target_compile_definitions(bitcoin_crypto PRIVATE ENABLE_ARM_SHANI)
  target_sources(bitcoin_crypto PRIVATE sha256_arm_shani.cpp)
  set_property(SOURCE sha256_arm_shani.cpp PROPERTY
    COMPILE_OPTIONS ${ARM_SHANI_CXXFLAGS}
  )
endif()
