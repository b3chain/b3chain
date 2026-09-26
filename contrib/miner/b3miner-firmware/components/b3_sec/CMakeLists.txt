idf_component_register(
    SRCS "b3_sec.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_driver_i2c esp_hw_support mbedtls
    PRIV_REQUIRES espressif__esp-cryptoauthlib
)

idf_component_get_property(mbedtls_dir mbedtls COMPONENT_DIR)
target_include_directories(${COMPONENT_LIB} PRIVATE
    "${mbedtls_dir}/mbedtls/tf-psa-crypto/drivers/builtin/include")
