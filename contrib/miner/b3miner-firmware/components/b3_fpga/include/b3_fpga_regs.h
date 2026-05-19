#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

/**
 * FPGA control register map (SPI, 32-bit aligned).
 * All multi-byte fields little-endian on wire.
 */
#define B3_FPGA_REG_ID           0x00  /* RO: 0xB3110002 (B3PoW-Scratch v1.1.1 build 0002, F-1 fix) */
#define B3_FPGA_REG_STATUS       0x04  /* RO: bit0 busy, bit1 share_valid, bit2 scratch_ready */
#define B3_FPGA_REG_CTRL         0x08  /* WO: bit0 start_job, bit1 abort, bit2 scratch_init */
#define B3_FPGA_REG_IRQ_MASK     0x0C
#define B3_FPGA_REG_NONCE_LO     0x10  /* last found nonce */
#define B3_FPGA_REG_NONCE_HI     0x14
#define B3_FPGA_REG_NTIME        0x18
#define B3_FPGA_REG_JOB_EPOCH    0x1C  /* host increments on each new job */
#define B3_FPGA_REG_HASH_COUNT   0x20  /* RO: hashes since job start (low 32) */
#define B3_FPGA_REG_TEMP_RAW     0x24  /* RO: XADC die temp */
#define B3_FPGA_REG_SEED         0x40  /* WO: 256-bit BLAKE3(header) seed, 8×32-bit writes */
#define B3_FPGA_REG_PREV_HASH    0x60  /* WO: 256-bit prev block hash for scratchpad init */
#define B3_FPGA_REG_NONCE_START  0x80  /* WO: nonce range start */
#define B3_FPGA_REG_NONCE_END    0x84  /* WO: nonce range end (exclusive) */
#define B3_FPGA_REG_POW_HASH     0x100 /* RO: 256-bit pow hash when share_valid */

#define B3_FPGA_MAGIC            0xB3110002u
#define B3_FPGA_STATUS_BUSY      (1u << 0)
#define B3_FPGA_STATUS_SHARE     (1u << 1)
#define B3_FPGA_STATUS_SCRATCH   (1u << 2)

typedef struct {
    uint32_t nonce;
    uint32_t ntime;
    uint32_t job_epoch;
    uint8_t  pow_hash_le[32];
} b3_fpga_share_t;

typedef struct {
    uint8_t  seed[32];
    uint8_t  prev_block_hash[32];
    uint32_t nonce_start;
    uint32_t nonce_end;
    uint32_t job_epoch;
} b3_fpga_job_t;

esp_err_t b3_fpga_init(int irq_gpio);
esp_err_t b3_fpga_load_bitstream_from_flash(void);  /* FILL IN: SelectMAP */
esp_err_t b3_fpga_submit_job(const b3_fpga_job_t *job);
esp_err_t b3_fpga_init_scratchpad(const uint8_t prev_hash[32]);
bool b3_fpga_poll_share(b3_fpga_share_t *out);
uint32_t b3_fpga_read_hash_count(void);
float b3_fpga_read_die_celsius(void);
void b3_fpga_worker_start(void);
