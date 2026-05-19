/**
 * @file b3_web.c
 * @brief Local dashboard — REST + WebSocket (/ws/metrics).
 *
 * Endpoints:
 *   GET  /              → embedded index.html (FILL IN: embed web/dist/)
 *   GET  /api/v1/status → JSON hashrate, temp, pool, uptime
 *   GET  /api/v1/config → read-only pool URL (password redacted)
 *   POST /api/v1/config → update pool (requires auth token — FILL IN)
 *   GET  /metrics       → Prometheus text exposition
 *   GET  /ws/metrics    → WebSocket push every 1s
 */

#include "b3_web.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "b3_config.h"
#include "b3_fpga.h"
#include "b3_metrics.h"

#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "b3_web";
static httpd_handle_t s_server;

static const char *INDEX_HTML =
    "<!DOCTYPE html><html><head><meta charset=utf-8>"
    "<title>B3Miner-1</title></head><body>"
    "<h1>B3Miner-1</h1><pre id=s>loading...</pre>"
    "<script>"
    "const ws=new WebSocket('ws://'+location.host+'/ws/metrics');"
    "ws.onmessage=e=>document.getElementById('s').textContent=e.data;"
    "</script></body></html>";

static esp_err_t handle_root(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t handle_status(httpd_req_t *req)
{
    b3_metrics_snapshot_t m;
    b3_metrics_get_snapshot(&m);
    char body[512];
    snprintf(body, sizeof(body),
             "{\"hashrate_khs\":%.3f,\"shares_accepted\":%" PRIu32 ","
             "\"shares_rejected\":%" PRIu32 ",\"uptime_s\":%" PRIu32 ","
             "\"fpga_temp_c\":%.1f,\"hashes_total\":%llu}",
             m.hashrate_khs, m.shares_accepted, m.shares_rejected,
             m.uptime_s, b3_fpga_read_die_celsius(),
             (unsigned long long)m.hashes_total);
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t handle_metrics(httpd_req_t *req)
{
    b3_metrics_snapshot_t m;
    b3_metrics_get_snapshot(&m);
    char body[256];
    snprintf(body, sizeof(body),
             "# HELP b3_hashrate_khs Instantaneous hashrate kilohashes per second\n"
             "# TYPE b3_hashrate_khs gauge\n"
             "b3_hashrate_khs %.6f\n"
             "# HELP b3_shares_accepted_total Accepted shares\n"
             "# TYPE b3_shares_accepted_total counter\n"
             "b3_shares_accepted_total %" PRIu32 "\n",
             m.hashrate_khs, m.shares_accepted);
    httpd_resp_set_type(req, "text/plain; version=0.0.4");
    return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

/* FILL IN: proper WebSocket handler using httpd_ws_* APIs */
static esp_err_t handle_ws(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {
        ESP_LOGI(TAG, "WebSocket handshake");
        return ESP_OK;
    }
    b3_metrics_snapshot_t m;
    b3_metrics_get_snapshot(&m);
    char msg[128];
    snprintf(msg, sizeof(msg), "hashrate_khs=%.3f temp=%.1f",
             m.hashrate_khs, b3_fpga_read_die_celsius());
    /* httpd_ws_send_frame(req, ...) — FILL IN */
    (void)msg;
    return ESP_OK;
}

void b3_web_on_got_ip(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    (void)id;
    ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
    ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&ev->ip_info.ip));
}

void b3_web_start(uint16_t port)
{
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = port;
    cfg.lru_purge_enable = true;
    cfg.max_uri_handlers = 12;

    if (httpd_start(&s_server, &cfg) != ESP_OK) {
        ESP_LOGE(TAG, "httpd_start failed");
        return;
    }

    httpd_uri_t uris[] = {
        {.uri = "/", .method = HTTP_GET, .handler = handle_root},
        {.uri = "/api/v1/status", .method = HTTP_GET, .handler = handle_status},
        {.uri = "/metrics", .method = HTTP_GET, .handler = handle_metrics},
        {.uri = "/ws/metrics", .method = HTTP_GET, .handler = handle_ws},
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); ++i) {
        httpd_register_uri_handler(s_server, &uris[i]);
    }
    ESP_LOGI(TAG, "HTTP dashboard on port %u", port);
}
