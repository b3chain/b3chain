# B3Miner-1 Firmware (ESP32-S3)

Host firmware for the B3Miner-1 standalone card (XCKU5P + ESP32-S3 + Ethernet).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ app_main.c          Boot, NVS, netif, task spawn            │
├─────────────────────────────────────────────────────────────┤
│ b3_stratum_v1       Stratum V1 (primary) — mirrors gpuminer  │
│ b3_stratum_v2       Stratum V2 skeleton (Noise + framing)     │
│ b3_work             Job → header → FPGA work packets          │
│ b3_fpga             SPI register map + share IRQ              │
│ b3_web              HTTP REST + WebSocket dashboard           │
│ b3_ota              HTTPS OTA + rollback                      │
│ b3_metrics          Hashrate, temps, Prometheus text export   │
│ b3_config           NVS pool URL, worker name, thresholds     │
│ b3_events           FreeRTOS event group + queues             │
└─────────────────────────────────────────────────────────────┘
         │ SPI 25 MHz                    │ TCP :3333 / :3336
         ▼                               ▼
    [XCKU5P FPGA]                   [B3Chain pool]
```

Wire protocol for Stratum V1 matches:
- `contrib/miner/b3chain-gpuminer/src/stratum/client.rs`
- `contrib/miner/b3chain-cpuminer.py`
- `doc/stratum.md`

PoW on FPGA implements **B3PoW-Scratch** (see design docs). Until the chain
activates that algorithm, set `CONFIG_B3_POW_LEGACY_DOUBLE_BLAKE3=y` in
`main/Kconfig.projbuild` for testnet against current double-BLAKE3 nodes.

## Build

```bash
cd contrib/miner/b3miner-firmware
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

Requires ESP-IDF v5.2+.

## Task map

| Task            | Priority | Stack  | Role                                      |
|-----------------|----------|--------|-------------------------------------------|
| stratum_v1      | 8        | 12 KB  | TCP NDJSON, handshake, job state          |
| fpga_worker     | 9        | 8 KB   | Push work, drain shares, scratchpad regen |
| web_server      | 5        | 8 KB   | esp_httpd REST + WS                       |
| metrics         | 4        | 4 KB   | Rolling hashrate, XADC poll               |
| ota_agent       | 3        | 6 KB   | Poll update server (optional)             |
| led_status      | 2        | 2 KB   | Power/link/mining LEDs                    |

## FPGA SPI register map

See `components/b3_fpga/include/b3_fpga_regs.h`.

## Fill-in checklist (skeleton → production)

- [ ] `b3_work_build_header()` — coinbase + merkle (port from gpuminer `work/`)
- [ ] `b3_stratum_v1_parse_notify()` — full notify decode + clean_jobs
- [ ] `b3_stratum_v2_*` — Noise XX handshake + SV2 template messages
- [ ] `b3_fpga_load_bitstream()` — SelectMAP or SPI slave config from flash
- [ ] `b3_web` — embed `web/dist/` SPA (build step in CMake)
- [ ] Sign OTA images with project key; enable Secure Boot V2 in sdkconfig
