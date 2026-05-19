/**
 * @file b3_stratum_json.c
 * @brief cJSON-backed Stratum NDJSON helpers.
 *
 * cJSON is included with ESP-IDF as the `json` component (no extra
 * dependency, no extra binary cost beyond the parser itself).
 */

#include "b3_stratum_json.h"

#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "esp_log.h"

static const char *TAG = "b3_json";

struct b3_json {
    cJSON *root;
    bool   is_notif;
    bool   is_resp;
    char   method[64];
    uint64_t resp_id;
};

esp_err_t b3_json_parse_line(const char *line, b3_json_t **out)
{
    if (!line || !out) {
        return ESP_ERR_INVALID_ARG;
    }
    cJSON *root = cJSON_Parse(line);
    if (!root) {
        ESP_LOGW(TAG, "parse failed: %.80s", line);
        return ESP_ERR_INVALID_ARG;
    }
    b3_json_t *j = calloc(1, sizeof(*j));
    if (!j) {
        cJSON_Delete(root);
        return ESP_ERR_NO_MEM;
    }
    j->root = root;

    const cJSON *id     = cJSON_GetObjectItemCaseSensitive(root, "id");
    const cJSON *method = cJSON_GetObjectItemCaseSensitive(root, "method");

    /* Stratum V1 notification rule (matches gpuminer/messages.rs:
     *   ServerMessage::is_notification): method present AND id null/absent */
    if (cJSON_IsString(method)) {
        strncpy(j->method, method->valuestring, sizeof(j->method) - 1);
        if (!id || cJSON_IsNull(id)) {
            j->is_notif = true;
        } else if (cJSON_IsNumber(id)) {
            /* Server-initiated request (rare). Treat as notification. */
            j->is_notif = true;
        }
    } else if (cJSON_IsNumber(id)) {
        j->is_resp = true;
        j->resp_id = (uint64_t)id->valuedouble;
    }

    *out = j;
    return ESP_OK;
}

void b3_json_free(b3_json_t *j)
{
    if (!j) return;
    if (j->root) cJSON_Delete(j->root);
    free(j);
}

bool b3_json_is_notification(const b3_json_t *j) { return j && j->is_notif; }
bool b3_json_is_response   (const b3_json_t *j) { return j && j->is_resp; }
const char *b3_json_method (const b3_json_t *j) { return j ? j->method : NULL; }
uint64_t b3_json_response_id(const b3_json_t *j) { return j ? j->resp_id : 0; }

bool b3_json_response_ok(const b3_json_t *j)
{
    if (!j || !j->root) return false;
    const cJSON *result = cJSON_GetObjectItemCaseSensitive(j->root, "result");
    const cJSON *error  = cJSON_GetObjectItemCaseSensitive(j->root, "error");
    if (error && !cJSON_IsNull(error)) return false;
    return cJSON_IsBool(result) ? cJSON_IsTrue(result) : (result != NULL);
}

esp_err_t b3_json_response_error(const b3_json_t *j, char *buf, size_t buflen)
{
    if (!j || !buf || buflen == 0) return ESP_ERR_INVALID_ARG;
    const cJSON *error = cJSON_GetObjectItemCaseSensitive(j->root, "error");
    if (!error || cJSON_IsNull(error)) return ESP_ERR_NOT_FOUND;
    char *txt = cJSON_PrintUnformatted(error);
    if (!txt) return ESP_ERR_NO_MEM;
    strncpy(buf, txt, buflen - 1);
    buf[buflen - 1] = '\0';
    cJSON_free(txt);
    return ESP_OK;
}

const b3_json_value_t *b3_json_params(const b3_json_t *j)
{
    if (!j) return NULL;
    return (const b3_json_value_t *)cJSON_GetObjectItemCaseSensitive(j->root, "params");
}

const b3_json_value_t *b3_json_result(const b3_json_t *j)
{
    if (!j) return NULL;
    return (const b3_json_value_t *)cJSON_GetObjectItemCaseSensitive(j->root, "result");
}

size_t b3_json_array_size(const b3_json_value_t *arr)
{
    const cJSON *c = (const cJSON *)arr;
    if (!c || !cJSON_IsArray(c)) return 0;
    return (size_t)cJSON_GetArraySize(c);
}

const b3_json_value_t *b3_json_array_get(const b3_json_value_t *arr, size_t idx)
{
    const cJSON *c = (const cJSON *)arr;
    if (!c || !cJSON_IsArray(c)) return NULL;
    return (const b3_json_value_t *)cJSON_GetArrayItem(c, (int)idx);
}

const char *b3_json_as_string(const b3_json_value_t *v)
{
    const cJSON *c = (const cJSON *)v;
    return (c && cJSON_IsString(c)) ? c->valuestring : NULL;
}

double b3_json_as_number(const b3_json_value_t *v)
{
    const cJSON *c = (const cJSON *)v;
    return (c && cJSON_IsNumber(c)) ? c->valuedouble : 0.0;
}

bool b3_json_as_bool(const b3_json_value_t *v)
{
    const cJSON *c = (const cJSON *)v;
    if (!c) return false;
    if (cJSON_IsBool(c)) return cJSON_IsTrue(c);
    if (cJSON_IsNumber(c)) return c->valuedouble != 0.0;
    return false;
}

bool b3_json_is_null(const b3_json_value_t *v)
{
    const cJSON *c = (const cJSON *)v;
    return !c || cJSON_IsNull(c);
}

int b3_json_format_request(char *buf, size_t buflen, uint64_t id,
                           const char *method, const char *params_json_array)
{
    return snprintf(buf, buflen,
                    "{\"id\":%llu,\"method\":\"%s\",\"params\":%s}\n",
                    (unsigned long long)id, method, params_json_array);
}
