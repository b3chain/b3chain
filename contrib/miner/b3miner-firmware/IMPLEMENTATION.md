# Implementation order — skeleton → EVT

## Phase 1 — Bring-up (week 1–2) ✅ DONE in skeleton

1. ✅ ESP32-S3 devkit, Ethernet (LAN8720A) bring-up — `app_main.c`
2. ✅ `b3_fpga_sim.c` behind `CONFIG_B3_FPGA_SIM=y` — generates synthetic shares
3. ✅ `b3_stratum_v1` notify parser — full 9-field decode using cJSON
4. **Try it now**: see "Quick bring-up" below

## Phase 2 — Work layer (week 3–4)

1. Port `b3_work_build_header()` from gpuminer `work/header.rs` + `merkle.rs`.
2. Add BLAKE3 (use ESP-IDF component or `blake3` C reference).
3. Wire `b3_work_build_pow_seed()` for legacy double-BLAKE3 testnet.
4. Replace sim's fake hash with a real on-host (BLAKE3-on-ESP32) check so
   the sim can produce *valid* shares when run against a regtest pool.

## Phase 3 — Real FPGA (week 5–8)

1. Synthesize KU5P bitstream with SPI slave + register map matching `b3_fpga_regs.h`.
2. Implement `b3_fpga_load_bitstream_from_flash()` (SelectMAP).
3. Set `CONFIG_B3_FPGA_SIM=n`, verify same Stratum loop works with real silicon.
4. Byte-level test: ESP32 writes job, FPGA returns known test vector nonce.

## Phase 4 — Product (week 9–12)

1. Add response-correlation map for `mining.submit` (mirror gpuminer's `pending` map).
2. Complete WebSocket handler (`httpd_ws_send_frame`).
3. WiFi captive portal for first-time pool config (optional).
4. OTA manifest server + Secure Boot V2 signing pipeline.
5. FCC/CE pre-scan.
6. **Secure element (ATECC608B) integration** — see Phase 4.6 below.

### Phase 4.6 — Secure element integration

Hardware spec for the chip lives in
[`../b3miner-hardware/SCHEMATIC.md`](../b3miner-hardware/SCHEMATIC.md)
§6.7 (ATECC608B-MAHDA-T on I²C, GPIO 1 = SDA, GPIO 2 = SCL).

1. Pull in `espressif/cryptoauthlib` ESP-IDF managed component
   (Microchip's official BSD-3-Clause library). Confirm `idf.py
   add-dependency "espressif/cryptoauthlib"` lands the latest
   v3.7.x and that `CONFIG_ATCA_HAL_I2C=y` is set.
2. Create new component `components/b3_sec/` exposing the wrapper
   API defined in SCHEMATIC.md §6.7.6:
   - `b3_sec_init(sda_gpio, scl_gpio)` — open `I2C_NUM_0` at
     400 kHz, register the cryptoauthlib HAL, run `atcab_info()`,
     log the 9-byte serial.
   - `b3_sec_serial()` — read once at boot, cache.
   - `b3_sec_sign_p256(slot, msg32, sig64)` — `atcab_sign()`.
   - `b3_sec_verify_p256(pub64, msg32, sig64)` — `atcab_verify_extern()`.
   - `b3_sec_random(buf, len)` — chunked `atcab_random()` calls.
   - `b3_sec_aes_encrypt_block(slot, in16, out16)` — `atcab_aes()`.
3. Wire `app_main()` boot sequence (insertion order):
   ```c
   ESP_ERROR_CHECK(b3_sec_init(PIN_SEC_I2C_SDA, PIN_SEC_I2C_SCL));
   uint8_t sn[9];
   if (b3_sec_serial(sn) == ESP_OK) {
       ESP_LOGI(TAG, "ATECC608B serial %02x%02x%02x%02x%02x%02x%02x%02x%02x",
                sn[0],sn[1],sn[2],sn[3],sn[4],sn[5],sn[6],sn[7],sn[8]);
   }
   /* Seed mbedTLS DRBG with on-chip TRNG before any TLS handshake */
   uint8_t seed[48];
   ESP_ERROR_CHECK(b3_sec_random(seed, sizeof(seed)));
   mbedtls_ctr_drbg_seed_with_personalization(&drbg, ..., seed, sizeof(seed));
   ```
4. Add `b3_sec_provisioning_required()` check at boot — if the
   ATECC Configuration Zone is unlocked (factory state), refuse
   to start mining tasks and return a deterministic web-UI
   message "Card unprovisioned — run factory fixture". This
   matches the bring-up §15.2 step 3 GO/NO-GO gate.
5. Modify `b3_stratum_v2.c` Noise XX handshake to sign with
   `b3_sec_sign_p256(0, ...)` instead of an mbedTLS-held key.
   No private key material ever touches ESP RAM after this swap.
6. Modify `b3_ota.c` manifest-fetch path: after sha256 verify,
   call `b3_sec_verify_p256(slot2_pubkey, manifest_sha256,
   manifest_sig)` against the slot-2 pubkey (cached at boot).
   Reject the OTA bundle if verify fails, even if Secure Boot
   V2 would have accepted the application binary itself.
7. Modify `b3_config.c` pool-password storage: encrypt with
   `b3_sec_aes_encrypt_block(3, pw, ct)` before
   `nvs_set_blob()`; decrypt symmetrically on read. NVS dumps
   from a stolen flash chip no longer leak the pool credential.
8. Add unit tests under `components/b3_sec/test/` running against
   the cryptoauthlib host-emulator (no hardware needed in CI).
9. Provisioning script (Python): `contrib/miner/b3miner-hardware/provisioning/atecc_provision.py`
   per [`../b3miner-hardware/SCHEMATIC.md`](../b3miner-hardware/SCHEMATIC.md)
   §16 item 10. Runs on the ICT fixture, **never** on a deployed card.

## Quick bring-up (no FPGA required)

```bash
cd b3chain/contrib/miner/b3miner-firmware
idf.py set-target esp32s3
idf.py menuconfig
  # Enable: B3Miner firmware → Use simulated FPGA backend (CONFIG_B3_FPGA_SIM=y)
  # Set:    B3Miner firmware → Default pool URL = stratum+tcp://pool.b3chain.org:3333
  # Set:    B3Miner firmware → Default worker user = <your-email>.<rigname>
idf.py build flash monitor
```

Expected log on success:

```
I (1234) b3_main: B3Miner-1 firmware boot
I (1240) b3_fpga_sim: FPGA simulator armed (sim_khs=20000 share_every=10000 ms)
I (1250) b3_main: Starting Stratum V1 client
I (1260) b3_main: All tasks started — mining when pool job arrives
I (2500) b3_main: Got IP: 192.168.1.42
I (2600) stratum_v1: connecting to pool.b3chain.org:3333 (attempt 1)
I (2900) stratum_v1: subscribed en1=0000003f (4 B) en2_size=4
I (3000) stratum_v1: authorized as alice@example.com.rig1
I (3050) stratum_v1: set_difficulty -> 65536.000
I (3100) stratum_v1: notify job=00012ab epoch=1 ver=0x20000000 bits=0x1d00ffff ...
I (3150) b3_fpga_sim: job submitted: epoch=1 nonces=[0x00000000,0x00100000)
I (13150) b3_fpga_sim: share latched: nonce=0x000a7e2c epoch=1
I (13160) stratum_v1: -> submit job=00012ab nonce=000a7e2c en2=00000000 ...
W (13180) stratum_v1: <- response id=4 REJECTED ["23","Low difficulty share"]
```

The pool will reject sim shares (sim's fake hash never satisfies the share
target). That's intentional — it confirms the full plumbing works without
mining any real blocks on the testnet.

## Critical FILL IN markers remaining

| File | Marker |
|------|--------|
| `b3_work.c` | `b3_work_build_header`, `b3_work_build_pow_seed`, merkle/coinbase |
| `b3_stratum_v1.c` | TLS (`stratum+ssl://`), submit response correlation |
| `b3_stratum_v2.c` | entire Noise/SV2 stack; replace mbedTLS sign with `b3_sec_sign_p256(0,…)` |
| `b3_fpga.c` | `b3_fpga_load_bitstream_from_flash` (SelectMAP) |
| `b3_web.c` | WebSocket frames, auth on POST /config |
| `b3_ota.c` | manifest fetch + sha256 verify + `b3_sec_verify_p256` against slot 2 |
| `b3_sec.c` | **NEW** — entire component (Phase 4.6); wraps cryptoauthlib |
| `b3_config.c` | encrypt pool password with `b3_sec_aes_encrypt_block(3,…)` before NVS commit |
| `app_main.c` | WiFi provisioning fallback; `b3_sec_init()` + DRBG seed; provisioning-required gate |
