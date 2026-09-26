#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef int ATCA_STATUS;
#define ATCA_SUCCESS 0
#define LOCK_ZONE_CONFIG 0

typedef struct {
    int dummy;
} ATCAIfaceCfg;

void atca_host_reset(void);
void atca_host_set_missing(int missing);
void atca_host_set_locked(int locked);
int atca_host_serial_reads(void);

ATCA_STATUS atcab_init(ATCAIfaceCfg *cfg);
ATCA_STATUS atcab_info(uint8_t *revision);
ATCA_STATUS atcab_read_serial_number(uint8_t *serial_number);
ATCA_STATUS atcab_is_locked(uint8_t zone, bool *is_locked);
ATCA_STATUS atcab_sign(uint16_t key_id, const uint8_t *msg, uint8_t *signature);
ATCA_STATUS atcab_verify_extern(const uint8_t *message, const uint8_t *signature,
                                const uint8_t *public_key, bool *is_verified);
ATCA_STATUS atcab_random(uint8_t *rand_out);
ATCA_STATUS atcab_aes_encrypt(uint16_t key_id, uint8_t key_block,
                              const uint8_t *plaintext, uint8_t *ciphertext);
ATCA_STATUS atcab_aes_decrypt(uint16_t key_id, uint8_t key_block,
                              const uint8_t *ciphertext, uint8_t *plaintext);
ATCA_STATUS atcab_get_pubkey(uint16_t key_id, uint8_t *public_key);
ATCA_STATUS atcab_read_pubkey(uint16_t slot, uint8_t *public_key);
