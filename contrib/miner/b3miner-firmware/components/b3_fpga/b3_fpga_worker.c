/**
 * @file b3_fpga_worker.c
 * @brief THE LOOP: wait for jobs → push to FPGA → collect shares → stratum queue.
 */

#include "b3_fpga.h"

#include "b3_events.h"
#include "b3_metrics.h"
#include "b3_work.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "fpga_worker";

static void fpga_worker_task(void *arg)
{
    (void)arg;
    b3_work_job_t work;
    uint32_t nonce_cursor = 0;

    for (;;) {
        if (!b3_work_wait_job(&work, pdMS_TO_TICKS(1000))) {
            continue;
        }

        ESP_LOGI(TAG, "New job epoch=%" PRIu32 " job_id=%s", work.epoch, work.job_id);

        /* Step 1: scratchpad regen once per block (B3PoW-Scratch).
         *
         * Always required on every b3chain network -- mainnet, testnet,
         * testnet4, and regtest all run B3PoW-Scratch v1.1.1 from
         * genesis (see contrib/miner/b3miner-rtl/SPEC.md §1).  The
         * old CONFIG_B3_POW_LEGACY_DOUBLE_BLAKE3 opt-out was removed
         * once the chain-ID rolled to B3PoW-Scratch at launch. */
        esp_err_t err = b3_fpga_init_scratchpad(work.prev_block_hash);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "scratchpad init failed");
            continue;
        }

        b3_fpga_job_t fj = {0};
        memcpy(fj.seed, work.pow_seed, 32);
        memcpy(fj.prev_block_hash, work.prev_block_hash, 32);
        fj.job_epoch = work.epoch;
        fj.nonce_start = nonce_cursor;
        fj.nonce_end = nonce_cursor + work.nonce_batch_size;

        b3_fpga_submit_job(&fj);

        uint32_t t0_hashes = b3_fpga_read_hash_count();
        int64_t t0_us = esp_timer_get_time();

        for (;;) {
            b3_fpga_share_t sh;
            if (b3_fpga_poll_share(&sh)) {
                b3_share_event_t ev = {
                    .job_epoch = sh.job_epoch,
                    .nonce = sh.nonce,
                    .ntime = sh.ntime,
                    .extranonce2 = {0}, /* FILL IN from work slice */
                };
                memcpy(ev.pow_hash_le, sh.pow_hash_le, 32);
                ev.meets_network_target = false; /* FILL IN: compare to network target */
                xQueueSend(b3_events_share_queue(), &ev, 0);
                /* Stratum task drains b3_events_share_queue() */
            }

            if (b3_work_job_stale(work.epoch)) {
                ESP_LOGW(TAG, "Job stale, aborting FPGA batch");
                break;
            }

            uint32_t now = b3_fpga_read_hash_count();
            if (now - fj.nonce_start >= work.nonce_batch_size) {
                nonce_cursor = fj.nonce_end;
                if (nonce_cursor == 0) {
                    nonce_cursor = 0; /* wrapped */
                }
                break;
            }

            vTaskDelay(pdMS_TO_TICKS(1));
        }

        uint32_t t1_hashes = b3_fpga_read_hash_count();
        int64_t dt_us = esp_timer_get_time() - t0_us;
        if (dt_us > 0) {
            float khs = (float)(t1_hashes - t0_hashes) * 1000.0f / (float)dt_us;
            b3_metrics_report_hashrate(khs);
        }
    }
}

void b3_fpga_worker_start(void)
{
    xTaskCreatePinnedToCore(fpga_worker_task, "fpga_worker", 8192, NULL, 9, NULL, 1);
}
