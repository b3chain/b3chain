#pragma once

#include "esp_err.h"

void b3_ota_start(const char *manifest_url);

/** Accept a manifest with no signature. Reject a bad signature. */
esp_err_t b3_ota_check_manifest(const char *json);
