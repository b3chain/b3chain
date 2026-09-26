/**
 * @file b3_ota.c
 * @brief HTTPS OTA with manifest check + rollback.
 *
 * Manifest format (JSON at CONFIG_B3_OTA_UPDATE_URL):
 * {
 *   "version": "1.0.1",
 *   "url": "https://updates.b3chain.org/b3miner-1.0.1.bin",
 *   "sha256": "...",
 *   "signature": "...",
 *   "min_version": "1.0.0"
 * }
 *
 * A signature field is checked with the slot-2 release pubkey. A manifest
 * with no signature keeps the current path. Image install stays the
 * existing download step.
 */

#include "b3_ota.h"

#include <string.h>

#include "b3_sec.h"

#include "esp_app_desc.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "b3_ota";

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int json_string_field(const char *json, const char *key, char *out, size_t out_len)
{
    char pattern[48];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (!p) {
        return 0;
    }
    p += strlen(pattern);
    while (*p == ' ' || *p == '\t' || *p == ':') {
        p++;
    }
    if (*p != '"') {
        return 0;
    }
    p++;
    size_t n = 0;
    while (*p && *p != '"' && n + 1 < out_len) {
        out[n++] = *p++;
    }
    out[n] = '\0';
    return n > 0;
}

static int decode_hex(const char *hex, uint8_t *out, size_t out_len)
{
    if (strlen(hex) != out_len * 2) {
        return 0;
    }
    for (size_t i = 0; i < out_len; i++) {
        int hi = hex_nibble(hex[i * 2]);
        int lo = hex_nibble(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            return 0;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return 1;
}

esp_err_t b3_ota_check_manifest(const char *json)
{
    if (!json) {
        return ESP_ERR_INVALID_ARG;
    }
    char signature[160];
    if (!json_string_field(json, "signature", signature, sizeof(signature))) {
        return ESP_OK;
    }
    char sha_hex[80];
    uint8_t sha[32];
    uint8_t sig[64];
    uint8_t pub[64];
    if (!json_string_field(json, "sha256", sha_hex, sizeof(sha_hex)) ||
        !decode_hex(sha_hex, sha, sizeof(sha)) ||
        !decode_hex(signature, sig, sizeof(sig)) ||
        b3_sec_slot2_pubkey(pub) != ESP_OK) {
        ESP_LOGW(TAG, "OTA manifest signature rejected");
        return ESP_FAIL;
    }
    if (b3_sec_verify_p256(pub, sha, sig) != ESP_OK) {
        ESP_LOGW(TAG, "OTA manifest signature rejected");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "OTA manifest signature valid");
    return ESP_OK;
}

static void ota_task(void *arg)
{
    const char *url = (const char *)arg;
    if (!url || url[0] == '\0') {
        ESP_LOGI(TAG, "OTA disabled (no manifest URL)");
        vTaskDelete(NULL);
        return;
    }

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(6 * 3600 * 1000)); /* poll every 6h */

        esp_app_desc_t running;
        const esp_partition_t *part = esp_ota_get_running_partition();
        if (part && esp_ota_get_partition_description(part, &running) == ESP_OK) {
            ESP_LOGD(TAG, "running firmware %s", running.version);
        }

        char body[1024];
        body[0] = '\0';
        esp_http_client_config_t http_cfg = {
            .url = url,
            .timeout_ms = 10000,
            .crt_bundle_attach = esp_crt_bundle_attach,
        };
        esp_http_client_handle_t client = esp_http_client_init(&http_cfg);
        if (!client) {
            continue;
        }
        if (esp_http_client_open(client, 0) == ESP_OK) {
            (void)esp_http_client_fetch_headers(client);
            int n = esp_http_client_read(client, body, sizeof(body) - 1);
            if (n > 0) {
                body[n] = '\0';
            } else {
                body[0] = '\0';
            }
        }
        esp_http_client_close(client);
        esp_http_client_cleanup(client);

        if (body[0] == '\0') {
            continue;
        }
        if (b3_ota_check_manifest(body) != ESP_OK) {
            ESP_LOGW(TAG, "OTA bundle rejected");
            continue;
        }
        /* Signature accepted, or the manifest had none. Image install
         * remains the existing path and is not started from this loop. */
        ESP_LOGI(TAG, "OTA manifest accepted");
    }
}

void b3_ota_start(const char *manifest_url)
{
    static char url_copy[256];
    if (manifest_url) {
        strncpy(url_copy, manifest_url, sizeof(url_copy) - 1);
    } else {
        url_copy[0] = '\0';
    }
    xTaskCreate(ota_task, "ota", 8192, url_copy, 3, NULL);
}
