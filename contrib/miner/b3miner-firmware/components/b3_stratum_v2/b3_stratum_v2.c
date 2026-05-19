/**
 * @file b3_stratum_v2.c
 * @brief Stratum V2 skeleton — Noise XX + binary framing.
 *
 * Reference: contrib/testnet/pool stratum-v2 translator, Braiins SV2 spec.
 *
 * FILL IN phases:
 *   Phase 1: TCP connect + version/setup handshake (no mining yet)
 *   Phase 2: OpenStandardMiningChannel + NewMiningJob messages
 *   Phase 3: SubmitShares message with B3Chain header blob
 *
 * Dependencies to add in production:
 *   - libsecp256k1 (authorized pubkey from pool)
 *   - Noise protocol (noise-c or custom XX pattern)
 */

#include "b3_stratum_v2.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "stratum_v2";

typedef enum {
    SV2_ST_DISCONNECTED = 0,
    SV2_ST_HANDSHAKE,
    SV2_ST_CHANNEL_OPEN,
    SV2_ST_MINING,
} sv2_state_t;

typedef struct {
    b3_runtime_config_t cfg;
    sv2_state_t state;
    /* FILL IN:
     * esp_tls_conn_t *tls;
     * noise_session_t noise;
     * uint32_t channel_id;
     * uint8_t  extranonce_prefix[8];
     */
} sv2_ctx_t;

static sv2_state_t sv2_run_handshake(sv2_ctx_t *ctx)
{
    (void)ctx;
    ESP_LOGW(TAG, "SV2 handshake STUB — falling back to V1 recommended for v1.0 ship");
    return SV2_ST_DISCONNECTED;
}

static void stratum_v2_task(void *arg)
{
    sv2_ctx_t *ctx = (sv2_ctx_t *)arg;
    for (;;) {
        ctx->state = sv2_run_handshake(ctx);
        if (ctx->state == SV2_ST_MINING) {
            /* FILL IN: read framed messages, decode NewMiningJob, publish to b3_work */
            vTaskDelay(pdMS_TO_TICKS(1000));
        } else {
            ESP_LOGE(TAG, "SV2 not ready — configure stratum+tcp V1 URL or implement SV2");
            vTaskDelay(pdMS_TO_TICKS(30000));
        }
    }
}

void b3_stratum_v2_start(const b3_runtime_config_t *cfg)
{
    static sv2_ctx_t ctx;
    ctx.cfg = *cfg;
    ctx.state = SV2_ST_DISCONNECTED;
    xTaskCreate(stratum_v2_task, "stratum_v2", 16384, &ctx, 8, NULL);
}
