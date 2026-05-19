#include "b3_metrics.h"

#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static b3_metrics_snapshot_t s_snap;
static SemaphoreHandle_t s_mtx;
static int64_t s_boot_us;

void b3_metrics_init(void)
{
    s_mtx = xSemaphoreCreateMutex();
    s_boot_us = esp_timer_get_time();
}

void b3_metrics_report_hashrate(float khs)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    s_snap.hashrate_khs = khs;
    xSemaphoreGive(s_mtx);
}

void b3_metrics_share_accepted(void)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    s_snap.shares_accepted++;
    xSemaphoreGive(s_mtx);
}

void b3_metrics_share_rejected(void)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    s_snap.shares_rejected++;
    xSemaphoreGive(s_mtx);
}

void b3_metrics_get_snapshot(b3_metrics_snapshot_t *out)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    *out = s_snap;
    out->uptime_s = (uint32_t)((esp_timer_get_time() - s_boot_us) / 1000000);
    xSemaphoreGive(s_mtx);
}
