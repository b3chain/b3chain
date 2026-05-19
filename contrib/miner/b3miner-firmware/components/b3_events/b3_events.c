#include "b3_events.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

static EventGroupHandle_t s_ev;
static QueueHandle_t s_share_q;

void b3_events_init(void)
{
    s_ev = xEventGroupCreate();
    s_share_q = xQueueCreate(16, sizeof(b3_share_event_t));
}

EventGroupHandle_t b3_events_get_group(void) { return s_ev; }

QueueHandle_t b3_events_share_queue(void) { return s_share_q; }

void b3_events_post(b3_event_bits_t bit)
{
    xEventGroupSetBits(s_ev, bit);
}

void b3_events_clear(b3_event_bits_t bit)
{
    xEventGroupClearBits(s_ev, bit);
}

bool b3_events_wait_bits(b3_event_bits_t mask, TickType_t timeout)
{
    EventBits_t got = xEventGroupWaitBits(s_ev, mask, pdTRUE, pdFALSE, timeout);
    return (got & mask) != 0;
}
