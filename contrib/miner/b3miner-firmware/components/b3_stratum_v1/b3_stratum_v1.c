/**
 * @file b3_stratum_v1.c
 * @brief Stratum V1 client for B3Chain — mirrors b3chain-gpuminer/src/stratum/client.rs.
 *
 * Wire: newline-delimited JSON over TCP (TLS support is FILL IN).
 * Methods we send         : mining.subscribe, mining.authorize, mining.submit
 * Notifications we handle : mining.notify, mining.set_difficulty,
 *                           mining.set_extranonce
 *
 * Job pipeline:
 *   pool -> on_mining_notify() -> b3_work_publish_job() -> fpga_worker task
 *   fpga_worker -> b3_events_share_queue() -> submit_share() -> pool
 *
 * Loop verification (Tier-3):
 *   1. TRIGGER  : connect_tcp + handshake
 *   2. PROCESS  : THE READ LOOP — recv_line() repeatedly, dispatched to on_*()
 *   3. RESULT   : b3_work_publish_job() (jobs); send_line() (submit)
 *   4. BYPASS   : disconnect -> reconnect backoff (5s) at end of loop
 *                 stale job   -> fpga_worker aborts via b3_work_job_stale()
 */

#include "b3_stratum_v1.h"

#include <errno.h>
#include <inttypes.h>
#include <netdb.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>

#include "b3_events.h"
#include "b3_hex.h"
#include "b3_stratum_json.h"
#include "b3_work.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "esp_tls.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/sockets.h"

static const char *TAG = "stratum_v1";

typedef struct {
    b3_runtime_config_t cfg;
    char host[96];
    uint16_t port;
    int sock;
    uint64_t req_id;

    /* Extranonce — assigned by mining.subscribe response */
    uint8_t  extranonce1[32];
    size_t   extranonce1_len;
    size_t   extranonce2_size;

    /* Per-worker rolling extranonce2 counter (host-side nonce-space slice) */
    uint32_t extranonce2_counter;

    float    share_diff;
    uint32_t clean_epoch;

    SemaphoreHandle_t submit_mtx;
} stratum_v1_ctx_t;

static stratum_v1_ctx_t s_ctx;

/* --------------------------------------------------------------------- *
 * Wire helpers
 * --------------------------------------------------------------------- */

static esp_err_t send_line(int sock, const char *line)
{
    size_t len = strlen(line);
    ssize_t sent = send(sock, line, len, 0);
    return sent == (ssize_t)len ? ESP_OK : ESP_FAIL;
}

static esp_err_t recv_line(int sock, char *buf, size_t buflen, int timeout_ms)
{
    size_t pos = 0;
    int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000;
    while (pos + 1 < buflen) {
        if (esp_timer_get_time() > deadline) {
            return ESP_ERR_TIMEOUT;
        }
        char c;
        int n = recv(sock, &c, 1, 0);
        if (n == 0) {
            return ESP_ERR_INVALID_STATE;
        }
        if (n < 0) {
            if (errno == EWOULDBLOCK || errno == EAGAIN) {
                vTaskDelay(pdMS_TO_TICKS(10));
                continue;
            }
            return ESP_FAIL;
        }
        if (c == '\n') {
            buf[pos] = '\0';
            return ESP_OK;
        }
        if (c != '\r') {
            buf[pos++] = c;
        }
    }
    return ESP_ERR_INVALID_SIZE;
}

/* Send a request and wait for its response (correlated by id). All notifications
 * received in between are dispatched normally. */
static esp_err_t rpc_call(stratum_v1_ctx_t *ctx, const char *method,
                          const char *params_json, b3_json_t **resp_out);

/* Forward declarations for notification handlers */
static void on_mining_notify(stratum_v1_ctx_t *ctx, const b3_json_value_t *params);
static void on_set_difficulty(stratum_v1_ctx_t *ctx, const b3_json_value_t *params);
static void on_set_extranonce(stratum_v1_ctx_t *ctx, const b3_json_value_t *params);

/* --------------------------------------------------------------------- *
 * Notification handlers
 * --------------------------------------------------------------------- */

static void on_set_difficulty(stratum_v1_ctx_t *ctx, const b3_json_value_t *params)
{
    if (b3_json_array_size(params) < 1) return;
    double d = b3_json_as_number(b3_json_array_get(params, 0));
    if (d <= 0.0) return;
    ctx->share_diff = (float)d;
    ESP_LOGI(TAG, "set_difficulty -> %.3f", d);
}

static void on_set_extranonce(stratum_v1_ctx_t *ctx, const b3_json_value_t *params)
{
    if (b3_json_array_size(params) < 2) return;
    const char *en1_hex = b3_json_as_string(b3_json_array_get(params, 0));
    int en2_size = (int)b3_json_as_number(b3_json_array_get(params, 1));
    if (!en1_hex || en2_size <= 0) return;

    size_t produced = 0;
    if (b3_hex_decode_var(en1_hex, ctx->extranonce1, sizeof(ctx->extranonce1),
                          &produced) != ESP_OK) {
        ESP_LOGW(TAG, "set_extranonce: bad en1 hex");
        return;
    }
    ctx->extranonce1_len = produced;
    ctx->extranonce2_size = (size_t)en2_size;
    ctx->clean_epoch++;
    ESP_LOGI(TAG, "set_extranonce en1=%s en2_size=%d", en1_hex, en2_size);
}

/*
 * mining.notify params (Stratum V1 layout, 9 fields):
 *   [0] job_id        : string
 *   [1] prevhash      : hex string of 32 bytes (raw — header builder owns endian)
 *   [2] coinb1        : hex string (coinbase prefix)
 *   [3] coinb2        : hex string (coinbase suffix)
 *   [4] merkle_branch : array of 32-byte hex strings
 *   [5] version       : hex string (4 bytes BE) — also accept integer
 *   [6] nbits         : hex string (4 bytes BE)
 *   [7] ntime         : hex string (4 bytes BE)
 *   [8] clean_jobs    : bool
 *
 * Mirrors the parse order in
 *   contrib/miner/b3chain-gpuminer/src/stratum/client.rs::on_mining_notify
 * and contrib/miner/b3chain-cpuminer.py::_on_notify.
 */
static void on_mining_notify(stratum_v1_ctx_t *ctx, const b3_json_value_t *params)
{
    if (b3_json_array_size(params) < 9) {
        ESP_LOGW(TAG, "notify: too few params (%u)", (unsigned)b3_json_array_size(params));
        return;
    }

    const char *job_id_s = b3_json_as_string(b3_json_array_get(params, 0));
    const char *prev_hex = b3_json_as_string(b3_json_array_get(params, 1));
    const char *coinb1   = b3_json_as_string(b3_json_array_get(params, 2));
    const char *coinb2   = b3_json_as_string(b3_json_array_get(params, 3));
    const b3_json_value_t *branches = b3_json_array_get(params, 4);
    const b3_json_value_t *ver_v    = b3_json_array_get(params, 5);
    const b3_json_value_t *nbits_v  = b3_json_array_get(params, 6);
    const b3_json_value_t *ntime_v  = b3_json_array_get(params, 7);
    bool clean_jobs = b3_json_as_bool(b3_json_array_get(params, 8));

    if (!job_id_s || !prev_hex || !coinb1 || !coinb2) {
        ESP_LOGW(TAG, "notify: missing required string fields");
        return;
    }

    b3_work_job_t job = {0};

    /* IDs and toggles */
    strncpy(job.job_id, job_id_s, sizeof(job.job_id) - 1);
    job.epoch = ++ctx->clean_epoch;
    job.share_diff = ctx->share_diff;
    job.extranonce2_size = ctx->extranonce2_size ? ctx->extranonce2_size : 4;
    job.nonce_batch_size = 0x100000; /* 1M nonces per FPGA batch */

    /* prev_block_hash — stored raw as decoded from hex (header builder
     * owns the endian flip — see b3_work_build_header). */
    if (b3_hex_decode(prev_hex, job.prev_block_hash, 32) != ESP_OK) {
        ESP_LOGW(TAG, "notify: bad prev_hash hex");
        return;
    }

    /* Coinbase halves — kept as hex strings; combined with extranonce in
     * b3_work_build_header. */
    size_t c1_len = strlen(coinb1);
    size_t c2_len = strlen(coinb2);
    if (c1_len >= B3_WORK_COINB1_MAX || c2_len >= B3_WORK_COINB2_MAX) {
        ESP_LOGW(TAG, "notify: coinbase too large (%u + %u)",
                 (unsigned)c1_len, (unsigned)c2_len);
        return;
    }
    memcpy(job.coinb1_hex, coinb1, c1_len + 1);
    memcpy(job.coinb2_hex, coinb2, c2_len + 1);

    /* Merkle branch — array of hex strings */
    size_t branch_cnt = b3_json_array_size(branches);
    if (branch_cnt > B3_WORK_MERKLE_MAX) {
        ESP_LOGW(TAG, "notify: too many merkle branches (%u)", (unsigned)branch_cnt);
        return;
    }
    for (size_t i = 0; i < branch_cnt; ++i) {
        const char *h = b3_json_as_string(b3_json_array_get(branches, i));
        if (!h || strlen(h) != 64) {
            ESP_LOGW(TAG, "notify: bad merkle branch [%u]", (unsigned)i);
            return;
        }
        memcpy(job.merkle_branch_hex[i], h, 65);
    }
    job.merkle_branch_count = branch_cnt;

    /* Version / nbits / ntime — accept either hex string or number */
    const char *ver_s   = b3_json_as_string(ver_v);
    const char *nbits_s = b3_json_as_string(nbits_v);
    const char *ntime_s = b3_json_as_string(ntime_v);
    job.version = ver_s   ? b3_hex_to_u32(ver_s)   : (uint32_t)b3_json_as_number(ver_v);
    job.nbits   = nbits_s ? b3_hex_to_u32(nbits_s) : (uint32_t)b3_json_as_number(nbits_v);
    job.ntime   = ntime_s ? b3_hex_to_u32(ntime_s) : (uint32_t)b3_json_as_number(ntime_v);

    /* Copy extranonce1 (immutable for the lifetime of the connection
     * unless set_extranonce arrives). */
    memcpy(job.extranonce1, ctx->extranonce1,
           ctx->extranonce1_len > sizeof(job.extranonce1)
               ? sizeof(job.extranonce1) : ctx->extranonce1_len);
    job.extranonce1_len = ctx->extranonce1_len;

    /* Reset per-job extranonce2 counter on clean_jobs */
    if (clean_jobs) {
        ctx->extranonce2_counter = 0;
    }

    /* TODO (b3_work): derive share_target_be from share_diff,
     * network_target_be from nbits, pow_seed from header template. */

    b3_work_publish_job(&job);
    b3_events_post(B3_EVT_JOB_NEW);

    ESP_LOGI(TAG, "notify job=%s epoch=%" PRIu32 " ver=0x%08" PRIx32
             " bits=0x%08" PRIx32 " ntime=0x%08" PRIx32
             " branches=%u clean=%d diff=%.2f",
             job.job_id, job.epoch, job.version, job.nbits, job.ntime,
             (unsigned)branch_cnt, clean_jobs, ctx->share_diff);
}

/* --------------------------------------------------------------------- *
 * Handshake — mining.subscribe + mining.authorize
 * --------------------------------------------------------------------- */

static esp_err_t parse_subscribe_result(stratum_v1_ctx_t *ctx, const b3_json_t *resp)
{
    /* Standard result: [[subscriptions...], extranonce1_hex, extranonce2_size] */
    const b3_json_value_t *result = b3_json_result(resp);
    if (b3_json_array_size(result) < 3) {
        ESP_LOGW(TAG, "subscribe result too short");
        return ESP_ERR_INVALID_RESPONSE;
    }
    const char *en1_hex = b3_json_as_string(b3_json_array_get(result, 1));
    double en2_size_d   = b3_json_as_number(b3_json_array_get(result, 2));
    if (!en1_hex || en2_size_d <= 0) {
        ESP_LOGW(TAG, "subscribe: missing en1/en2_size");
        return ESP_ERR_INVALID_RESPONSE;
    }

    size_t produced = 0;
    if (b3_hex_decode_var(en1_hex, ctx->extranonce1, sizeof(ctx->extranonce1),
                          &produced) != ESP_OK) {
        ESP_LOGW(TAG, "subscribe: bad en1 hex '%s'", en1_hex);
        return ESP_ERR_INVALID_RESPONSE;
    }
    ctx->extranonce1_len = produced;
    ctx->extranonce2_size = (size_t)en2_size_d;
    ctx->extranonce2_counter = 0;

    ESP_LOGI(TAG, "subscribed en1=%s (%u B) en2_size=%u",
             en1_hex, (unsigned)produced, (unsigned)ctx->extranonce2_size);
    return ESP_OK;
}

static esp_err_t handshake(stratum_v1_ctx_t *ctx)
{
    char params[256];
    b3_json_t *resp = NULL;

    /* mining.subscribe ["b3miner-esp32/1.0"] */
    snprintf(params, sizeof(params), "[\"b3miner-esp32/1.0\"]");
    if (rpc_call(ctx, "mining.subscribe", params, &resp) != ESP_OK || !resp) {
        return ESP_FAIL;
    }
    esp_err_t err = parse_subscribe_result(ctx, resp);
    b3_json_free(resp);
    if (err != ESP_OK) return err;

    /* mining.authorize ["user", "pass"] */
    snprintf(params, sizeof(params), "[\"%s\",\"%s\"]",
             ctx->cfg.worker_user, ctx->cfg.worker_pass);
    if (rpc_call(ctx, "mining.authorize", params, &resp) != ESP_OK || !resp) {
        return ESP_FAIL;
    }
    bool ok = b3_json_response_ok(resp);
    if (!ok) {
        char errbuf[128] = {0};
        b3_json_response_error(resp, errbuf, sizeof(errbuf));
        ESP_LOGE(TAG, "authorize rejected: %s", errbuf);
    } else {
        ESP_LOGI(TAG, "authorized as %s", ctx->cfg.worker_user);
    }
    b3_json_free(resp);
    return ok ? ESP_OK : ESP_FAIL;
}

/* --------------------------------------------------------------------- *
 * Dispatch + RPC correlation
 * --------------------------------------------------------------------- */

static bool dispatch_notification(stratum_v1_ctx_t *ctx, const b3_json_t *msg)
{
    const char *method = b3_json_method(msg);
    if (!method) return false;
    const b3_json_value_t *params = b3_json_params(msg);
    if (strcmp(method, "mining.notify") == 0) {
        on_mining_notify(ctx, params);
    } else if (strcmp(method, "mining.set_difficulty") == 0) {
        on_set_difficulty(ctx, params);
    } else if (strcmp(method, "mining.set_extranonce") == 0) {
        on_set_extranonce(ctx, params);
    } else {
        ESP_LOGD(TAG, "unknown notify method '%s' (ignoring)", method);
    }
    return true;
}

static esp_err_t rpc_call(stratum_v1_ctx_t *ctx, const char *method,
                          const char *params_json, b3_json_t **resp_out)
{
    char req[512];
    ctx->req_id++;
    uint64_t want_id = ctx->req_id;
    int n = b3_json_format_request(req, sizeof(req), want_id, method, params_json);
    if (n <= 0 || (size_t)n >= sizeof(req)) {
        return ESP_ERR_INVALID_SIZE;
    }
    ESP_LOGD(TAG, "-> %.*s", n - 1, req);
    if (send_line(ctx->sock, req) != ESP_OK) {
        return ESP_FAIL;
    }

    /* Read until we get the matching response. Dispatch notifications
     * that arrive in between. */
    char line[4096];
    int64_t deadline = esp_timer_get_time() + 15 * 1000 * 1000;
    while (esp_timer_get_time() < deadline) {
        if (recv_line(ctx->sock, line, sizeof(line), 15000) != ESP_OK) {
            return ESP_ERR_TIMEOUT;
        }
        b3_json_t *msg = NULL;
        if (b3_json_parse_line(line, &msg) != ESP_OK) {
            continue;
        }
        if (b3_json_is_notification(msg)) {
            dispatch_notification(ctx, msg);
            b3_json_free(msg);
            continue;
        }
        if (b3_json_is_response(msg) && b3_json_response_id(msg) == want_id) {
            *resp_out = msg;
            return ESP_OK;
        }
        ESP_LOGW(TAG, "rpc: skipping response id=%llu (waiting for %llu)",
                 (unsigned long long)b3_json_response_id(msg),
                 (unsigned long long)want_id);
        b3_json_free(msg);
    }
    return ESP_ERR_TIMEOUT;
}

/* --------------------------------------------------------------------- *
 * Submit
 * --------------------------------------------------------------------- */

static esp_err_t submit_share(stratum_v1_ctx_t *ctx, const b3_work_job_t *job,
                              const b3_share_event_t *ev)
{
    if (!job || !ev) {
        return ESP_ERR_INVALID_ARG;
    }
    xSemaphoreTake(ctx->submit_mtx, portMAX_DELAY);

    /* extranonce2 hex string — variable length per pool */
    char en2_hex[32 * 2 + 1] = {0};
    size_t en2_size = ctx->extranonce2_size > 4 ? 4 : ctx->extranonce2_size;
    if (en2_size == 0) en2_size = 4;
    b3_hex_encode(ev->extranonce2, en2_size, en2_hex);

    char params[256];
    char line[512];
    snprintf(params, sizeof(params),
             "[\"%s\",\"%s\",\"%s\",\"%08" PRIx32 "\",\"%08" PRIx32 "\"]",
             ctx->cfg.worker_user, job->job_id, en2_hex, ev->ntime, ev->nonce);

    ctx->req_id++;
    uint64_t want_id = ctx->req_id;
    int n = b3_json_format_request(line, sizeof(line), want_id,
                                   "mining.submit", params);
    if (n <= 0) {
        xSemaphoreGive(ctx->submit_mtx);
        return ESP_FAIL;
    }

    int64_t t0 = esp_timer_get_time();
    esp_err_t err = send_line(ctx->sock, line);
    /* Response is correlated by the main read loop — we don't block
     * here; instead the next iteration of the read loop logs the
     * accepted/rejected outcome. For a richer correlation, see the
     * gpuminer client's pending-response map. */
    int64_t dt = (esp_timer_get_time() - t0) / 1000;
    ESP_LOGI(TAG, "-> submit job=%s nonce=%08" PRIx32 " en2=%s (write %lld ms)",
             job->job_id, ev->nonce, en2_hex, (long long)dt);

    xSemaphoreGive(ctx->submit_mtx);
    return err;
}

/* --------------------------------------------------------------------- *
 * Connect + read loop
 * --------------------------------------------------------------------- */

static esp_err_t connect_tcp(stratum_v1_ctx_t *ctx)
{
    struct addrinfo hints = {0}, *res = NULL;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    char portstr[8];
    snprintf(portstr, sizeof(portstr), "%u", ctx->port);

    if (getaddrinfo(ctx->host, portstr, &hints, &res) != 0 || !res) {
        return ESP_ERR_NOT_FOUND;
    }

    int sock = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (sock < 0) {
        freeaddrinfo(res);
        return ESP_FAIL;
    }

    struct timeval tv = {.tv_sec = 30, .tv_usec = 0};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    if (connect(sock, res->ai_addr, res->ai_addrlen) != 0) {
        close(sock);
        freeaddrinfo(res);
        return ESP_ERR_HTTP_CONNECT;
    }
    freeaddrinfo(res);
    ctx->sock = sock;
    return ESP_OK;
}

static void stratum_v1_task(void *arg)
{
    stratum_v1_ctx_t *ctx = (stratum_v1_ctx_t *)arg;
    uint32_t attempt = 0;
    uint32_t backoff_ms = 5000;

    for (;;) {
        attempt++;
        ESP_LOGI(TAG, "connecting to %s:%u (attempt %" PRIu32 ")", ctx->host, ctx->port, attempt);

        if (connect_tcp(ctx) != ESP_OK) {
            ESP_LOGW(TAG, "connect failed; retry in %" PRIu32 " ms", backoff_ms);
            vTaskDelay(pdMS_TO_TICKS(backoff_ms));
            backoff_ms = backoff_ms < 60000 ? backoff_ms * 2 : 60000;
            continue;
        }

        if (handshake(ctx) != ESP_OK) {
            ESP_LOGW(TAG, "handshake failed");
            close(ctx->sock);
            vTaskDelay(pdMS_TO_TICKS(backoff_ms));
            backoff_ms = backoff_ms < 60000 ? backoff_ms * 2 : 60000;
            continue;
        }
        backoff_ms = 5000;

        /* THE READ LOOP — process messages until disconnect or timeout */
        char line[4096];
        for (;;) {
            /* Drain FPGA share queue and forward to pool. Non-blocking. */
            b3_share_event_t share;
            while (xQueueReceive(b3_events_share_queue(), &share, 0) == pdTRUE) {
                b3_work_job_t job;
                if (b3_work_wait_job(&job, 0)) {
                    submit_share(ctx, &job, &share);
                }
            }

            esp_err_t rerr = recv_line(ctx->sock, line, sizeof(line), 500);
            if (rerr == ESP_ERR_TIMEOUT) {
                /* No traffic in 500 ms — loop back to drain share queue. */
                continue;
            }
            if (rerr != ESP_OK) {
                break;
            }
            if (line[0] == '\0') continue;

            b3_json_t *msg = NULL;
            if (b3_json_parse_line(line, &msg) != ESP_OK) {
                ESP_LOGW(TAG, "parse error on line: %.120s", line);
                continue;
            }
            if (b3_json_is_notification(msg)) {
                dispatch_notification(ctx, msg);
            } else if (b3_json_is_response(msg)) {
                /* Submit response (or other late RPC). Log outcome. */
                bool ok = b3_json_response_ok(msg);
                if (ok) {
                    ESP_LOGI(TAG, "<- response id=%llu ACCEPTED",
                             (unsigned long long)b3_json_response_id(msg));
                } else {
                    char errbuf[128] = {0};
                    b3_json_response_error(msg, errbuf, sizeof(errbuf));
                    ESP_LOGW(TAG, "<- response id=%llu REJECTED %s",
                             (unsigned long long)b3_json_response_id(msg),
                             errbuf);
                }
            }
            b3_json_free(msg);
        }

        ESP_LOGW(TAG, "disconnected, reconnecting in %" PRIu32 " ms", backoff_ms);
        close(ctx->sock);
        vTaskDelay(pdMS_TO_TICKS(backoff_ms));
        backoff_ms = backoff_ms < 60000 ? backoff_ms * 2 : 60000;
    }
}

/* --------------------------------------------------------------------- *
 * Public entry point
 * --------------------------------------------------------------------- */

void b3_stratum_v1_start(const b3_runtime_config_t *cfg)
{
    memset(&s_ctx, 0, sizeof(s_ctx));
    s_ctx.cfg = *cfg;
    s_ctx.submit_mtx = xSemaphoreCreateMutex();
    s_ctx.share_diff = cfg->default_diff;

    char host[96] = {0};
    uint16_t port = 3333;
    bool tls = false;
    b3_stratum_proto_t proto;
    b3_config_parse_pool_url(cfg->pool_url, host, sizeof(host), &port, &tls, &proto);
    strncpy(s_ctx.host, host, sizeof(s_ctx.host) - 1);
    s_ctx.port = port;
    (void)tls; /* FILL IN: esp_tls_conn for stratum+ssl */

    b3_work_init();
    xTaskCreate(stratum_v1_task, "stratum_v1", 12288, &s_ctx, 8, NULL);
}
