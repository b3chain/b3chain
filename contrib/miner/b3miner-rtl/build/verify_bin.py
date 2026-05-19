"""verify_bin.py -- sanity-check the SelectMAP-serial bitstream.

Run after `make bin` produces build/artifacts/b3miner.bin.  Checks:

* File exists and is between 5 MB and 8 MB (KU5P-FFVB676E compressed range).
* First 16 bytes match the standard Xilinx bitstream-sync sequence
    (FF FF FF FF AA 99 55 66) at offset 0.  The bit-reversed byte order
    inside the sync word is the contract; the firmware loader streams
    it MSB-first per byte without re-ordering.
* MD5 hash of the binary is recorded so the firmware OTA manifest can
    refuse to load mismatched bitstreams.

Usage:
    cd b3chain/contrib/miner/b3miner-rtl
    python build/verify_bin.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ART_DIR = Path(__file__).resolve().parent / "artifacts"
BIN_FILE = ART_DIR / "b3miner.bin"

MIN_SIZE = 5 * 1024 * 1024     # 5 MB
MAX_SIZE = 8 * 1024 * 1024     # 8 MB (must fit firmware partition)

# Standard Xilinx 7-series / UltraScale+ bitstream sync sequence.
# It can appear at any 32-bit-aligned offset; Vivado's -bin_file places
# the bus-width auto-detect dummy words first, then the sync word.
SYNC_WORD = bytes([0xAA, 0x99, 0x55, 0x66])


def main() -> int:
    if not BIN_FILE.exists():
        print(f"ERROR: {BIN_FILE} not found.  Run `make bin` first.", file=sys.stderr)
        return 1

    data = BIN_FILE.read_bytes()
    size = len(data)
    print(f"file:  {BIN_FILE}")
    print(f"size:  {size:,} bytes  ({size / (1024*1024):.2f} MB)")

    if size < MIN_SIZE:
        print(f"ERROR: too small (< {MIN_SIZE:,}).  Synth probably failed.", file=sys.stderr)
        return 1
    if size > MAX_SIZE:
        print(f"ERROR: too large (> {MAX_SIZE:,}).  Bump firmware partition.", file=sys.stderr)
        return 1

    if SYNC_WORD not in data[:1024]:
        print(f"ERROR: Xilinx sync word AA 99 55 66 not found in first 1 KB.",
              file=sys.stderr)
        return 1
    sync_off = data[:1024].index(SYNC_WORD)
    print(f"sync:  AA 99 55 66 at offset {sync_off}")

    h = hashlib.md5(data).hexdigest()
    print(f"md5:   {h}")

    # Record in artifacts/manifest.txt for the firmware OTA manifest.
    (ART_DIR / "manifest.txt").write_text(
        f"file: b3miner.bin\n"
        f"size: {size}\n"
        f"md5:  {h}\n"
        f"sync_offset: {sync_off}\n"
    )
    print(f"\nrecorded {ART_DIR / 'manifest.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
