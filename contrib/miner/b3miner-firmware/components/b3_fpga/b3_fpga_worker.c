/**
 * @file b3_fpga_worker.c
 * @brief THE LOOP: wait for jobs → push to FPGA → collect shares → stratum queue.
 */

#include "b3_fpga.h"

#include <string.h>

#include "b3_events.h"
#include "b3_metrics.h"
#include "b3_work.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "fpga_worker";

static void reverse_32(const uint8_t in[32], uint8_t out[32])
{
    for (int i = 0; i < 32; ++i) out[i] = in[31 - i];
}

static void fpga_worker_task(void *arg)
{
    (void)arg;
    static b3_work_job_t work;

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
        uint8_t prev_le[32];
        reverse_32(work.prev_block_hash, prev_le);
        esp_err_t err = b3_fpga_init_scratchpad(prev_le);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "scratchpad init failed");
            continue;
        }

        uint8_t extranonce2[32] = {0};
        uint32_t nonce_cursor = 0;
        while (!b3_work_job_stale(work.epoch)) {
            uint8_t header[80];
            err = b3_work_build_header(
                &work, extranonce2, work.extranonce2_size,
                work.ntime, 0, header);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "header build failed: %s", esp_err_to_name(err));
                break;
            }

            b3_fpga_job_t fj = {0};
            memcpy(fj.header_prefix, header, sizeof(fj.header_prefix));
            memcpy(fj.prev_block_hash, prev_le, sizeof(fj.prev_block_hash));
            reverse_32(work.share_target_be, fj.share_target_le);
            fj.job_epoch = work.epoch;
            fj.nonce_start = nonce_cursor;
            const uint64_t remaining_nonce_space =
                0x100000000ULL - (uint64_t)nonce_cursor;
            fj.nonce_count = work.nonce_batch_size < remaining_nonce_space
                ? work.nonce_batch_size : (uint32_t)remaining_nonce_space;
            fj.nonce_end = nonce_cursor + fj.nonce_count;

            err = b3_fpga_submit_job(&fj);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "job submit failed: %s", esp_err_to_name(err));
                break;
            }
            const int64_t t0_us = esp_timer_get_time();
            bool completion_seen = false;
            bool batch_failed = false;

            for (;;) {
                b3_fpga_share_t sh;
                if (b3_fpga_poll_share(&sh)) {
                    b3_share_event_t ev = {
                        .job_epoch = work.epoch,
                        .nonce = sh.nonce,
                        .ntime = work.ntime,
                        .extranonce2 = {0},
                        .extranonce2_len = (uint8_t)work.extranonce2_size,
                    };
                    memcpy(ev.extranonce2, extranonce2, work.extranonce2_size);
                    memcpy(ev.pow_hash_le, sh.pow_hash_le, 32);
                    int meets_share = b3_work_hash_meets_target(
                        sh.pow_hash_le, work.share_target_be);
                    int meets_network = b3_work_hash_meets_target(
                        sh.pow_hash_le, work.network_target_be);
                    if (!meets_share && !meets_network) {
                        ESP_LOGE(TAG, "FPGA candidate missed share and network targets");
                        if (b3_fpga_ack_share() != ESP_OK) {
                            b3_fpga_abort_job();
                            batch_failed = true;
                            break;
                        }
                        continue;
                    }
                    ev.meets_network_target = meets_network;
                    if (xQueueSend(b3_events_share_queue(), &ev, 0) == pdTRUE) {
                        if (b3_fpga_ack_share() != ESP_OK) {
                            ESP_LOGE(TAG, "share ACK failed; aborting batch");
                            b3_fpga_abort_job();
                            batch_failed = true;
                            break;
                        }
                    } else {
                        ESP_LOGW(TAG, "share queue full; leaving FPGA share pending");
                        vTaskDelay(pdMS_TO_TICKS(1));
                        continue;
                    }
                }

                if (b3_work_job_stale(work.epoch)) {
                    ESP_LOGW(TAG, "Job stale, aborting FPGA batch");
                    b3_fpga_abort_job();
                    break;
                }

                const uint32_t hashes = b3_fpga_read_hash_count();
                b3_metrics_note_fpga_count(hashes, work.epoch, 0);
                if (hashes >= fj.nonce_count) {
                    if (!completion_seen) {
                        completion_seen = true;
                        vTaskDelay(pdMS_TO_TICKS(1));
                        continue;
                    }
                    const int64_t dt_us = esp_timer_get_time() - t0_us;
                    if (dt_us > 0) {
                        const float khs = (float)hashes * 1000.0f / (float)dt_us;
                        b3_metrics_report_hashrate(khs);
                        b3_metrics_note_fpga_count(hashes, work.epoch, 1);
                    }
                    break;
                }
                completion_seen = false;
                vTaskDelay(pdMS_TO_TICKS(1));
            }

            if (batch_failed) break;
            if (b3_work_job_stale(work.epoch)) break;
            if ((uint64_t)fj.nonce_count == remaining_nonce_space) {
                nonce_cursor = 0;
                size_t byte = 0;
                while (byte < work.extranonce2_size && ++extranonce2[byte] == 0)
                    byte++;
                if (byte == work.extranonce2_size) {
                    ESP_LOGW(TAG, "extranonce2 space exhausted");
                    break;
                }
            } else {
                nonce_cursor += fj.nonce_count;
            }
        }
    }
}

void b3_fpga_worker_start(void)
{
    xTaskCreatePinnedToCore(fpga_worker_task, "fpga_worker", 16384, NULL, 9, NULL, 1);
}
