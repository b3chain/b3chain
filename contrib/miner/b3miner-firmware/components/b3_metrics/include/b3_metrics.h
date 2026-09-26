#pragma once

#include <stdint.h>

typedef struct {
    float hashrate_khs;
    float last_completed_khs;
    uint32_t shares_accepted;
    uint32_t shares_rejected;
    uint32_t uptime_s;
    uint32_t measurement_age_s;
    uint32_t job_epoch;
    uint64_t hashes_total;
    uint8_t stratum_connected;
    uint32_t wifi_disconnects;
} b3_metrics_snapshot_t;

void b3_metrics_init(void);
void b3_metrics_report_hashrate(float khs);
void b3_metrics_note_fpga_count(uint32_t raw_count, uint32_t job_epoch, int batch_done);
void b3_metrics_set_connected(int connected);
void b3_metrics_share_accepted(void);
void b3_metrics_share_rejected(void);
void b3_metrics_note_wifi_disconnect(void);
void b3_metrics_get_snapshot(b3_metrics_snapshot_t *out);
