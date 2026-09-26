idf_component_register(
    SRCS "b3_sec.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_driver_i2c mbedtls
    PRIV_REQUIRES espressif__esp-cryptoauthlib
)
