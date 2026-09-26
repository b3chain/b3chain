idf_component_register(
    SRCS "b3_web.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_server esp_netif espressif__cjson
             b3_metrics b3_config b3_fpga
)
