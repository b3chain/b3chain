/**
 * @file app_main.c
 * @brief B3Miner-1 entry: NVS, Ethernet, task spawn.
 *
 * TRIGGER  → power-on / reset
 * PROCESS  → FreeRTOS tasks (stratum, fpga_worker, web, metrics, ota)
 * RESULT   → shares submitted to pool; dashboard on :80
 * BYPASS   → config portal if no pool URL in NVS (WiFi AP mode — FILL IN)
 */

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#if CONFIG_B3_NETWORK_ETHERNET
#include "esp_eth.h"
#include "esp_mac.h"
#endif
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "b3_config.h"
#include "b3_events.h"
#include "b3_fpga.h"
#include "b3_metrics.h"
#include "b3_ota.h"
#include "b3_stratum_v1.h"
#include "b3_stratum_v2.h"
#include "b3_web.h"

static const char *TAG = "b3_main";

/* XCKU5P-2FFVB676 board contract: page 4/page 8. */
#define PIN_FPGA_IRQ        18   /* ESP32_RX1 <- FPGA AD14 */
#define PIN_LED_STATUS      4    /* ESP32_LED */

#if CONFIG_B3_NETWORK_ETHERNET
#define PIN_ETH_PHY_ADDR    0
#define PIN_ETH_PHY_RST     -1
#define PIN_ETH_MDC         23
#define PIN_ETH_MDIO        18
static esp_eth_handle_t s_eth_handle;
#endif

static void led_task(void *arg)
{
    (void)arg;
    gpio_set_direction(PIN_LED_STATUS, GPIO_MODE_OUTPUT);
    for (;;) {
        b3_metrics_snapshot_t snap;
        b3_metrics_get_snapshot(&snap);
        const bool mining = snap.hashrate_khs > 0.1f;
        gpio_set_level(PIN_LED_STATUS,
                       mining ? !gpio_get_level(PIN_LED_STATUS) : 1);
        vTaskDelay(pdMS_TO_TICKS(mining ? 200 : 1000));
    }
}

#if CONFIG_B3_NETWORK_ETHERNET
static void eth_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)data;
    if (base == ETH_EVENT) {
        switch (id) {
        case ETHERNET_EVENT_CONNECTED:
            ESP_LOGI(TAG, "Ethernet link up");
            b3_events_post(B3_EVT_ETH_UP);
            break;
        case ETHERNET_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "Ethernet link down");
            b3_events_post(B3_EVT_ETH_DOWN);
            break;
        case ETHERNET_EVENT_START:
            ESP_LOGI(TAG, "Ethernet started");
            break;
        case ETHERNET_EVENT_STOP:
            break;
        default:
            break;
        }
    }
}
#endif

#if CONFIG_B3_NETWORK_WIFI
static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    (void)arg;
    (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        b3_events_post(B3_EVT_ETH_DOWN);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        b3_events_post(B3_EVT_ETH_UP);
        b3_web_on_got_ip(arg, base, id, data);
    }
}
#endif

static esp_err_t init_network(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
#if CONFIG_B3_NETWORK_WIFI
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL));
    wifi_config_t wifi = {0};
    strlcpy((char *)wifi.sta.ssid, CONFIG_B3_WIFI_SSID,
            sizeof(wifi.sta.ssid));
    strlcpy((char *)wifi.sta.password, CONFIG_B3_WIFI_PASSWORD,
            sizeof(wifi.sta.password));
    wifi.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi));
    ESP_ERROR_CHECK(esp_wifi_start());
    return ESP_OK;
#else
    esp_netif_config_t cfg = ESP_NETIF_DEFAULT_ETH();
    esp_netif_t *netif = esp_netif_new(&cfg);

    eth_mac_config_t mac_cfg = ETH_MAC_DEFAULT_CONFIG();
    eth_esp32_emac_config_t emac_cfg = ETH_ESP32_EMAC_DEFAULT_CONFIG();
    emac_cfg.smi_gpio.mdc_num = PIN_ETH_MDC;
    emac_cfg.smi_gpio.mdio_num = PIN_ETH_MDIO;

    esp_eth_mac_t *mac = esp_eth_mac_new_esp32(&emac_cfg, &mac_cfg);

    eth_phy_config_t phy_cfg = ETH_PHY_DEFAULT_CONFIG();
    phy_cfg.phy_addr = PIN_ETH_PHY_ADDR;
    phy_cfg.reset_gpio_num = PIN_ETH_PHY_RST;
    esp_eth_phy_t *phy = esp_eth_phy_new_lan87xx(&phy_cfg);

    esp_eth_config_t eth_cfg = ETH_DEFAULT_CONFIG(mac, phy);
    ESP_ERROR_CHECK(esp_eth_driver_install(&eth_cfg, &s_eth_handle));
    ESP_ERROR_CHECK(esp_netif_attach(netif, esp_eth_new_netif_glue(s_eth_handle)));

    ESP_ERROR_CHECK(esp_event_handler_register(ETH_EVENT, ESP_EVENT_ANY_ID,
                                               &eth_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_ETH_GOT_IP,
                                               &b3_web_on_got_ip, NULL));

    ESP_ERROR_CHECK(esp_eth_start(s_eth_handle));
    return ESP_OK;
#endif
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    ESP_LOGI(TAG, "B3Miner-1 firmware boot");
    b3_config_init();
    b3_events_init();
    b3_metrics_init();
    ESP_ERROR_CHECK(b3_fpga_init(PIN_FPGA_IRQ));
#if CONFIG_B3_FPGA_BOOT_SELFTEST
    ESP_ERROR_CHECK(b3_fpga_run_selftest());
#endif
    ESP_ERROR_CHECK(init_network());

    /* Stratum: prefer V2 URL scheme if configured, else V1 */
    b3_runtime_config_t rcfg;
    b3_config_load_runtime(&rcfg);

    if (rcfg.stratum_proto == B3_STRATUM_PROTO_V2) {
        ESP_LOGI(TAG, "Starting Stratum V2 client");
        b3_stratum_v2_start(&rcfg);
    } else {
        ESP_LOGI(TAG, "Starting Stratum V1 client");
        b3_stratum_v1_start(&rcfg);
    }

    b3_fpga_worker_start();
    b3_web_start(CONFIG_B3_WEB_HTTP_PORT);
    b3_ota_start(CONFIG_B3_OTA_UPDATE_URL);

    xTaskCreate(led_task, "led", 2048, NULL, 2, NULL);

    ESP_LOGI(TAG, "All tasks started — mining when pool job arrives");
}
