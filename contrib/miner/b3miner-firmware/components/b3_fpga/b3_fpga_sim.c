/**
 * @file b3_fpga_sim.c
 * @brief In-memory FPGA simulator — drop-in replacement for b3_fpga.c.
 *
 * Selected via CONFIG_B3_FPGA_SIM=y in menuconfig.
 *
 * Lets the firmware run end-to-end against a real Stratum pool on a
 * bare ESP32-S3 devkit (no KU5P required), producing synthetic shares
 * at CONFIG_B3_FPGA_SIM_KHS kH/s and CONFIG_B3_FPGA_SIM_SHARE_INTERVAL_MS
 * cadence.
 *
 * State machine mirrors the real backend:
 *
 *   IDLE ── submit_job() ──> RUNNING ── share_timer ──> share_valid=1
 *     ▲                                                       │
 *     └────────────────── ack_share() ────────────────────────┘
 *
 * Verified loop (Tier-3):
 *   1. TRIGGER  : b3_fpga_submit_job() writes job + sets RUNNING
 *   2. PROCESS  : sim_tick_task increments hash_count, fires shares
 *   3. RESULT   : b3_fpga_poll_share() returns the latched share
 *   4. BYPASS   : if job stale (epoch bumped) sim_tick aborts current batch
 */

#include "b3_fpga.h"

#include <inttypes.h>
#include <string.h>

#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"
#include "sdkconfig.h"

static const char *TAG = "b3_fpga_sim";

#define SIM_KHS                CONFIG_B3_FPGA_SIM_KHS
#define SIM_SHARE_INTERVAL_MS  CONFIG_B3_FPGA_SIM_SHARE_INTERVAL_MS
#define SIM_TICK_MS            100  /* hashrate accounting granularity */

/* ---- Sim state -------------------------------------------------------- */

typedef enum {
    SIM_IDLE = 0,
    SIM_SCRATCH_INIT,
    SIM_RUNNING,
    SIM_SHARE_LATCHED,
} sim_state_t;

typedef struct {
    SemaphoreHandle_t mtx;
    sim_state_t       state;

    /* Current job */
    uint8_t  seed[32];
    uint8_t  prev_block_hash[32];
    uint32_t job_epoch;
    uint32_t nonce_start;
    uint32_t nonce_end;
    uint32_t nonce_cursor;

    /* Counters */
    uint64_t hashes_total;
    uint32_t hash_count;            /* visible in REG_HASH_COUNT, low 32 */
    int64_t  job_start_us;
    int64_t  last_share_us;

    /* Latched share waiting to be drained by poll_share */
    b3_fpga_share_t pending_share;
    bool            share_valid;

    /* IRQ to host (optional — fpga_worker polls regardless) */
    int irq_gpio;
} sim_ctx_t;

static sim_ctx_t s_sim;

/* ---- Helpers ---------------------------------------------------------- */

static void sim_lock(void)   { xSemaphoreTake(s_sim.mtx, portMAX_DELAY); }
static void sim_unlock(void) { xSemaphoreGive(s_sim.mtx); }

/* Produce a believable-looking hash for share dumps: SHA256(seed || nonce).
 * This is NOT consensus-valid — `meets_network_target` is always false for
 * sim shares. The pool will reject them (or treat as invalid), which is
 * exactly what we want during bring-up so we don't accidentally claim
 * real block credit. */
static void sim_fake_hash(const uint8_t seed[32], uint32_t nonce, uint8_t out[32])
{
    mbedtls_sha256_context c;
    mbedtls_sha256_init(&c);
    mbedtls_sha256_starts(&c, 0);
    mbedtls_sha256_update(&c, seed, 32);
    uint8_t nb[4] = {
        (uint8_t)(nonce       ),
        (uint8_t)(nonce >>  8 ),
        (uint8_t)(nonce >> 16 ),
        (uint8_t)(nonce >> 24 ),
    };
    mbedtls_sha256_update(&c, nb, 4);
    mbedtls_sha256_finish(&c, out);
    mbedtls_sha256_free(&c);
}

/* ---- Periodic tick task ---------------------------------------------- *
 * THE LOOP: advances hash_count, latches a share at the configured cadence.
 */
static void sim_tick_task(void *arg)
{
    (void)arg;
    /* hashes_per_tick = (kH/s × 1000) × (tick_ms / 1000) */
    const uint64_t hashes_per_tick =
        (uint64_t)SIM_KHS * 1000ULL * (uint64_t)SIM_TICK_MS / 1000ULL;

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(SIM_TICK_MS));

        sim_lock();
        if (s_sim.state != SIM_RUNNING) {
            sim_unlock();
            continue;
        }

        /* Advance hashes */
        s_sim.hash_count += (uint32_t)hashes_per_tick;
        s_sim.hashes_total += hashes_per_tick;
        s_sim.nonce_cursor += (uint32_t)hashes_per_tick;
        if (s_sim.nonce_cursor >= s_sim.nonce_end) {
            /* Batch complete — fpga_worker will issue a new submit_job */
            s_sim.state = SIM_IDLE;
            sim_unlock();
            continue;
        }

        /* Time-based share generation */
        int64_t now = esp_timer_get_time();
        if (!s_sim.share_valid &&
            (now - s_sim.last_share_us) >= (int64_t)SIM_SHARE_INTERVAL_MS * 1000) {

            uint32_t nonce = s_sim.nonce_start +
                             (uint32_t)(esp_random() %
                                        (s_sim.nonce_cursor - s_sim.nonce_start + 1));

            s_sim.pending_share.nonce = nonce;
            s_sim.pending_share.ntime = (uint32_t)(now / 1000000) + 1715000000u;
            s_sim.pending_share.job_epoch = s_sim.job_epoch;
            sim_fake_hash(s_sim.seed, nonce, s_sim.pending_share.pow_hash_le);

            s_sim.share_valid = true;
            s_sim.state = SIM_SHARE_LATCHED;
            s_sim.last_share_us = now;
            ESP_LOGI(TAG, "share latched: nonce=0x%08" PRIx32 " epoch=%" PRIu32,
                     nonce, s_sim.job_epoch);
        }
        sim_unlock();
    }
}

/* ---- Public API (matches b3_fpga.h) ---------------------------------- */

esp_err_t b3_fpga_init(int irq_gpio)
{
    memset(&s_sim, 0, sizeof(s_sim));
    s_sim.mtx = xSemaphoreCreateMutex();
    s_sim.irq_gpio = irq_gpio;
    s_sim.state = SIM_IDLE;
    s_sim.last_share_us = esp_timer_get_time();

    ESP_LOGI(TAG, "FPGA simulator armed (sim_khs=%d share_every=%d ms)",
             SIM_KHS, SIM_SHARE_INTERVAL_MS);

    xTaskCreate(sim_tick_task, "fpga_sim", 4096, NULL, 4, NULL);
    return ESP_OK;
}

esp_err_t b3_fpga_load_bitstream_from_flash(void)
{
    /* Sim has no bitstream — pretend it's loaded. */
    return ESP_OK;
}

esp_err_t b3_fpga_init_scratchpad(const uint8_t prev_hash[32])
{
    if (!prev_hash) return ESP_ERR_INVALID_ARG;
    sim_lock();
    memcpy(s_sim.prev_block_hash, prev_hash, 32);
    s_sim.state = SIM_SCRATCH_INIT;
    sim_unlock();
    /* In real hardware this takes ~5-10 ms (32k BLAKE3 chunks); fake it
     * so timing-sensitive tests still see realistic latency. */
    vTaskDelay(pdMS_TO_TICKS(5));
    sim_lock();
    s_sim.state = SIM_IDLE;
    sim_unlock();
    return ESP_OK;
}

esp_err_t b3_fpga_submit_job(const b3_fpga_job_t *job)
{
    if (!job) return ESP_ERR_INVALID_ARG;
    sim_lock();
    memcpy(s_sim.seed, job->seed, 32);
    memcpy(s_sim.prev_block_hash, job->prev_block_hash, 32);
    s_sim.job_epoch = job->job_epoch;
    s_sim.nonce_start = job->nonce_start;
    s_sim.nonce_end = job->nonce_end;
    s_sim.nonce_cursor = job->nonce_start;
    s_sim.hash_count = 0;
    s_sim.job_start_us = esp_timer_get_time();
    s_sim.share_valid = false;
    s_sim.state = SIM_RUNNING;
    sim_unlock();
    ESP_LOGI(TAG, "job submitted: epoch=%" PRIu32 " nonces=[0x%08" PRIx32 ",0x%08" PRIx32 ")",
             job->job_epoch, job->nonce_start, job->nonce_end);
    return ESP_OK;
}

bool b3_fpga_poll_share(b3_fpga_share_t *out)
{
    bool got = false;
    sim_lock();
    if (s_sim.share_valid) {
        if (out) *out = s_sim.pending_share;
        s_sim.share_valid = false;
        if (s_sim.state == SIM_SHARE_LATCHED) {
            s_sim.state = SIM_RUNNING;
        }
        got = true;
    }
    sim_unlock();
    return got;
}

uint32_t b3_fpga_read_hash_count(void)
{
    uint32_t v;
    sim_lock();
    v = s_sim.hash_count;
    sim_unlock();
    return v;
}

float b3_fpga_read_die_celsius(void)
{
    /* Plausible idle / loaded curve for a KU5P: ~42 C cold + state-dependent rise */
    sim_lock();
    bool running = (s_sim.state == SIM_RUNNING || s_sim.state == SIM_SHARE_LATCHED);
    sim_unlock();
    return running ? 58.0f : 42.0f;
}
