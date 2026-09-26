#!/usr/bin/env python3
"""ICT-only ATECC608B-MAHDA-T provisioning. Never run this on a mining card.

The chip requires the Configuration zone to be locked before GenKey.
This script locks Configuration first, then:

  1. GenKey slot 0 (ECC P-256) and slot 5 (attestation)
  2. Fill slot 3 with 32 bytes from the chip RNG (AES key; GenKey is ECC-only)
  3. Write the pool authority pubkey into slot 1
  4. Write the release-signing pubkey into slot 2
  5. Write the 32-byte provisioning record into slot 4
  6. Lock the Data zone
  7. Sign a known 32-byte challenge with slot 0 and verify it

Firmware never calls this script. Without --confirm, --i2c-bus, and the
three slot payloads, the script exits before it imports cryptoauthlib
or opens a device.
"""

from __future__ import annotations

import argparse
import sys

# Fixed challenge. The fixture signs these 32 bytes with slot 0.
KNOWN_CHALLENGE = bytes.fromhex("b3" * 16)
I2C_ADDRESS = 0xC0
I2C_BAUD = 400_000


def main() -> int:
    parser = argparse.ArgumentParser(description="Factory ATECC608B provisioning")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Confirms this is the ICT fixture, not a mining card.",
    )
    parser.add_argument("--i2c-bus", type=int, help="Host I2C bus number for the fixture")
    parser.add_argument("--slot1-pubkey", help="128 hex chars, pool authority public key")
    parser.add_argument("--slot2-pubkey", help="128 hex chars, release-signing public key")
    parser.add_argument("--slot4-record", help="64 hex chars, 32-byte provisioning record")
    parser.add_argument(
        "--known-challenge",
        help="64 hex chars. Defaults to the fixture challenge.",
    )
    args = parser.parse_args()
    if not args.confirm:
        print("refusing: pass --confirm on the factory fixture only", file=sys.stderr)
        return 2

    challenge = KNOWN_CHALLENGE
    if args.known_challenge is not None:
        parsed = parse_hex(args.known_challenge, 32, "--known-challenge")
        if isinstance(parsed, int):
            return parsed
        challenge = parsed

    slot1 = parse_hex(args.slot1_pubkey, 64, "--slot1-pubkey")
    slot2 = parse_hex(args.slot2_pubkey, 64, "--slot2-pubkey")
    slot4 = parse_hex(args.slot4_record, 32, "--slot4-record")
    if args.i2c_bus is None or args.i2c_bus < 0:
        print("refusing: --i2c-bus is required so a default bus is not opened", file=sys.stderr)
        return 4
    if isinstance(slot1, int):
        return slot1
    if isinstance(slot2, int):
        return slot2
    if isinstance(slot4, int):
        return slot4

    try:
        import cryptoauthlib as cal
    except ImportError:
        print("cryptoauthlib is not installed; fixture host is not ready", file=sys.stderr)
        return 3

    try:
        provision(cal, args.i2c_bus, slot1, slot2, slot4, challenge)
    except Exception as exc:
        print(f"provisioning failed: {exc}", file=sys.stderr)
        return 5
    return 0


def parse_hex(text: str | None, size: int, flag: str) -> bytes | int:
    if not text or len(text) != size * 2:
        print(f"refusing: {flag} must be {size * 2} hex chars", file=sys.stderr)
        return 4
    try:
        return bytes.fromhex(text)
    except ValueError:
        print(f"refusing: {flag} is not hex", file=sys.stderr)
        return 4


def provision(cal, bus: int, slot1: bytes, slot2: bytes, slot4: bytes, challenge: bytes) -> None:
    required = (
        "ATCA_SUCCESS",
        "ATCA_ZONE_DATA",
        "cfg_ateccx08a_i2c_default",
        "atcab_init",
        "atcab_release",
        "atcab_is_locked",
        "atcab_genkey",
        "atcab_random",
        "atcab_write_bytes_zone",
        "atcab_write_pubkey",
        "atcab_lock_config_zone",
        "atcab_lock_data_zone",
        "atcab_sign",
        "atcab_verify_extern",
        "atcab_read_serial_number",
    )
    missing = [name for name in required if not hasattr(cal, name)]
    if missing:
        raise RuntimeError("cryptoauthlib is missing " + ", ".join(missing))

    cfg = cal.cfg_ateccx08a_i2c_default()
    devtype = getattr(cal, "ATECC608", None)
    if devtype is None:
        devtype = getattr(cal, "ATECC608A", None)
    if devtype is None:
        raise RuntimeError("cryptoauthlib has no ATECC608 devtype")
    cfg.devtype = devtype
    i2c = i2c_cfg(cfg)
    i2c.bus = bus
    i2c.baud = I2C_BAUD
    if hasattr(i2c, "slave_address"):
        i2c.slave_address = I2C_ADDRESS
    elif hasattr(i2c, "address"):
        i2c.address = I2C_ADDRESS
    else:
        raise RuntimeError("cryptoauthlib i2c cfg has no address field")

    status = cal.atcab_init(cfg)
    if status != cal.ATCA_SUCCESS:
        raise RuntimeError(f"atcab_init failed ({status})")
    try:
        serial = read_out(cal, cal.atcab_read_serial_number, 9)
        print("serial", serial.hex())

        # GenKey is rejected while Configuration is unlocked.
        if not zone_locked(cal, config_zone(cal)):
            check(cal, cal.atcab_lock_config_zone(), "lock config")
        if not zone_locked(cal, config_zone(cal)):
            raise RuntimeError("configuration zone is still unlocked")

        slot0_pub = read_out(cal, lambda buf: cal.atcab_genkey(0, buf), 64)
        read_out(cal, lambda buf: cal.atcab_genkey(5, buf), 64)
        aes_key = read_out(cal, cal.atcab_random, 32)
        check(cal, cal.atcab_write_bytes_zone(cal.ATCA_ZONE_DATA, 3, 0, aes_key, len(aes_key)), "write slot 3")
        check(cal, cal.atcab_write_pubkey(1, slot1), "write slot 1")
        check(cal, cal.atcab_write_pubkey(2, slot2), "write slot 2")
        check(cal, cal.atcab_write_bytes_zone(cal.ATCA_ZONE_DATA, 4, 0, slot4, len(slot4)), "write slot 4")

        if not zone_locked(cal, data_zone(cal)):
            check(cal, cal.atcab_lock_data_zone(), "lock data")

        sig = read_out(cal, lambda buf: cal.atcab_sign(0, challenge, buf), 64)
        if not verified(cal, challenge, sig, slot0_pub):
            raise RuntimeError("known challenge did not verify")
        print("slot0", slot0_pub.hex())
        print("challenge ok")
    finally:
        cal.atcab_release()


def i2c_cfg(cfg):
    target = cfg.cfg if hasattr(cfg, "cfg") else cfg
    i2c = getattr(target, "atcai2c", None)
    if i2c is None:
        raise RuntimeError("cryptoauthlib cfg has no atcai2c")
    return i2c


def config_zone(cal) -> int:
    return getattr(cal, "LOCK_ZONE_CONFIG", 0)


def data_zone(cal) -> int:
    return getattr(cal, "LOCK_ZONE_DATA", 1)


def check(cal, status, step: str) -> None:
    if isinstance(status, tuple):
        status = status[0]
    if status != cal.ATCA_SUCCESS:
        raise RuntimeError(f"{step} failed ({status})")


def zone_locked(cal, zone: int) -> bool:
    result = cal.atcab_is_locked(zone)
    if isinstance(result, tuple) and len(result) >= 2:
        check(cal, result[0], "is_locked")
        return bool(result[1])
    raise RuntimeError("atcab_is_locked did not return (status, locked)")


def read_out(cal, fn, size: int) -> bytes:
    buf = bytearray(size)
    result = fn(buf)
    if isinstance(result, tuple):
        check(cal, result[0], fn.__name__ if hasattr(fn, "__name__") else "read")
        data = result[1] if len(result) > 1 and result[1] is not None else buf
        return bytes(data)[:size]
    check(cal, result, fn.__name__ if hasattr(fn, "__name__") else "read")
    return bytes(buf)


def verified(cal, message: bytes, signature: bytes, pubkey: bytes) -> bool:
    result = cal.atcab_verify_extern(message, signature, pubkey)
    if isinstance(result, tuple) and len(result) >= 2:
        check(cal, result[0], "verify")
        return bool(result[1])
    buf = bytearray(1)
    result = cal.atcab_verify_extern(message, signature, pubkey, buf)
    if isinstance(result, tuple):
        check(cal, result[0], "verify")
        return bool(result[1]) if len(result) > 1 else bool(buf[0])
    check(cal, result, "verify")
    return bool(buf[0])


if __name__ == "__main__":
    raise SystemExit(main())
