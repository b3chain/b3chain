#pragma once

#include "esp_event.h"

void b3_web_start(uint16_t port);
void b3_web_on_got_ip(void *arg, esp_event_base_t base, int32_t id, void *data);
