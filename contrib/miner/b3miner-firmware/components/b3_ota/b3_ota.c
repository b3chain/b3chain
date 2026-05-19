/**
 * @file b3_ota.c
 * @brief HTTPS OTA with manifest check + rollback.
 *
 * Manifest format (JSON at CONFIG_B3_OTA_UPDATE_URL):
 * {
 *   "version": "1.0.1",
 *   "url": "https://updates.b3chain.org/b3miner-1.0.1.bin",
 *   "sha256": "...",
 *   "min_version": "1.0.0"
 * }
 *
 * Production: enable CONFIG_SECURE_BOOT + signed app images.
 * Rollback: esp_ota_mark_app_valid_cancel_rollback() after 24h stable mining.
 */

#include "b3_ota.h"

#include <string.h>

#include "b3_events.h"

#include "esp_app_desc.h"
#include "esp_https_ota.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "b3_ota";

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

        /* FILL IN:
         * 1. GET manifest_url over HTTPS (cert bundle)
         * 2. Compare semver to esp_app_get_description()->version
         * 3. If newer: b3_events_post(B3_EVT_OTA_PENDING), pause mining
         * 4. esp_https_ota() with sha256 check
         * 5. esp_restart()
         */

        esp_app_desc_t running;
        const esp_partition_t *part = esp_ota_get_running_partition();
        if (part && esp_ota_get_partition_description(part, &running) == ESP_OK) {
            ESP_LOGD(TAG, "running firmware %s", running.version);
        }
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
    xTaskCreate(ota_task, "ota", 6144, url_copy, 3, NULL);
}
