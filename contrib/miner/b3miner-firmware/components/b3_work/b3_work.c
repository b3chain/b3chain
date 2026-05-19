#include "b3_work.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static b3_work_job_t s_job;
static uint32_t s_latest_epoch;
static SemaphoreHandle_t s_job_mtx;

void b3_work_init(void)
{
    s_job_mtx = xSemaphoreCreateMutex();
    s_latest_epoch = 0;
}

void b3_work_publish_job(const b3_work_job_t *job)
{
    xSemaphoreTake(s_job_mtx, portMAX_DELAY);
    s_job = *job;
    s_latest_epoch = job->epoch;
    xSemaphoreGive(s_job_mtx);
}

bool b3_work_wait_job(b3_work_job_t *out, TickType_t timeout)
{
    if (!out) {
        return false;
    }
    if (xSemaphoreTake(s_job_mtx, timeout) != pdTRUE) {
        return false;
    }
    *out = s_job;
    xSemaphoreGive(s_job_mtx);
    return s_job.epoch != 0;
}

bool b3_work_job_stale(uint32_t epoch)
{
    return epoch != s_latest_epoch;
}

esp_err_t b3_work_build_header(const b3_work_job_t *job, uint32_t extranonce2,
                               uint32_t ntime, uint32_t nonce,
                               uint8_t header_out[80])
{
    if (!job || !header_out) {
        return ESP_ERR_INVALID_ARG;
    }
    /* FILL IN — port from contrib/miner/b3chain-gpuminer/src/work/header.rs:
     * 1. coinbase = hex_decode(coinb1) || extranonce1 || en2 || hex_decode(coinb2)
     * 2. coinbase_hash = SHA256d(coinbase)
     * 3. merkle_root = fold merkle_branch with coinbase_hash
     * 4. pack 80-byte header LE per doc/stratum.md
     */
    (void)extranonce2;
    (void)ntime;
    (void)nonce;
    memset(header_out, 0, 80);
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t b3_work_build_pow_seed(const b3_work_job_t *job, uint32_t extranonce2,
                                 uint32_t ntime, uint8_t seed_out[32])
{
    uint8_t hdr[80];
    ESP_ERROR_CHECK(b3_work_build_header(job, extranonce2, ntime, 0, hdr));
    /* FILL IN: BLAKE3(hdr) for B3PoW-Scratch seed, or pass header to FPGA */
    (void)job;
    memset(seed_out, 0, 32);
    return ESP_ERR_NOT_SUPPORTED;
}
