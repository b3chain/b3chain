/**
 * @file b3_fpga.c
 * @brief SPI bridge to KU5P control registers.
 *
 * LOOP: b3_fpga_worker_task polls IRQ + STATUS for shares (see b3_fpga_worker.c)
 */

#include "b3_fpga.h"

#include <inttypes.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "b3_fpga";

#define B3_FPGA_CTRL_START        (1u << 0)
#define B3_FPGA_CTRL_ABORT        (1u << 1)
#define B3_FPGA_CTRL_SCRATCH_INIT (1u << 2)

static spi_device_handle_t s_spi;
static SemaphoreHandle_t s_bus_mtx;
static int s_irq_gpio = -1;

/* Board SPI pins — B3Miner-1 rev A */
#define PIN_SPI_MOSI  11
#define PIN_SPI_MISO  13
#define PIN_SPI_SCLK  12
#define PIN_SPI_CS    10

/*
 * SPI wire format (see ../../b3miner-rtl/rtl/spi_slave.sv):
 *
 *   - 40-bit transaction, mode 0, MSB-first per byte.
 *   - Byte 0 = command: bit 7 = WR(1)/RD(0), bits 6:0 = word index.
 *   - Bytes 1..4 = 32-bit data, little-endian.
 *
 * The header file's `B3_FPGA_REG_*` constants are kept as byte offsets
 * for documentation; this function converts byte_offset -> word_index by
 * right-shifting by 2 before placing it on the wire.  That gives us 128
 * addressable words = 512 bytes -- enough to cover the full register map
 * including REG_POW_HASH at byte offset 0x100 (= word index 0x40).
 */
static esp_err_t reg_xfer(uint16_t reg_byte_addr, bool write, uint32_t *word)
{
    if (!word) {
        return ESP_ERR_INVALID_ARG;
    }
    if ((reg_byte_addr & 0x03u) != 0u) {
        ESP_LOGE(TAG, "reg_xfer: unaligned byte address 0x%03x", reg_byte_addr);
        return ESP_ERR_INVALID_ARG;
    }
    uint8_t word_idx = (uint8_t)((reg_byte_addr >> 2) & 0x7Fu);

    uint8_t tx[8] = {0};
    uint8_t rx[8] = {0};
    tx[0] = (uint8_t)(write ? 0x80 : 0x00) | word_idx;
    if (write) {
        tx[1] = (uint8_t)(*word);
        tx[2] = (uint8_t)(*word >> 8);
        tx[3] = (uint8_t)(*word >> 16);
        tx[4] = (uint8_t)(*word >> 24);
    }

    /* Full 40 clocks for BOTH read and write -- the slave needs the
     * extra 32 SCK edges to drive MISO with the register contents. */
    spi_transaction_t t = {
        .length = 40,
        .rxlength = 40,
        .tx_buffer = tx,
        .rx_buffer = rx,
    };

    xSemaphoreTake(s_bus_mtx, portMAX_DELAY);
    esp_err_t err = spi_device_polling_transmit(s_spi, &t);
    xSemaphoreGive(s_bus_mtx);
    if (err != ESP_OK) {
        return err;
    }
    if (!write) {
        *word = (uint32_t)rx[1] | ((uint32_t)rx[2] << 8) |
                ((uint32_t)rx[3] << 16) | ((uint32_t)rx[4] << 24);
    }
    return ESP_OK;
}

static esp_err_t reg_write32(uint16_t reg, uint32_t val)
{
    return reg_xfer(reg, true, &val);
}

static esp_err_t reg_read32(uint16_t reg, uint32_t *val)
{
    return reg_xfer(reg, false, val);
}

static esp_err_t reg_write_block(uint16_t base_reg, const void *data, size_t len)
{
    const uint32_t *w = (const uint32_t *)data;
    for (size_t i = 0; i < len / 4; ++i) {
        ESP_ERROR_CHECK(reg_write32((uint16_t)(base_reg + i * 4), w[i]));
    }
    return ESP_OK;
}

static esp_err_t reg_read_block(uint16_t base_reg, void *data, size_t len)
{
    uint32_t *w = (uint32_t *)data;
    for (size_t i = 0; i < len / 4; ++i) {
        ESP_ERROR_CHECK(reg_read32((uint16_t)(base_reg + i * 4), &w[i]));
    }
    return ESP_OK;
}

static void IRAM_ATTR fpga_irq_isr(void *arg)
{
    (void)arg;
    /* Defer to worker — ISR stays minimal */
    BaseType_t hp = pdFALSE;
    /* FILL IN: notify fpga_worker via task notification if needed */
    if (hp) {
        portYIELD_FROM_ISR(hp);
    }
}

esp_err_t b3_fpga_init(int irq_gpio)
{
    s_irq_gpio = irq_gpio;
    s_bus_mtx = xSemaphoreCreateMutex();

    spi_bus_config_t bus = {
        .mosi_io_num = PIN_SPI_MOSI,
        .miso_io_num = PIN_SPI_MISO,
        .sclk_io_num = PIN_SPI_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 4096,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_CH_AUTO));

    spi_device_interface_config_t dev = {
        .clock_speed_hz = CONFIG_B3_FPGA_SPI_MHZ * 1000 * 1000,
        .mode = 0,
        .spics_io_num = PIN_SPI_CS,
        .queue_size = 4,
    };
    ESP_ERROR_CHECK(spi_bus_add_device(SPI3_HOST, &dev, &s_spi));

    if (irq_gpio >= 0) {
        gpio_config_t io = {
            .pin_bit_mask = 1ULL << irq_gpio,
            .mode = GPIO_MODE_INPUT,
            .pull_down_en = GPIO_PULLDOWN_ENABLE,
            .intr_type = GPIO_INTR_POSEDGE,
        };
        ESP_ERROR_CHECK(gpio_config(&io));
        ESP_ERROR_CHECK(gpio_install_isr_service(0));
        ESP_ERROR_CHECK(gpio_isr_handler_add(irq_gpio, fpga_irq_isr, NULL));
    }

    uint32_t id = 0;
    ESP_ERROR_CHECK(reg_read32(B3_FPGA_REG_ID, &id));
    if (id != B3_FPGA_MAGIC) {
        ESP_LOGW(TAG, "FPGA ID mismatch: 0x%08" PRIx32 " (expected 0x%08x)", id, B3_FPGA_MAGIC);
        /* FILL IN: attempt bitstream load */
        ESP_ERROR_CHECK(b3_fpga_load_bitstream_from_flash());
        ESP_ERROR_CHECK(reg_read32(B3_FPGA_REG_ID, &id));
        if (id != B3_FPGA_MAGIC) {
            ESP_LOGE(TAG, "FPGA not responding after bitstream load");
            return ESP_ERR_NOT_FOUND;
        }
    }
    ESP_LOGI(TAG, "FPGA ready, ID=0x%08" PRIx32, id);
    return ESP_OK;
}

esp_err_t b3_fpga_load_bitstream_from_flash(void)
{
    /* FILL IN:
     * 1. Read bitstream from SPI flash partition or embedded blob
     * 2. Assert PROGRAM_B, pulse INIT, stream via SelectMAP or SPI slave
     * 3. Wait DONE high
     * See Xilinx UG470 "Configuration via SPI" for KU5P.
     */
    ESP_LOGW(TAG, "b3_fpga_load_bitstream_from_flash: STUB — no bitstream loaded");
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t b3_fpga_init_scratchpad(const uint8_t prev_hash[32])
{
    ESP_ERROR_CHECK(reg_write_block(B3_FPGA_REG_PREV_HASH, prev_hash, 32));
    ESP_ERROR_CHECK(reg_write32(B3_FPGA_REG_CTRL, B3_FPGA_CTRL_SCRATCH_INIT));
    /* Poll until scratch_ready */
    for (int i = 0; i < 5000; ++i) {
        uint32_t st = 0;
        ESP_ERROR_CHECK(reg_read32(B3_FPGA_REG_STATUS, &st));
        if (st & B3_FPGA_STATUS_SCRATCH) {
            return ESP_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    return ESP_ERR_TIMEOUT;
}

esp_err_t b3_fpga_submit_job(const b3_fpga_job_t *job)
{
    if (!job) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_ERROR_CHECK(reg_write_block(B3_FPGA_REG_SEED, job->seed, 32));
    ESP_ERROR_CHECK(reg_write32(B3_FPGA_REG_JOB_EPOCH, job->job_epoch));
    ESP_ERROR_CHECK(reg_write32(B3_FPGA_REG_NONCE_START, job->nonce_start));
    ESP_ERROR_CHECK(reg_write32(B3_FPGA_REG_NONCE_END, job->nonce_end));
    ESP_ERROR_CHECK(reg_write32(B3_FPGA_REG_CTRL, B3_FPGA_CTRL_START));
    return ESP_OK;
}

bool b3_fpga_poll_share(b3_fpga_share_t *out)
{
    uint32_t st = 0;
    if (reg_read32(B3_FPGA_REG_STATUS, &st) != ESP_OK) {
        return false;
    }
    if (!(st & B3_FPGA_STATUS_SHARE)) {
        return false;
    }
    if (out) {
        reg_read32(B3_FPGA_REG_NONCE_LO, &out->nonce);
        reg_read32(B3_FPGA_REG_NTIME, &out->ntime);
        reg_read32(B3_FPGA_REG_JOB_EPOCH, &out->job_epoch);
        reg_read_block(B3_FPGA_REG_POW_HASH, out->pow_hash_le, 32);
    }
    /* ACK share */
    reg_write32(B3_FPGA_REG_CTRL, B3_FPGA_CTRL_ABORT); /* bit clears share_valid in FPGA */
    return true;
}

uint32_t b3_fpga_read_hash_count(void)
{
    uint32_t v = 0;
    reg_read32(B3_FPGA_REG_HASH_COUNT, &v);
    return v;
}

float b3_fpga_read_die_celsius(void)
{
    uint32_t raw = 0;
    reg_read32(B3_FPGA_REG_TEMP_RAW, &raw);
    /* FILL IN: convert XADC raw to °C per UG480 */
    return (float)raw * 0.1f;
}
