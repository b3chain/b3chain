#include "b3_metrics.h"

#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static b3_metrics_snapshot_t s_snap;
static SemaphoreHandle_t s_mtx;
static int64_t s_boot_us;
static uint32_t s_last_raw;
static int s_have_raw;
static int64_t s_rate_us;
static uint64_t s_rate_base;

void b3_metrics_init(void)
{
    s_mtx = xSemaphoreCreateMutex();
    s_boot_us = esp_timer_get_time();
}

void b3_metrics_report_hashrate(float khs)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    s_snap.last_completed_khs = khs;
    xSemaphoreGive(s_mtx);
}

void b3_metrics_note_fpga_count(uint32_t raw_count, uint32_t job_epoch, int batch_done)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    uint32_t delta = 0;
    if (!s_have_raw) {
        s_have_raw = 1;
        s_rate_us = esp_timer_get_time();
        s_rate_base = 0;
    } else if (raw_count >= s_last_raw) {
        delta = raw_count - s_last_raw;
    } else if (s_last_raw > 0xF0000000u) {
        delta = raw_count + (0xffffffffu - s_last_raw) + 1u;
    }
    s_last_raw = raw_count;
    s_snap.hashes_total += delta;
    s_snap.job_epoch = job_epoch;
    int64_t now = esp_timer_get_time();
    int64_t dt = now - s_rate_us;
    if (dt >= 1000000) {
        uint64_t done = s_snap.hashes_total - s_rate_base;
        s_snap.hashrate_khs = (float)done * 1000.0f / (float)dt;
        s_snap.measurement_age_s = 0;
        s_rate_us = now;
        s_rate_base = s_snap.hashes_total;
    } else if (s_rate_us > 0) {
        s_snap.measurement_age_s = (uint32_t)((now - s_rate_us) / 1000000);
    }
    (void)batch_done;
    xSemaphoreGive(s_mtx);
}

void b3_metrics_set_connected(int connected)
{
    xSemaphoreTake(s_mtx, portMAX_DELAY);
    s_snap.stratum_connected = connected ? 1 : 0;
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
