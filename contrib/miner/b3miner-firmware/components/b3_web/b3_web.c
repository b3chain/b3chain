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
#include "b3_sec.h"

#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#if CONFIG_B3_NETWORK_WIFI
#include "esp_wifi.h"
#endif
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
    const char *gate = b3_sec_status_text();
    httpd_resp_set_type(req, "text/html");
    if (gate) {
        char page[256];
        snprintf(page, sizeof(page),
                 "<!DOCTYPE html><html><body><h1>%s</h1></body></html>", gate);
        return httpd_resp_send(req, page, HTTPD_RESP_USE_STRLEN);
    }
    return httpd_resp_send(req, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static int json_text_ok(const char *text)
{
    if (!text || !text[0]) {
        return 0;
    }
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p < 0x20 || *p == '"' || *p == '\\') {
            return 0;
        }
    }
    return 1;
}

static esp_err_t handle_status(httpd_req_t *req)
{
    b3_metrics_snapshot_t m;
    b3_metrics_get_snapshot(&m);
    float temp_c = 0.0f;
    const int spi_ok = b3_fpga_try_read_die_celsius(&temp_c);
    char temp_lit[24] = "null";
    if (spi_ok) {
        snprintf(temp_lit, sizeof(temp_lit), "%.1f", temp_c);
    }

    char rssi_lit[16] = "null";
    char channel_lit[16] = "null";
    char ssid_lit[80] = "null";
    char disconnect_lit[16] = "null";
#if CONFIG_B3_NETWORK_WIFI
    wifi_ap_record_t ap;
    memset(&ap, 0, sizeof(ap));
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        snprintf(rssi_lit, sizeof(rssi_lit), "%d", ap.rssi);
        snprintf(channel_lit, sizeof(channel_lit), "%u", ap.primary);
        char ssid[33];
        memcpy(ssid, ap.ssid, sizeof(ap.ssid));
        ssid[32] = '\0';
        if (json_text_ok(ssid)) {
            snprintf(ssid_lit, sizeof(ssid_lit), "\"%s\"", ssid);
        }
    }
    snprintf(disconnect_lit, sizeof(disconnect_lit), "%" PRIu32, m.wifi_disconnects);
#endif

    char body[1600];
    const char *gate = b3_sec_status_text();
    char gate_lit[96] = "null";
    if (gate) {
        snprintf(gate_lit, sizeof(gate_lit), "\"%s\"", gate);
    }
    snprintf(body, sizeof(body),
             "{\"hashrate_khs\":%.3f,\"last_completed_khs\":%.3f,"
             "\"shares_accepted\":%" PRIu32 ",\"shares_rejected\":%" PRIu32 ","
             "\"uptime_s\":%" PRIu32 ",\"measurement_age_s\":%" PRIu32 ","
             "\"job_epoch\":%" PRIu32 ",\"stratum_connected\":%u,"
             "\"fpga_temp_c\":%s,\"fpga_spi_ok\":%s,\"hashes_total\":%llu,"
             "\"board_link\":\"spi\",\"wifi_rssi_dbm\":%s,\"wifi_channel\":%s,"
             "\"wifi_ssid\":%s,\"wifi_disconnects\":%s,"
             "\"sec_present\":%s,\"sec_provisioned\":%s,\"status_text\":%s}",
             m.hashrate_khs, m.last_completed_khs,
             m.shares_accepted, m.shares_rejected,
             m.uptime_s, m.measurement_age_s, m.job_epoch,
             (unsigned)m.stratum_connected, temp_lit, spi_ok ? "true" : "false",
             (unsigned long long)m.hashes_total,
             rssi_lit, channel_lit, ssid_lit, disconnect_lit,
             b3_sec_present() ? "true" : "false",
             b3_sec_provisioned() ? "true" : "false",
             gate_lit);
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
    char msg[192];
    const char *gate = b3_sec_status_text();
    if (gate) {
        snprintf(msg, sizeof(msg), "%s", gate);
    } else {
        snprintf(msg, sizeof(msg), "hashrate_khs=%.3f temp=%.1f",
                 m.hashrate_khs, b3_fpga_read_die_celsius());
    }
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
