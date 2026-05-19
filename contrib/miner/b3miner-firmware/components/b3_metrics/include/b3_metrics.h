#pragma once

#include <stdint.h>

typedef struct {
    float hashrate_khs;
    uint32_t shares_accepted;
    uint32_t shares_rejected;
    uint32_t uptime_s;
    uint64_t hashes_total;
} b3_metrics_snapshot_t;

void b3_metrics_init(void);
void b3_metrics_report_hashrate(float khs);
void b3_metrics_share_accepted(void);
void b3_metrics_share_rejected(void);
void b3_metrics_get_snapshot(b3_metrics_snapshot_t *out);
