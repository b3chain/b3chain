#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"

typedef enum {
    B3_EVT_ETH_UP       = BIT0,
    B3_EVT_ETH_DOWN     = BIT1,
    B3_EVT_JOB_NEW      = BIT2,
    B3_EVT_JOB_STALE    = BIT3,
    B3_EVT_SHARE_FOUND  = BIT4,
    B3_EVT_FPGA_READY   = BIT5,
    B3_EVT_OTA_PENDING  = BIT6,
} b3_event_bits_t;

typedef struct {
    uint32_t job_epoch;
    uint32_t nonce;
    uint32_t ntime;
    uint8_t  extranonce2[4];
    uint8_t  pow_hash_le[32];
    bool     meets_network_target;
} b3_share_event_t;

void b3_events_init(void);
EventGroupHandle_t b3_events_get_group(void);
QueueHandle_t b3_events_share_queue(void);
void b3_events_post(b3_event_bits_t bit);
void b3_events_clear(b3_event_bits_t bit);
bool b3_events_wait_bits(b3_event_bits_t mask, TickType_t timeout);
