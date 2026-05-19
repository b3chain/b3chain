if(CONFIG_B3_FPGA_SIM)
    set(b3_fpga_backend "b3_fpga_sim.c")
else()
    set(b3_fpga_backend "b3_fpga.c")
endif()

idf_component_register(
    SRCS ${b3_fpga_backend} "b3_fpga_worker.c"
    INCLUDE_DIRS "include"
    REQUIRES driver esp_timer mbedtls b3_events b3_work b3_metrics
)
