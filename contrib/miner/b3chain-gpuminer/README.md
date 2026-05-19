# b3chain-gpuminer (deprecated, retained for reference)

> **Status: deprecated. Does not produce valid B3Chain mainnet or
> testnet shares.**
>
> This GPU miner targets the retired double-BLAKE3 PoW
> (`BLAKE3(BLAKE3(80-byte header))`) that B3Chain ran in early
> development. The live consensus algorithm is **B3PoW-Scratch v1.1**
> (see [`contrib/miner/b3miner-rtl/SPEC.md`](../b3miner-rtl/SPEC.md)).
> B3PoW-Scratch is **GPU-hostile by design** — its 1 MiB sequential
> data-dependent scratchpad destroys GPU throughput — so this tree is
> not being ported. It is kept as a complete reference for the
> previous algorithm and as a worked example of the Stratum V1 +
> JSONL pipeline.
>
> If you want a working B3Chain miner today, use the FPGA reference at
> [`contrib/miner/b3miner-firmware/`](../b3miner-firmware/) or the
> Python reference at
> [`contrib/miner/b3chain-cpuminer.py`](../b3chain-cpuminer.py)
> (correctness reference only, not competitive on mainnet).
>
> See [`doc/b3chain-pow-design.md`](../../../doc/b3chain-pow-design.md)
> § "Not 'GPU-proof', but GPU-hostile" for the rationale, and
> [`doc/analysis/FPGA-FEASIBILITY.md`](../../../doc/analysis/FPGA-FEASIBILITY.md)
> for the quantitative argument.

NVIDIA CUDA GPU miner for the **retired** double-BLAKE3 B3Chain PoW.

Computes `BLAKE3(BLAKE3(80-byte header))` directly on the GPU and submits
shares over Stratum V1, with a JSONL log format that is byte-compatible
with [`b3chain-cpuminer.py`](../b3chain-cpuminer.py) so the live
[mining dashboard](../tests/mining_dashboard.py) can ingest it without
modification.

## Status

This is **v0.1, deprecated**. It is layered out in four phases (see
`.cursor/plans/b3chain_cuda_gpu_miner_*.plan.md`):

| Phase | Status | Exit criterion |
|------:|:-------|:----------------|
| A     | done   | Kernel produces bitwise-identical output to the host `blake3` crate over 100k random 80-byte headers (`cargo test kernel_correctness`) |
| B     | done   | Async Stratum V1 client completes a full handshake against an in-process mock server (`cargo test stratum_handshake`) |
| C     | done   | Driver wires Phase A + B together; emits `share_pre_submit` + `share_submit` JSONL matching the Python miner schema |
| D     | partial| Block/grid + multi-stream tuning, dashboard backend selector, multi-GPU |

## Build prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| NVIDIA driver | >= 535 | CUDA 12.x runtime is bundled into the driver. |
| CUDA Toolkit  | 12.x   | `build.rs` shells out to `nvcc`. Set `CUDA_PATH` or put `nvcc` on PATH. |
| MSVC Build Tools 2022 | -- | Windows only -- `nvcc` requires `cl.exe`. |
| Rust          | 1.75+ stable | install via `rustup`. |

The `cudarc` crate uses runtime-loaded CUDA driver API, so the resulting
`.exe` does **not** statically depend on `nvcuda.dll`. Any machine with
the NVIDIA driver installed can run a binary built on a different host
(driver version permitting).

### Picking a compute capability

`build.rs` defaults to `sm_75` (Turing -- covers GTX 1660 / RTX
2060/2070/2080 / T4). To override, set `CUDA_ARCH` before building:

```powershell
$env:CUDA_ARCH = "sm_86"   # RTX 30xx (Ampere)
cargo build --release
```

`sm_75` PTX is forward-compatible with newer GPUs through the driver's
JIT, so the default works on Ampere/Ada/Blackwell without any change --
just at a (very small) startup cost.

## Build & test

```powershell
# Standard build (links the CUDA kernel via build.rs).
cd contrib/miner/b3chain-gpuminer
cargo build --release

# Phase-A correctness gate -- requires a CUDA device.
cargo test --release kernel_correctness

# Phase-B handshake test -- pure CPU, no GPU needed.
cargo test --release stratum_handshake

# All unit tests (target math, URL parser, merkle, header layout, etc.).
cargo test --release
```

If you want to `cargo check` on a machine without the CUDA Toolkit,
disable the kernel build:

```powershell
cargo check --no-default-features
```

The crate still compiles, but the resulting binary will refuse to start
("CUDA toolchain missing").

## Run

```powershell
.\target\release\b3chain-gpuminer.exe `
    --stratum stratum+tcp://pool.b3chain.org:3333 `
    --user    yourname@b3chain.org.gpu1 `
    --pass    x `
    --json-log mining.jsonl
```

CLI flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--stratum`     | -- (required) | `stratum+tcp://host:port` |
| `--user`        | -- (required) | Worker username, e.g. `alice@b3chain.org.gpu1` |
| `--pass`        | `x`           | Stratum password (the pool ignores the value but requires non-empty) |
| `--useragent`   | `b3chain-gpuminer/0.1` | Sent with `mining.subscribe` |
| `--json-log`    | -- (optional) | Append-only JSONL events file (consumed by the dashboard) |
| `--gpu`         | `0` | CUDA device ordinal |
| `--batch-size`  | `16777216` (2^24) | Nonces per kernel launch -- tune for your GPU |
| `--block-size`  | `256` | CUDA threads per block |
| `--default-diff`| `1024` | Initial share difficulty before the pool sends `mining.set_difficulty` |

## Architecture (one paragraph)

A single tokio task owns the Stratum TCP socket and dispatches inbound
notifications (`mining.notify`, `mining.set_difficulty`, ...) into a
`tokio::sync::watch<MiningState>` channel. The GPU driver task watches
that state, builds the coinbase / merkle / 80-byte header on the host,
and calls `MinerKernel::launch()` for each 16M-nonce batch. Candidates
that beat the share target are pushed onto an mpsc::channel that the
Stratum task drains -- every `mining.submit` and its response goes
through that one TCP socket. The driver retains a per-share-seq map of
the deep-detail payload (header_hex, pow_hash_le, coinbase, merkle,
etc.) so when the response arrives, the response handler can emit a
`share_submit` JSONL event with the full schema the dashboard expects.

The kernel itself (`kernels/miner.cu` + `kernels/blake3.cuh`) is ~250
lines of CUDA C: a straight implementation of the BLAKE3 compression
function with the chunk-tree / parent-node code paths stripped out
(both hashes are <=1024 bytes -- one chunk -- and we always set the
ROOT flag on the last block).

## Wire-protocol contract

This miner targets **Stratum V1** specifically. The pool implementation
is at [`contrib/testnet/pool/`](../../testnet/pool/); the on-wire
behaviour we replicate (line-delimited JSON, request/response by `id`,
notifications with `id == null`) lives in
[`contrib/testnet/pool/src/stratum/client.ts`](../../testnet/pool/src/stratum/client.ts).

The exact `mining.notify` payload shape and the `coinb1 || en1 || en2 ||
coinb2` coinbase splice are documented in
[`b3chain-cpuminer.py`](../b3chain-cpuminer.py) -- this Rust port keeps
the same byte layout so a side-by-side diff of two miners' JSONL logs
lets you eyeball-verify correctness.

## Performance expectations

This is intentionally a v0.1 single-stream implementation. Measured
roughly:

| GPU class   | Expected throughput | Speedup vs. Python miner |
|-------------|--------------------:|-------------------------:|
| GTX 1660    | ~250-400 MH/s       | ~50-80x                  |
| RTX 2060    | ~600-900 MH/s       | ~120-180x                |
| RTX 3060    | ~1.0-1.5 GH/s       | ~200-300x                |
| RTX 4070    | ~2.0-3.0 GH/s       | ~400-600x                |

These are kernel-bound numbers; the host->device->host roundtrip per
batch costs ~0.1-0.5 ms which is amortised across 16M nonces.

Phase D will explore multi-stream pipelining, register-resident
compression state, and per-arch tuning sweeps for another ~2x.

## Troubleshooting

**`miner.ptx is the build-time stub (CUDA toolchain missing)`** --
`build.rs` could not find `nvcc`. Install the CUDA Toolkit 12.x and set
`CUDA_PATH` or put `<cuda>\bin` on PATH, then `cargo clean && cargo
build --release`.

**`CUDA_ERROR_NO_DEVICE`** -- the NVIDIA driver isn't loaded or no GPU
is visible. Check `nvidia-smi`.

**`PTX version mismatch`** -- the PTX was compiled for a newer arch
than your driver supports. Lower `CUDA_ARCH` (e.g. `sm_70` for
Pascal/Volta/Turing-compatible) and rebuild.

**Pool rejects every share** -- almost certainly a BLAKE3 endianness
mismatch, which Phase A's `kernel_correctness` test is specifically
designed to catch. Run that test first.
