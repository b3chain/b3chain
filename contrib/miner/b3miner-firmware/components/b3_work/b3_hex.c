#include "b3_hex.h"

#include <ctype.h>
#include <string.h>

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

esp_err_t b3_hex_decode(const char *hex, uint8_t *out, size_t out_len)
{
    if (!hex || !out) {
        return ESP_ERR_INVALID_ARG;
    }
    if (strlen(hex) != out_len * 2) {
        return ESP_ERR_INVALID_SIZE;
    }
    for (size_t i = 0; i < out_len; ++i) {
        int hi = hex_nibble(hex[i * 2]);
        int lo = hex_nibble(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            return ESP_ERR_INVALID_ARG;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return ESP_OK;
}

esp_err_t b3_hex_decode_var(const char *hex, uint8_t *out, size_t out_cap,
                            size_t *produced)
{
    if (!hex || !out || !produced) {
        return ESP_ERR_INVALID_ARG;
    }
    size_t hlen = strlen(hex);
    if (hlen & 1) {
        return ESP_ERR_INVALID_SIZE;
    }
    size_t need = hlen / 2;
    if (need > out_cap) {
        return ESP_ERR_INVALID_SIZE;
    }
    for (size_t i = 0; i < need; ++i) {
        int hi = hex_nibble(hex[i * 2]);
        int lo = hex_nibble(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            return ESP_ERR_INVALID_ARG;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    *produced = need;
    return ESP_OK;
}

void b3_hex_encode(const uint8_t *in, size_t in_len, char *out)
{
    static const char tab[] = "0123456789abcdef";
    for (size_t i = 0; i < in_len; ++i) {
        out[i * 2]     = tab[(in[i] >> 4) & 0x0F];
        out[i * 2 + 1] = tab[in[i] & 0x0F];
    }
    out[in_len * 2] = '\0';
}

uint32_t b3_hex_to_u32(const char *hex)
{
    if (!hex) return 0;
    const char *p = hex;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
    }
    uint32_t v = 0;
    while (*p) {
        int n = hex_nibble(*p++);
        if (n < 0) return 0;
        v = (v << 4) | (uint32_t)n;
    }
    return v;
}
