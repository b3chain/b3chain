idf_component_register(
    SRCS "b3_sec.c"
    INCLUDE_DIRS "include"
    REQUIRES driver mbedtls
    PRIV_REQUIRES espressif__esp-cryptoauthlib
)
