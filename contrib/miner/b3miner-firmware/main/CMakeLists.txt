idf_component_register(
    SRCS "app_main.c"
    INCLUDE_DIRS "."
    REQUIRES nvs_flash esp_netif esp_eth esp_event esp_wifi
             b3_config b3_events b3_fpga b3_work
             b3_stratum_v1 b3_stratum_v2 b3_web b3_ota b3_metrics
             driver esp_timer
)
