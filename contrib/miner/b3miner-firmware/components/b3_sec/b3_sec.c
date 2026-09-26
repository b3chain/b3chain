/**
 * ATECC608B-MAHDA-T on I2C_NUM_0. GPIO 1 is SDA and GPIO 2 is SCL.
 * Firmware never generates keys, writes slots, or locks a zone.
 */
#include "b3_sec.h"

#include <string.h>

#ifdef B3_SEC_HOST_TEST
#include <stdio.h>
#include "atca_host.h"
#define ESP_LOGI(tag, fmt, ...) printf("I (%s) " fmt "\n", tag, ##__VA_ARGS__)
#define ESP_LOGW(tag, fmt, ...) printf("W (%s) " fmt "\n", tag, ##__VA_ARGS__)
#define ESP_LOGE(tag, fmt, ...) printf("E (%s) " fmt "\n", tag, ##__VA_ARGS__)
#else
#include "cryptoauthlib.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_random.h"
#include "mbedtls/private/ctr_drbg.h"
#endif

#ifndef CONFIG_B3_SEC_REQUIRE_PROVISIONED
#define CONFIG_B3_SEC_REQUIRE_PROVISIONED 0
#endif

static const char *TAG = "b3_sec";
static const char *UNPROVISIONED = "Card unprovisioned — run factory fixture";

static bool s_present;
static bool s_serial_cached;
static uint8_t s_serial[9];
static bool s_slot2_valid;
static uint8_t s_slot2[64];
static int s_require_override = -1;

#ifndef B3_SEC_HOST_TEST
static i2c_master_bus_handle_t s_i2c_bus;
static mbedtls_ctr_drbg_context s_drbg;
static bool s_drbg_ready;

static int hw_entropy(void *ctx, unsigned char *out, size_t len)
{
    (void)ctx;
    esp_fill_random(out, len);
    return 0;
}
#endif

#ifdef B3_SEC_HOST_TEST
void b3_sec_test_reset(void)
{
    s_present = false;
    s_serial_cached = false;
    s_slot2_valid = false;
    s_require_override = -1;
    memset(s_serial, 0, sizeof(s_serial));
    memset(s_slot2, 0, sizeof(s_slot2));
    atca_host_reset();
}

void b3_sec_test_set_require(int on)
{
    s_require_override = on ? 1 : 0;
}
#endif

static int require_provisioned(void)
{
    if (s_require_override >= 0) {
        return s_require_override;
    }
    return CONFIG_B3_SEC_REQUIRE_PROVISIONED ? 1 : 0;
}

bool b3_sec_present(void)
{
    return s_present;
}

bool b3_sec_provisioned(void)
{
    if (!s_present) {
        return false;
    }
    bool locked = false;
    if (atcab_is_locked(LOCK_ZONE_CONFIG, &locked) != ATCA_SUCCESS) {
        return false;
    }
    return locked;
}

bool b3_sec_mining_blocked(void)
{
    return require_provisioned() && !b3_sec_provisioned();
}

const char *b3_sec_status_text(void)
{
    return b3_sec_mining_blocked() ? UNPROVISIONED : NULL;
}

esp_err_t b3_sec_serial(uint8_t sn[9])
{
    if (!sn) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!s_present) {
        return ESP_FAIL;
    }
    if (!s_serial_cached) {
        if (atcab_read_serial_number(s_serial) != ATCA_SUCCESS) {
            return ESP_FAIL;
        }
        s_serial_cached = true;
    }
    memcpy(sn, s_serial, 9);
    return ESP_OK;
}

static void cache_slot2(void)
{
    s_slot2_valid = false;
    if (!b3_sec_provisioned()) {
        return;
    }
    if (atcab_read_pubkey(2, s_slot2) == ATCA_SUCCESS) {
        s_slot2_valid = true;
    }
}

esp_err_t b3_sec_init(int sda_gpio, int scl_gpio)
{
    s_present = false;
    s_serial_cached = false;
    s_slot2_valid = false;

#ifndef B3_SEC_HOST_TEST
    if (sda_gpio < 0 || scl_gpio < 0) {
        ESP_LOGE(TAG, "bad i2c pins");
        return ESP_ERR_INVALID_ARG;
    }
    i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = sda_gpio,
        .scl_io_num = scl_gpio,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = 1,
    };
    esp_err_t ierr = i2c_new_master_bus(&bus, &s_i2c_bus);
    if (ierr != ESP_OK && ierr != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "i2c bus: %s", esp_err_to_name(ierr));
        s_i2c_bus = NULL;
    }

    ATCAIfaceCfg cfg = cfg_ateccx08a_i2c_default;
    cfg.devtype = ATECC608;
    ATCA_IFACECFG_VALUE(&cfg, atcai2c.bus) = I2C_NUM_0;
    ATCA_IFACECFG_I2C_BAUD(&cfg) = 400000;
    ATCA_IFACECFG_I2C_ADDRESS(&cfg) = 0xC0;
    ATCA_STATUS st = atcab_init(&cfg);
    if (st != ATCA_SUCCESS && s_i2c_bus) {
        i2c_del_master_bus(s_i2c_bus);
        s_i2c_bus = NULL;
        st = atcab_init(&cfg);
    }
#else
    (void)sda_gpio;
    (void)scl_gpio;
    ATCAIfaceCfg cfg;
    memset(&cfg, 0, sizeof(cfg));
    ATCA_STATUS st = atcab_init(&cfg);
#endif

    if (st != ATCA_SUCCESS) {
        ESP_LOGE(TAG, "atcab_init failed (%d)", (int)st);
        return ESP_FAIL;
    }

    uint8_t revision[4] = {0};
    st = atcab_info(revision);
    if (st != ATCA_SUCCESS) {
        ESP_LOGE(TAG, "atcab_info failed (%d)", (int)st);
        return ESP_FAIL;
    }

    s_present = true;
    uint8_t sn[9];
    if (b3_sec_serial(sn) == ESP_OK) {
        ESP_LOGI(TAG, "ATECC608B serial %02x%02x%02x%02x%02x%02x%02x%02x%02x",
                 sn[0], sn[1], sn[2], sn[3], sn[4], sn[5], sn[6], sn[7], sn[8]);
    }
    if (!b3_sec_provisioned()) {
        ESP_LOGW(TAG, "Card unprovisioned");
    }
    cache_slot2();
    return ESP_OK;
}

esp_err_t b3_sec_sign_p256(uint16_t slot, const uint8_t msg32[32], uint8_t sig64[64])
{
    if (!s_present || !msg32 || !sig64) {
        return ESP_ERR_INVALID_ARG;
    }
    if (atcab_sign(slot, msg32, sig64) != ATCA_SUCCESS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}

esp_err_t b3_sec_verify_p256(const uint8_t pub64[64], const uint8_t msg32[32], const uint8_t sig64[64])
{
    if (!s_present || !pub64 || !msg32 || !sig64) {
        return ESP_ERR_INVALID_ARG;
    }
    bool verified = false;
    if (atcab_verify_extern(msg32, sig64, pub64, &verified) != ATCA_SUCCESS) {
        return ESP_FAIL;
    }
    return verified ? ESP_OK : ESP_FAIL;
}

esp_err_t b3_sec_random(uint8_t *buf, size_t len)
{
    if (!s_present || !buf) {
        return ESP_ERR_INVALID_ARG;
    }
    size_t off = 0;
    while (off < len) {
        uint8_t block[32];
        if (atcab_random(block) != ATCA_SUCCESS) {
            return ESP_FAIL;
        }
        size_t n = len - off;
        if (n > sizeof(block)) {
            n = sizeof(block);
        }
        memcpy(buf + off, block, n);
        off += n;
    }
    return ESP_OK;
}

esp_err_t b3_sec_aes_encrypt_block(uint16_t slot, const uint8_t in16[16], uint8_t out16[16])
{
    if (!s_present || !in16 || !out16) {
        return ESP_ERR_INVALID_ARG;
    }
    if (atcab_aes_encrypt(slot, 0, in16, out16) != ATCA_SUCCESS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}

esp_err_t b3_sec_aes_decrypt_block(uint16_t slot, const uint8_t in16[16], uint8_t out16[16])
{
    if (!s_present || !in16 || !out16) {
        return ESP_ERR_INVALID_ARG;
    }
    if (atcab_aes_decrypt(slot, 0, in16, out16) != ATCA_SUCCESS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}

esp_err_t b3_sec_pubkey(uint16_t slot, uint8_t pub64[64])
{
    if (!s_present || !pub64) {
        return ESP_ERR_INVALID_ARG;
    }
    if (atcab_get_pubkey(slot, pub64) != ATCA_SUCCESS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}

esp_err_t b3_sec_slot2_pubkey(uint8_t pub64[64])
{
    if (!pub64 || !s_slot2_valid) {
        return ESP_FAIL;
    }
    memcpy(pub64, s_slot2, 64);
    return ESP_OK;
}

esp_err_t b3_sec_seed_drbg(void)
{
    if (!s_present) {
        return ESP_FAIL;
    }
    uint8_t seed[48];
    if (b3_sec_random(seed, sizeof(seed)) != ESP_OK) {
        return ESP_FAIL;
    }
#ifdef B3_SEC_HOST_TEST
    (void)seed;
    return ESP_OK;
#else
    if (s_drbg_ready) {
        return ESP_OK;
    }
    mbedtls_ctr_drbg_init(&s_drbg);
    int rc = mbedtls_ctr_drbg_seed(&s_drbg, hw_entropy, NULL, seed, sizeof(seed));
    if (rc != 0) {
        ESP_LOGW(TAG, "ctr_drbg seed failed (%d)", rc);
        return ESP_FAIL;
    }
    s_drbg_ready = true;
    ESP_LOGI(TAG, "mbedTLS CTR-DRBG personalized from ATECC608B");
    return ESP_OK;
#endif
}
