#include "b3_config.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "b3_config";
static const char *NS = "b3miner";

void b3_config_init(void)
{
    ESP_LOGI(TAG, "config namespace ready");
}

esp_err_t b3_config_parse_pool_url(const char *url, char *host, size_t host_len,
                                   uint16_t *port, bool *use_tls,
                                   b3_stratum_proto_t *proto)
{
    if (!url || !host || !port || !use_tls || !proto) {
        return ESP_ERR_INVALID_ARG;
    }
    *use_tls = false;
    *proto = B3_STRATUM_PROTO_V1;
    *port = 3333;

    const char *rest = url;
    if (strncmp(rest, "stratum2+ssl://", 15) == 0) {
        *use_tls = true;
        *proto = B3_STRATUM_PROTO_V2;
        rest += 15;
    } else if (strncmp(rest, "stratum2+tcp://", 15) == 0) {
        *proto = B3_STRATUM_PROTO_V2;
        rest += 15;
    } else if (strncmp(rest, "stratum+ssl://", 14) == 0) {
        *use_tls = true;
        rest += 14;
    } else if (strncmp(rest, "stratum+tcp://", 14) == 0) {
        rest += 14;
    } else if (strncmp(rest, "stratum://", 10) == 0) {
        rest += 10;
    } else {
        return ESP_ERR_INVALID_ARG;
    }

    const char *colon = strrchr(rest, ':');
    if (!colon) {
        strncpy(host, rest, host_len - 1);
        host[host_len - 1] = '\0';
        return ESP_OK;
    }
    size_t hlen = (size_t)(colon - rest);
    if (hlen >= host_len) {
        return ESP_ERR_INVALID_SIZE;
    }
    memcpy(host, rest, hlen);
    host[hlen] = '\0';
    int p = atoi(colon + 1);
    if (p <= 0 || p > 65535) {
        return ESP_ERR_INVALID_ARG;
    }
    *port = (uint16_t)p;
    return ESP_OK;
}

void b3_config_load_runtime(b3_runtime_config_t *out)
{
    memset(out, 0, sizeof(*out));
    strncpy(out->pool_url, CONFIG_B3_STRATUM_DEFAULT_URL, sizeof(out->pool_url) - 1);
    strncpy(out->worker_user, CONFIG_B3_STRATUM_DEFAULT_USER, sizeof(out->worker_user) - 1);
    strncpy(out->worker_pass, CONFIG_B3_STRATUM_DEFAULT_PASS, sizeof(out->worker_pass) - 1);
    out->default_diff = (float)CONFIG_B3_STRATUM_DEFAULT_DIFF;
    out->stratum_proto = B3_STRATUM_PROTO_V1;
    strncpy(out->hostname, CONFIG_B3_DEVICE_NAME, sizeof(out->hostname) - 1);

    nvs_handle_t h;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) {
        goto parse_url;
    }
    size_t len = sizeof(out->pool_url);
    nvs_get_str(h, "pool_url", out->pool_url, &len);
    len = sizeof(out->worker_user);
    nvs_get_str(h, "worker_user", out->worker_user, &len);
    len = sizeof(out->worker_pass);
    nvs_get_str(h, "worker_pass", out->worker_pass, &len);
    len = sizeof(out->hostname);
    nvs_get_str(h, "hostname", out->hostname, &len);
    uint8_t proto = 0;
    if (nvs_get_u8(h, "stratum_proto", &proto) == ESP_OK && proto != 0) {
        out->stratum_proto = (b3_stratum_proto_t)proto;
    }
    nvs_close(h);

parse_url:
    {
        char host[96];
        uint16_t port = 3333;
        b3_config_parse_pool_url(out->pool_url, host, sizeof(host), &port,
                                 &out->use_tls, &out->stratum_proto);
    }
}

esp_err_t b3_config_save_runtime(const b3_runtime_config_t *cfg)
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open(NS, NVS_READWRITE, &h));
    ESP_ERROR_CHECK(nvs_set_str(h, "pool_url", cfg->pool_url));
    ESP_ERROR_CHECK(nvs_set_str(h, "worker_user", cfg->worker_user));
    ESP_ERROR_CHECK(nvs_set_str(h, "worker_pass", cfg->worker_pass));
    ESP_ERROR_CHECK(nvs_set_str(h, "hostname", cfg->hostname));
    ESP_ERROR_CHECK(nvs_set_u8(h, "stratum_proto", (uint8_t)cfg->stratum_proto));
    esp_err_t err = nvs_commit(h);
    nvs_close(h);
    return err;
}
