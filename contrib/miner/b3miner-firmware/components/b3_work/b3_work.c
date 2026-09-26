#include "b3_work.h"

#include <math.h>
#include <stdatomic.h>
#include <string.h>

#include "b3_crypto.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "psa/crypto.h"

static b3_work_job_t s_job;
static _Atomic uint32_t s_latest_epoch;
static SemaphoreHandle_t s_job_mtx;

static void put_u32_le(uint8_t out[4], uint32_t value)
{
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
    out[2] = (uint8_t)(value >> 16);
    out[3] = (uint8_t)(value >> 24);
}

static esp_err_t sha256d(const uint8_t *data, size_t len, uint8_t out[32])
{
    uint8_t first[32];
    size_t written = 0;
    if (psa_crypto_init() != PSA_SUCCESS ||
        psa_hash_compute(PSA_ALG_SHA_256, data, len, first, sizeof(first),
                         &written) != PSA_SUCCESS ||
        written != sizeof(first) ||
        psa_hash_compute(PSA_ALG_SHA_256, first, sizeof(first), out, 32,
                         &written) != PSA_SUCCESS ||
        written != 32) {
        return ESP_FAIL;
    }
    return ESP_OK;
}

static esp_err_t target_from_nbits(uint32_t nbits, uint8_t out_be[32])
{
    const uint32_t exp = nbits >> 24;
    uint32_t mant = nbits & 0x007FFFFFu;
    if ((nbits & 0x00800000u) != 0 || mant == 0 || exp > 32) {
        return ESP_ERR_INVALID_ARG;
    }
    uint32_t shift_bytes = 0;
    if (exp <= 3) {
        mant >>= 8 * (3 - exp);
    } else {
        shift_bytes = exp - 3;
    }
    memset(out_be, 0, 32);
    for (uint32_t i = 0; i < 3; ++i) {
        const uint32_t pos_from_lsb = shift_bytes + i;
        if (pos_from_lsb < 32)
            out_be[31 - pos_from_lsb] = (uint8_t)(mant >> (8 * i));
    }
    return ESP_OK;
}

static esp_err_t target_from_share_diff(double difficulty, uint8_t out_be[32])
{
    if (!(difficulty >= 0.000001) || !isfinite(difficulty)) {
        return ESP_ERR_INVALID_ARG;
    }
    uint64_t scaled_diff = (uint64_t)llround(difficulty * 1000000.0);
    if (scaled_diff == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    uint32_t limbs[8] = {0, 0, 0, 0, 0, 0, 0xFFFF0000u, 0};
    uint64_t carry = 0;
    for (int i = 0; i < 8; ++i) {
        const uint64_t product = (uint64_t)limbs[i] * 1000000u + carry;
        limbs[i] = (uint32_t)product;
        carry = product >> 32;
    }
    if (carry != 0) {
        return ESP_ERR_INVALID_ARG;
    }

    uint32_t quotient[8] = {0};
    uint64_t remainder = 0;
    for (int bit = 255; bit >= 0; --bit) {
        const uint32_t input_bit =
            (limbs[bit / 32] >> (bit % 32)) & 1u;
        const bool overflow = (remainder >> 63) != 0;
        remainder = (remainder << 1) | input_bit;
        if (overflow || remainder >= scaled_diff) {
            remainder -= scaled_diff;
            quotient[bit / 32] |= 1u << (bit % 32);
        }
    }
    memcpy(limbs, quotient, sizeof(limbs));
    for (int i = 0; i < 8; ++i) {
        const uint32_t word = limbs[7 - i];
        out_be[4*i + 0] = (uint8_t)(word >> 24);
        out_be[4*i + 1] = (uint8_t)(word >> 16);
        out_be[4*i + 2] = (uint8_t)(word >> 8);
        out_be[4*i + 3] = (uint8_t)word;
    }
    return ESP_OK;
}

void b3_work_init(void)
{
    s_job_mtx = xSemaphoreCreateMutex();
    atomic_store_explicit(&s_latest_epoch, 0, memory_order_release);
}

void b3_work_publish_job(const b3_work_job_t *job)
{
    xSemaphoreTake(s_job_mtx, portMAX_DELAY);
    s_job = *job;
    atomic_store_explicit(&s_latest_epoch, job->epoch, memory_order_release);
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
    return out->epoch != 0;
}

bool b3_work_job_stale(uint32_t epoch)
{
    return epoch != atomic_load_explicit(&s_latest_epoch, memory_order_acquire);
}

void b3_work_invalidate(void)
{
    xSemaphoreTake(s_job_mtx, portMAX_DELAY);
    uint32_t next = atomic_load_explicit(&s_latest_epoch, memory_order_relaxed) + 1;
    if (next == 0) next = 1;
    atomic_store_explicit(&s_latest_epoch, next, memory_order_release);
    s_job.epoch = 0;
    xSemaphoreGive(s_job_mtx);
}

void b3_work_update_difficulty(double share_diff, uint32_t epoch)
{
    xSemaphoreTake(s_job_mtx, portMAX_DELAY);
    if (s_job.epoch != 0) {
        uint8_t next_target[32];
        if (target_from_share_diff(share_diff, next_target) == ESP_OK) {
            s_job.share_diff = share_diff;
            memcpy(s_job.share_target_be, next_target, 32);
            s_job.epoch = epoch;
            atomic_store_explicit(&s_latest_epoch, epoch, memory_order_release);
        }
    }
    xSemaphoreGive(s_job_mtx);
}

esp_err_t b3_work_build_header(const b3_work_job_t *job,
                               const uint8_t *extranonce2, size_t extranonce2_len,
                               uint32_t ntime, uint32_t nonce,
                               uint8_t header_out[80])
{
    if (!job || !header_out) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!extranonce2 || extranonce2_len != job->extranonce2_size ||
        job->extranonce2_size == 0 || job->extranonce2_size > 32 ||
        job->extranonce1_len > sizeof(job->extranonce1)) {
        return ESP_ERR_INVALID_SIZE;
    }

    uint8_t coinb1[B3_WORK_COINB1_MAX / 2];
    uint8_t coinb2[B3_WORK_COINB2_MAX / 2];
    uint8_t coinbase[B3_WORK_COINB1_MAX / 2 + 32 + 32 + B3_WORK_COINB2_MAX / 2];
    size_t coinb1_len = 0, coinb2_len = 0, offset = 0;
    ESP_RETURN_ON_ERROR(
        b3_hex_decode_var(job->coinb1_hex, coinb1, sizeof(coinb1), &coinb1_len),
        "b3_work", "bad coinb1");
    ESP_RETURN_ON_ERROR(
        b3_hex_decode_var(job->coinb2_hex, coinb2, sizeof(coinb2), &coinb2_len),
        "b3_work", "bad coinb2");

    memcpy(coinbase + offset, coinb1, coinb1_len);
    offset += coinb1_len;
    memcpy(coinbase + offset, job->extranonce1, job->extranonce1_len);
    offset += job->extranonce1_len;
    memcpy(coinbase + offset, extranonce2, extranonce2_len);
    offset += extranonce2_len;
    memcpy(coinbase + offset, coinb2, coinb2_len);
    offset += coinb2_len;

    uint8_t merkle[32];
    ESP_RETURN_ON_ERROR(
        sha256d(coinbase, offset, merkle),
        "b3_work", "coinbase SHA256d failed");
    for (size_t i = 0; i < job->merkle_branch_count; ++i) {
        uint8_t branch_be[32], pair[64];
        ESP_RETURN_ON_ERROR(
            b3_hex_decode(job->merkle_branch_hex[i], branch_be, 32),
            "b3_work", "bad merkle branch");
        memcpy(pair, merkle, 32);
        for (int j = 0; j < 32; ++j) pair[32 + j] = branch_be[31 - j];
        ESP_RETURN_ON_ERROR(
            sha256d(pair, sizeof(pair), merkle),
            "b3_work", "merkle SHA256d failed");
    }

    put_u32_le(header_out + 0, job->version);
    for (int i = 0; i < 32; ++i)
        header_out[4 + i] = job->prev_block_hash[31 - i];
    memcpy(header_out + 36, merkle, 32);
    put_u32_le(header_out + 68, ntime);
    put_u32_le(header_out + 72, job->nbits);
    put_u32_le(header_out + 76, nonce);
    return ESP_OK;
}

esp_err_t b3_work_build_pow_seed(const b3_work_job_t *job,
                                 const uint8_t *extranonce2, size_t extranonce2_len,
                                 uint32_t ntime, uint8_t seed_out[32])
{
    uint8_t hdr[80];
    ESP_ERROR_CHECK(b3_work_build_header(
        job, extranonce2, extranonce2_len, ntime, 0, hdr));
    b3_blake3_hash(hdr, sizeof(hdr), seed_out);
    return ESP_OK;
}

esp_err_t b3_work_derive_targets(b3_work_job_t *job)
{
    if (!job) return ESP_ERR_INVALID_ARG;
    ESP_RETURN_ON_ERROR(
        target_from_nbits(job->nbits, job->network_target_be),
        "b3_work", "invalid nbits");
    ESP_RETURN_ON_ERROR(
        target_from_share_diff(job->share_diff, job->share_target_be),
        "b3_work", "invalid share difficulty");
    return ESP_OK;
}

bool b3_work_hash_meets_target(const uint8_t hash_le[32],
                               const uint8_t target_be[32])
{
    if (!hash_le || !target_be) return false;
    for (int i = 0; i < 32; ++i) {
        const uint8_t hash_be_byte = hash_le[31 - i];
        if (hash_be_byte < target_be[i]) return true;
        if (hash_be_byte > target_be[i]) return false;
    }
    return true;
}
