idf_component_register(
    SRCS "b3_stratum_v2.c"
    INCLUDE_DIRS "include"
    REQUIRES mbedtls b3_config b3_work b3_events
)
