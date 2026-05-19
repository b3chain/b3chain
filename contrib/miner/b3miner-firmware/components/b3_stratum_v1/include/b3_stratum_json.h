#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

/**
 * Stratum NDJSON helper — cJSON wrapper.
 *
 * Each Stratum line is parsed into a b3_json_t and then queried
 * via the helpers below. Caller must b3_json_free() when done.
 *
 * Notification (server push)  : id == null, method set, params set
 * Response   (reply to us)    : id integer, method absent, result/error set
 */

typedef struct b3_json b3_json_t;
typedef struct b3_json_value b3_json_value_t;

/* Parse a single NDJSON line. Returns ESP_OK and fills *out, or
 * ESP_ERR_INVALID_ARG on parse failure. */
esp_err_t b3_json_parse_line(const char *line, b3_json_t **out);
void b3_json_free(b3_json_t *j);

/* Categorisation */
bool b3_json_is_notification(const b3_json_t *j);
bool b3_json_is_response(const b3_json_t *j);
const char *b3_json_method(const b3_json_t *j);
uint64_t b3_json_response_id(const b3_json_t *j);

/* Response helpers — true if result is boolean-true, false otherwise. */
bool b3_json_response_ok(const b3_json_t *j);
/* Copy error tuple as JSON text into buf (truncated). Returns ESP_OK if
 * an error field was present, ESP_ERR_NOT_FOUND otherwise. */
esp_err_t b3_json_response_error(const b3_json_t *j, char *buf, size_t buflen);

/* Access to the top-level params/result arrays. Each returned handle
 * is owned by the b3_json_t — do NOT free it separately. */
const b3_json_value_t *b3_json_params(const b3_json_t *j);
const b3_json_value_t *b3_json_result(const b3_json_t *j);

/* Array accessors */
size_t b3_json_array_size(const b3_json_value_t *arr);
const b3_json_value_t *b3_json_array_get(const b3_json_value_t *arr, size_t idx);

/* Scalar accessors — return defaults on type mismatch / missing */
const char *b3_json_as_string(const b3_json_value_t *v);  /* NULL if not string */
double      b3_json_as_number(const b3_json_value_t *v);
bool        b3_json_as_bool  (const b3_json_value_t *v);
bool        b3_json_is_null  (const b3_json_value_t *v);

/* Format a request line: {"id":N,"method":"...","params":<params_json_array>}\n
 * Returns the number of bytes written (excluding NUL). Caller-provided
 * params_json_array must already be a valid JSON array literal. */
int b3_json_format_request(char *buf, size_t buflen, uint64_t id,
                           const char *method, const char *params_json_array);
