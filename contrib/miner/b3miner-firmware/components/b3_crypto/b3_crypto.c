#include "b3_crypto.h"

#include "blake3.h"

void b3_blake3_hash(const uint8_t *data, size_t len, uint8_t out[32])
{
    blake3_hasher hasher;
    blake3_hasher_init(&hasher);
    blake3_hasher_update(&hasher, data, len);
    blake3_hasher_finalize(&hasher, out, 32);
}
