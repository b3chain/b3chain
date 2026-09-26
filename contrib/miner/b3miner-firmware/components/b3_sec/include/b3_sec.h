#pragma once

#ifdef B3_SEC_HOST_TEST
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_INVALID_SIZE 0x104
#else
#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#endif

/**
 * ATECC608B wrapper. Slot 0 is the per-card P-256 key. The private key
 * stays in the chip; callers only pass a 32-byte message and receive a
 * 64-byte R||S signature.
 */

esp_err_t b3_sec_init(int sda_gpio, int scl_gpio);
esp_err_t b3_sec_serial(uint8_t sn[9]);
bool b3_sec_present(void);
/** Reads the Configuration Zone lock byte. Does not lock anything. */
bool b3_sec_provisioned(void);
/** True only when CONFIG_B3_SEC_REQUIRE_PROVISIONED is on and the chip is not locked. */
bool b3_sec_mining_blocked(void);
/** Non-NULL when mining is blocked: "Card unprovisioned — run factory fixture". */
const char *b3_sec_status_text(void);

esp_err_t b3_sec_sign_p256(uint16_t slot, const uint8_t msg32[32], uint8_t sig64[64]);
esp_err_t b3_sec_verify_p256(const uint8_t pub64[64], const uint8_t msg32[32], const uint8_t sig64[64]);
esp_err_t b3_sec_random(uint8_t *buf, size_t len);
esp_err_t b3_sec_aes_encrypt_block(uint16_t slot, const uint8_t in16[16], uint8_t out16[16]);
esp_err_t b3_sec_aes_decrypt_block(uint16_t slot, const uint8_t in16[16], uint8_t out16[16]);
esp_err_t b3_sec_pubkey(uint16_t slot, uint8_t pub64[64]);
esp_err_t b3_sec_slot2_pubkey(uint8_t pub64[64]);
/** Personalize mbedTLS CTR-DRBG from atcab_random. No-op success path when the chip is absent. */
esp_err_t b3_sec_seed_drbg(void);

#ifdef B3_SEC_HOST_TEST
void b3_sec_test_reset(void);
void b3_sec_test_set_require(int on);
#endif
