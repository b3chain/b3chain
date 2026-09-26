/**
 * Host stand-in for the cryptoauthlib emulator. Sign and verify share one
 * deterministic MAC so the wrapper can round-trip without a chip. AES is
 * XOR with the slot key so encrypt and decrypt invert.
 */
#include "atca_host.h"

#include <string.h>

static int s_missing;
static int s_locked;
static int s_serial_reads;
static uint32_t s_rand;
static uint8_t s_priv[32];
static uint8_t s_pub[64];
static uint8_t s_aes[16];
static uint8_t s_slot2[64];

static void mix(uint8_t out[32], const uint8_t *a, size_t a_len, const uint8_t *b, size_t b_len)
{
    uint8_t acc[32];
    memset(acc, 0x5a, sizeof(acc));
    for (size_t i = 0; i < a_len; i++) {
        acc[i % 32] = (uint8_t)(acc[i % 32] + a[i] + (uint8_t)i);
    }
    for (size_t i = 0; i < b_len; i++) {
        acc[i % 32] ^= (uint8_t)(b[i] + (uint8_t)(i * 3));
    }
    for (int r = 0; r < 4; r++) {
        for (int i = 0; i < 32; i++) {
            acc[i] = (uint8_t)(acc[i] * 33 + acc[(i + 7) % 32] + r);
        }
    }
    memcpy(out, acc, 32);
}

void atca_host_reset(void)
{
    s_missing = 0;
    s_locked = 1;
    s_serial_reads = 0;
    s_rand = 1;
    for (int i = 0; i < 32; i++) {
        s_priv[i] = (uint8_t)(0x10 + i);
    }
    mix(s_pub, s_priv, 32, (const uint8_t *)"pub", 3);
    mix(s_pub + 32, s_priv, 32, (const uint8_t *)"PUB", 3);
    for (int i = 0; i < 16; i++) {
        s_aes[i] = (uint8_t)(0xA0 + i);
    }
    memset(s_slot2, 0x22, sizeof(s_slot2));
}

void atca_host_set_missing(int missing)
{
    s_missing = missing ? 1 : 0;
}

void atca_host_set_locked(int locked)
{
    s_locked = locked ? 1 : 0;
}

int atca_host_serial_reads(void)
{
    return s_serial_reads;
}

ATCA_STATUS atcab_init(ATCAIfaceCfg *cfg)
{
    (void)cfg;
    return s_missing ? -1 : ATCA_SUCCESS;
}

ATCA_STATUS atcab_info(uint8_t *revision)
{
    if (s_missing || !revision) {
        return -1;
    }
    revision[0] = 0x00;
    revision[1] = 0x00;
    revision[2] = 0x60;
    revision[3] = 0x02;
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_read_serial_number(uint8_t *serial_number)
{
    if (s_missing || !serial_number) {
        return -1;
    }
    s_serial_reads++;
    const uint8_t sn[9] = {0x01, 0x23, 0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66};
    memcpy(serial_number, sn, 9);
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_is_locked(uint8_t zone, bool *is_locked)
{
    (void)zone;
    if (s_missing || !is_locked) {
        return -1;
    }
    *is_locked = s_locked ? true : false;
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_sign(uint16_t key_id, const uint8_t *msg, uint8_t *signature)
{
    if (s_missing || key_id != 0 || !msg || !signature) {
        return -1;
    }
    mix(signature, s_priv, 32, msg, 32);
    mix(signature + 32, msg, 32, s_priv, 32);
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_verify_extern(const uint8_t *message, const uint8_t *signature,
                                const uint8_t *public_key, bool *is_verified)
{
    if (s_missing || !message || !signature || !public_key || !is_verified) {
        return -1;
    }
    if (memcmp(public_key, s_pub, 64) != 0) {
        *is_verified = false;
        return ATCA_SUCCESS;
    }
    uint8_t expect[64];
    mix(expect, s_priv, 32, message, 32);
    mix(expect + 32, message, 32, s_priv, 32);
    *is_verified = memcmp(expect, signature, 64) == 0;
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_random(uint8_t *rand_out)
{
    if (s_missing || !rand_out) {
        return -1;
    }
    for (int i = 0; i < 32; i++) {
        s_rand = s_rand * 1664525u + 1013904223u;
        rand_out[i] = (uint8_t)(s_rand >> 16);
    }
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_aes_encrypt(uint16_t key_id, uint8_t key_block,
                              const uint8_t *plaintext, uint8_t *ciphertext)
{
    (void)key_block;
    if (s_missing || key_id != 3 || !plaintext || !ciphertext) {
        return -1;
    }
    for (int i = 0; i < 16; i++) {
        ciphertext[i] = (uint8_t)(plaintext[i] ^ s_aes[i]);
    }
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_aes_decrypt(uint16_t key_id, uint8_t key_block,
                              const uint8_t *ciphertext, uint8_t *plaintext)
{
    return atcab_aes_encrypt(key_id, key_block, ciphertext, plaintext);
}

ATCA_STATUS atcab_get_pubkey(uint16_t key_id, uint8_t *public_key)
{
    if (s_missing || key_id != 0 || !public_key) {
        return -1;
    }
    memcpy(public_key, s_pub, 64);
    return ATCA_SUCCESS;
}

ATCA_STATUS atcab_read_pubkey(uint16_t slot, uint8_t *public_key)
{
    if (s_missing || slot != 2 || !public_key) {
        return -1;
    }
    memcpy(public_key, s_slot2, 64);
    return ATCA_SUCCESS;
}
