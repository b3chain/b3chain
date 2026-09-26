# B3PoW-Scratch measurement ledger

Each row is `measured`, `modeled`, or `unmeasured`. A modeled row is an
equation or a place-and-route report. It is not a stopwatch on a board
or a GPU.

| Item | Class | Value | Source |
|---|---|---|---|
| CPU honest Python reference | measured | single-digit H/s per core | [`bench-b3pow-cpu.py`](bench-b3pow-cpu.py) cold/warm rows |
| Checkpoint-replay mix-step ratio, reference header, 512 KiB cap | measured | about 1.20×10³ (1,529 dirty misses, 2,451,436 mix steps) | [`b3pow_reduced.py`](../../miner/b3miner-rtl/ref/b3pow_reduced.py) on header nonce 4, `prev = bytes(range(32))` |
| Same, 256 KiB cap | measured | about 2.39×10³ (3,347 dirty misses) | same run |
| Same, 128 KiB cap | measured | about 3.11×10³ (4,612 dirty misses) | same run |
| SPEC §8.C floors | claimed minimum | 2× / 4× / 8× at 512 / 256 / 128 KiB | [`test_reduced_memory.py`](../../miner/b3miner-rtl/ref/tests/test_reduced_memory.py). A cheaper hash-equivalent run lowers the floor. |
| XOF rebuild after a write | measured negative | pad byte differs from `BLAKE3-XOF(prev \|\| i)` | `test_xof_rebuild_diverges_after_write` |
| FPGA KU5P closed route | modeled | about 5.5 kH/s, one pipeline, 456/480 BRAM | [`TIMING_CLOSURE.md`](../../miner/b3miner-rtl/docs/TIMING_CLOSURE.md) |
| FPGA KU5P SPEC §8.D 49 µs / 20.4 kH/s | superseded model | pre-route 6-cycle estimate | [`SPEC.md`](../../miner/b3miner-rtl/SPEC.md) §8.D |
| Whitepaper eight-pipeline ~8 MH/s | superseded model | one iteration per cycle, eight pipelines | replaced in whitepaper §6.1 |
| GPU RTX 4090 ~400 H/s | unmeasured | one stalled pipeline at ~2.5 ms, not a device rate | no in-tree v1.1 GPU miner |
| On-card KU5P hashrate | unmeasured | — | waits on a pool soak |

The checkpoint-replay charges are one strategy and one header. Nested
misses inside a replay are not added, so the charge is a lower bound
for that strategy. Another strategy can be cheaper. The CI floors stay
at 2× / 4× / 8× until a hash-equivalent run beats one.

`bench-b3pow-cpu.py` writes a `reduced-<cap>KiB` row. The `note` field
carries `mix_ratio`, `floor`, `dirty_misses`, `mix_steps`, and
`peak_bytes`. Wall-clock on that row is not a pass/fail gate.
