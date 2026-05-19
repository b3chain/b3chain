#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

/**
 * Hex helpers — used by Stratum notify decode and work builder.
 * Both directions are lower-case, no prefix, no whitespace.
 */

/* Decode `hex` (length must be 2*out_len) into `out`. Returns ESP_OK on
 * success, ESP_ERR_INVALID_ARG / ESP_ERR_INVALID_SIZE on bad input. */
esp_err_t b3_hex_decode(const char *hex, uint8_t *out, size_t out_len);

/* Decode `hex` of any length (must be even) into `out`. Writes the
 * number of bytes produced into `*produced`. */
esp_err_t b3_hex_decode_var(const char *hex, uint8_t *out, size_t out_cap,
                            size_t *produced);

/* Encode `in` to lower-case hex in `out`. `out` must have room for
 * 2*in_len + 1 bytes (NUL-terminated). */
void b3_hex_encode(const uint8_t *in, size_t in_len, char *out);

/* Parse a hex string into a 32-bit unsigned integer.
 * Accepts optional "0x" prefix. Returns 0 on invalid input. */
uint32_t b3_hex_to_u32(const char *hex);
