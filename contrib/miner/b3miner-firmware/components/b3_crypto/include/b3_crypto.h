#pragma once

#include <stddef.h>
#include <stdint.h>

void b3_blake3_hash(const uint8_t *data, size_t len, uint8_t out[32]);
