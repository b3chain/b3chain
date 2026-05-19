idf_component_register(
    SRCS "b3_stratum_v1.c" "b3_stratum_json.c"
    INCLUDE_DIRS "include"
    REQUIRES lwip esp-tls mbedtls json b3_config b3_events b3_work
)
