/**
 * Host tests for the b3_sec wrapper against the ATCA stand-in.
 * Build: gcc -std=c11 -Wall -Wextra -DB3_SEC_HOST_TEST -I../include -I. ../b3_sec.c atca_host.c test_b3_sec.c -o test_b3_sec
 */
#include "b3_sec.h"
#include "atca_host.h"

#include <stdio.h>
#include <string.h>

static int g_fails;

static void expect(int cond, const char *name)
{
    if (!cond) {
        printf("FAIL %s\n", name);
        g_fails++;
    } else {
        printf("ok   %s\n", name);
    }
}

int main(void)
{
    b3_sec_test_reset();
    atca_host_set_locked(1);
    expect(b3_sec_init(1, 2) == ESP_OK, "init");
    uint8_t sn[9];
    expect(b3_sec_serial(sn) == ESP_OK, "serial");
    expect(sn[0] == 0x01 && sn[1] == 0x23, "serial prefix");
    int reads = atca_host_serial_reads();
    expect(b3_sec_serial(sn) == ESP_OK, "serial cached call");
    expect(atca_host_serial_reads() == reads, "serial not read twice");
    expect(b3_sec_present(), "present");
    expect(b3_sec_provisioned(), "locked means provisioned");

    uint8_t msg[32];
    memset(msg, 0x42, sizeof(msg));
    uint8_t sig[64];
    uint8_t pub[64];
    expect(b3_sec_sign_p256(0, msg, sig) == ESP_OK, "sign");
    expect(b3_sec_pubkey(0, pub) == ESP_OK, "pubkey");
    expect(b3_sec_verify_p256(pub, msg, sig) == ESP_OK, "verify");
    msg[0] ^= 0xff;
    expect(b3_sec_verify_p256(pub, msg, sig) == ESP_FAIL, "verify rejects other message");

    uint8_t pt[16];
    uint8_t ct[16];
    uint8_t back[16];
    for (int i = 0; i < 16; i++) {
        pt[i] = (uint8_t)i;
    }
    expect(b3_sec_aes_encrypt_block(3, pt, ct) == ESP_OK, "aes encrypt");
    expect(memcmp(pt, ct, 16) != 0, "aes changes bytes");
    expect(b3_sec_aes_decrypt_block(3, ct, back) == ESP_OK, "aes decrypt");
    expect(memcmp(pt, back, 16) == 0, "aes round trip");

    uint8_t rnd[48];
    expect(b3_sec_random(rnd, sizeof(rnd)) == ESP_OK, "random 48");
    int nonzero = 0;
    for (int i = 0; i < 48; i++) {
        if (rnd[i] != 0) {
            nonzero = 1;
        }
    }
    expect(nonzero, "random not all zero");
    expect(b3_sec_seed_drbg() == ESP_OK, "drbg seed");

    uint8_t slot2[64];
    expect(b3_sec_slot2_pubkey(slot2) == ESP_OK, "slot2 cached");

    b3_sec_test_reset();
    atca_host_set_locked(0);
    expect(b3_sec_init(1, 2) == ESP_OK, "init unlocked");
    expect(!b3_sec_provisioned(), "unlocked is not provisioned");
    expect(!b3_sec_mining_blocked(), "soft gate keeps mining");
    b3_sec_test_set_require(1);
    expect(b3_sec_mining_blocked(), "hard gate blocks unlocked");
    expect(b3_sec_status_text() != NULL, "status text set");
    expect(strcmp(b3_sec_status_text(), "Card unprovisioned — run factory fixture") == 0, "status text");

    b3_sec_test_reset();
    atca_host_set_missing(1);
    esp_err_t err = b3_sec_init(1, 2);
    expect(err != ESP_OK, "missing device returns error");
    expect(!b3_sec_present(), "missing device is not present");
    expect(!b3_sec_mining_blocked(), "missing device does not abort the caller");

    if (g_fails) {
        printf("%d failed\n", g_fails);
        return 1;
    }
    printf("all passed\n");
    return 0;
}
