// b3chain-gpuminer library root.
//
// The crate ships both a binary (`b3chain-gpuminer`) and a library so
// integration tests in `tests/` can import internals without going
// through the CLI.
//
// Module map:
//   util::*    -- target math, JSONL logger, misc helpers (no I/O,
//                  no CUDA -- pure functions, easy to test)
//   work::*    -- coinbase splice, merkle root, header serialise
//                  (all CPU side, port of the Python helpers)
//   stratum::* -- async TCP client, message types, job state
//   gpu::*     -- CUDA driver wrapper + work dispatcher (only built
//                  with the `cuda` feature)
//
// Public surface is intentionally small; the binary in src/main.rs
// is the supported entry point.

pub mod util;
pub mod work;
pub mod stratum;

#[cfg(feature = "cuda")]
pub mod gpu;
