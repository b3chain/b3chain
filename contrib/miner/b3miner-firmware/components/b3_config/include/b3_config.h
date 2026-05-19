#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef enum {
    B3_STRATUM_PROTO_V1 = 1,
    B3_STRATUM_PROTO_V2 = 2,
} b3_stratum_proto_t;

typedef struct {
    char pool_url[128];       /* stratum+tcp://host:port or stratum2+tcp:// */
    char worker_user[96];     /* email.worker per doc/stratum.md */
    char worker_pass[32];
    b3_stratum_proto_t stratum_proto;
    float default_diff;
    bool  use_tls;
    char  hostname[32];
} b3_runtime_config_t;

void b3_config_init(void);
void b3_config_load_runtime(b3_runtime_config_t *out);
esp_err_t b3_config_save_runtime(const b3_runtime_config_t *cfg);
esp_err_t b3_config_parse_pool_url(const char *url, char *host, size_t host_len,
                                   uint16_t *port, bool *use_tls,
                                   b3_stratum_proto_t *proto);
