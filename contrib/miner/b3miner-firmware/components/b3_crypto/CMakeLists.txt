set(BLAKE3_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../../../src/crypto/blake3")

idf_component_register(
    SRCS
        "b3_crypto.c"
        "${BLAKE3_DIR}/blake3.c"
        "${BLAKE3_DIR}/blake3_dispatch.c"
        "${BLAKE3_DIR}/blake3_portable.c"
    INCLUDE_DIRS
        "include"
        "${BLAKE3_DIR}"
)
