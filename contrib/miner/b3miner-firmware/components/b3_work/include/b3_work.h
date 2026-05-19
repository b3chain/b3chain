#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"

#include "b3_hex.h"

#define B3_WORK_JOB_ID_MAX   32
#define B3_WORK_COINB1_MAX   512
#define B3_WORK_COINB2_MAX   512
#define B3_WORK_MERKLE_MAX   32

typedef struct {
    char     job_id[B3_WORK_JOB_ID_MAX];
    uint32_t epoch;
    uint32_t version;
    uint8_t  prev_block_hash[32];
    uint8_t  merkle_root[32];
    uint32_t nbits;
    uint32_t ntime;
    uint8_t  extranonce1[32];
    size_t   extranonce1_len;
    size_t   extranonce2_size;
    char     coinb1_hex[B3_WORK_COINB1_MAX];
    char     coinb2_hex[B3_WORK_COINB2_MAX];
    char     merkle_branch_hex[B3_WORK_MERKLE_MAX][66];
    size_t   merkle_branch_count;
    float    share_diff;
    uint8_t  share_target_be[32];
    uint8_t  network_target_be[32];
    uint8_t  pow_seed[32];          /* BLAKE3(header template) or scratch seed */
    uint32_t nonce_batch_size;      /* nonces per FPGA batch */
} b3_work_job_t;

void b3_work_init(void);
void b3_work_publish_job(const b3_work_job_t *job);
bool b3_work_wait_job(b3_work_job_t *out, TickType_t timeout);
bool b3_work_job_stale(uint32_t epoch);
esp_err_t b3_work_build_header(const b3_work_job_t *job, uint32_t extranonce2,
                               uint32_t ntime, uint32_t nonce,
                               uint8_t header_out[80]);
esp_err_t b3_work_build_pow_seed(const b3_work_job_t *job, uint32_t extranonce2,
                                 uint32_t ntime, uint8_t seed_out[32]);
