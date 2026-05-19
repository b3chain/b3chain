// CUDA device wrapper.
//
// This module owns a `CudaDevice`, the loaded PTX, and persistent
// device-side buffers for the search kernel. It exposes a single
// `MinerKernel::launch()` call that:
//
//   1. Copies the 80-byte header template into a persistent device
//      buffer (only when the template changes -- cheap to detect by
//      bytewise equality on the host side).
//   2. Copies the 32-byte share target into a persistent device buffer
//      (same change-detection optimisation).
//   3. Resets the result counter to 0.
//   4. Launches `nonce_count` threads (rounded up to grid * block).
//   5. Synchronously copies the result counter and any results back
//      and returns them.
//
// We don't pipeline (multiple in-flight launches) here -- that's
// Phase D. v0.1 is a single-stream loop.

use anyhow::{anyhow, Context, Result};
use cudarc::driver::{CudaDevice, CudaSlice, DeviceRepr, LaunchAsync, LaunchConfig};
use std::sync::Arc;

const PTX_BYTES: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/miner.ptx"));
const KERNEL_NAME_SEARCH: &str = "double_blake3_search";
const KERNEL_NAME_DUMP: &str = "double_blake3_dump";
const MODULE_NAME: &str = "b3chain_gpuminer";

/// Mirrors the C `b3::ShareCandidate` struct in kernels/miner.cu.
#[repr(C)]
#[derive(Copy, Clone, Debug)]
pub struct ShareCandidate {
    pub nonce: u32,
    pub hash_le: [u8; 32],
}

// Safety: ShareCandidate is plain old data with #[repr(C)] and no
// padding gaps that would expose uninit memory across the device-host
// boundary (the [u8; 32] starts at offset 4, total size = 36, alignment = 4).
unsafe impl DeviceRepr for ShareCandidate {}

pub struct KernelLaunch<'a> {
    pub header_template_le: &'a [u8; 80],
    pub share_target_le: &'a [u8; 32],
    pub nonce_start: u32,
    pub nonce_count: u32,
    pub block_size: u32,
}

#[derive(Debug, Clone)]
pub struct KernelResult {
    pub candidates: Vec<ShareCandidate>,
    /// True if the result counter exceeded the buffer size. Should
    /// never happen in v0.1 (we size the buffer to 64 entries; if a
    /// single launch produces 64 shares the share target is way too
    /// loose and the operator should raise it).
    pub overflow: bool,
}

const MAX_RESULTS: u32 = 64;

pub struct MinerKernel {
    dev: Arc<CudaDevice>,
    // Persistent device buffers.
    header_dev: CudaSlice<u8>,         // 80 bytes
    target_dev: CudaSlice<u8>,         // 32 bytes
    results_dev: CudaSlice<ShareCandidate>,
    counter_dev: CudaSlice<u32>,
    // Cached host copies for change detection.
    last_header: [u8; 80],
    last_target: [u8; 32],
    last_header_valid: bool,
    last_target_valid: bool,
}

impl MinerKernel {
    pub fn new(device_ordinal: usize) -> Result<Self> {
        let dev = CudaDevice::new(device_ordinal)
            .with_context(|| format!("opening CUDA device #{device_ordinal}"))?;

        // Refuse to load the stub PTX written by build.rs when the
        // CUDA toolchain is absent.
        if PTX_BYTES.len() < 256 {
            anyhow::bail!(
                "miner.ptx is the build-time stub (CUDA toolchain missing); \
                 install the CUDA Toolkit (>=12.x) and rebuild with `cargo build --release`."
            );
        }

        let ptx = std::str::from_utf8(PTX_BYTES)
            .map_err(|e| anyhow!("PTX is not UTF-8: {e}"))?
            .to_string();
        let ptx_owned = cudarc::nvrtc::Ptx::from_src(ptx);

        dev.load_ptx(
            ptx_owned,
            MODULE_NAME,
            &[KERNEL_NAME_SEARCH, KERNEL_NAME_DUMP],
        )
        .context("loading miner.ptx into CUDA module")?;

        let header_dev: CudaSlice<u8> =
            dev.alloc_zeros::<u8>(80).context("alloc header buffer")?;
        let target_dev: CudaSlice<u8> =
            dev.alloc_zeros::<u8>(32).context("alloc target buffer")?;
        let results_dev: CudaSlice<ShareCandidate> = dev
            .alloc_zeros::<ShareCandidate>(MAX_RESULTS as usize)
            .context("alloc result buffer")?;
        let counter_dev: CudaSlice<u32> =
            dev.alloc_zeros::<u32>(1).context("alloc result counter")?;

        Ok(Self {
            dev,
            header_dev,
            target_dev,
            results_dev,
            counter_dev,
            last_header: [0u8; 80],
            last_target: [0u8; 32],
            last_header_valid: false,
            last_target_valid: false,
        })
    }

    pub fn device(&self) -> &Arc<CudaDevice> {
        &self.dev
    }

    /// Run one batch on the GPU and block until results come back.
    pub fn launch(&mut self, plan: KernelLaunch<'_>) -> Result<KernelResult> {
        // Push header / target only when changed.
        if !self.last_header_valid || &self.last_header != plan.header_template_le {
            self.dev
                .htod_sync_copy_into(plan.header_template_le.as_slice(), &mut self.header_dev)
                .context("copy header template")?;
            self.last_header = *plan.header_template_le;
            self.last_header_valid = true;
        }
        if !self.last_target_valid || &self.last_target != plan.share_target_le {
            self.dev
                .htod_sync_copy_into(plan.share_target_le.as_slice(), &mut self.target_dev)
                .context("copy share target")?;
            self.last_target = *plan.share_target_le;
            self.last_target_valid = true;
        }

        // Reset result counter to 0.
        let zero = vec![0u32; 1];
        self.dev
            .htod_sync_copy_into(&zero, &mut self.counter_dev)
            .context("reset result counter")?;

        // Launch.
        let func = self
            .dev
            .get_func(MODULE_NAME, KERNEL_NAME_SEARCH)
            .ok_or_else(|| anyhow!("kernel {KERNEL_NAME_SEARCH} not loaded"))?;

        let block = plan.block_size.max(32).min(1024);
        let grid = (plan.nonce_count + block - 1) / block;
        let cfg = LaunchConfig {
            grid_dim: (grid, 1, 1),
            block_dim: (block, 1, 1),
            shared_mem_bytes: 0,
        };
        unsafe {
            func.launch(
                cfg,
                (
                    &self.header_dev,
                    &self.target_dev,
                    plan.nonce_start,
                    plan.nonce_count,
                    MAX_RESULTS,
                    &mut self.results_dev,
                    &mut self.counter_dev,
                ),
            )
        }
        .context("kernel launch")?;

        // Sync + read back.
        self.dev.synchronize().context("device synchronize")?;
        let counter_host = self
            .dev
            .dtoh_sync_copy(&self.counter_dev)
            .context("read counter")?;
        let n_emitted = counter_host[0] as usize;
        let n_to_read = n_emitted.min(MAX_RESULTS as usize);
        let mut all = self
            .dev
            .dtoh_sync_copy(&self.results_dev)
            .context("read results")?;
        all.truncate(n_to_read);
        Ok(KernelResult {
            candidates: all,
            overflow: n_emitted > MAX_RESULTS as usize,
        })
    }

    /// Phase-A debug helper: run the dump kernel on a single input,
    /// return the 32-byte BLAKE3(BLAKE3(input)) digest.
    pub fn double_blake3_dump(&self, input: &[u8]) -> Result<[u8; 32]> {
        if input.is_empty() || input.len() > 1024 {
            anyhow::bail!(
                "double_blake3_dump: input must be 1..=1024 bytes (got {})",
                input.len()
            );
        }
        let input_dev = self.dev.htod_copy(input.to_vec()).context("htod input")?;
        let mut output_dev: CudaSlice<u8> =
            self.dev.alloc_zeros::<u8>(32).context("alloc output")?;
        let func = self
            .dev
            .get_func(MODULE_NAME, KERNEL_NAME_DUMP)
            .ok_or_else(|| anyhow!("kernel {KERNEL_NAME_DUMP} not loaded"))?;
        let cfg = LaunchConfig {
            grid_dim: (1, 1, 1),
            block_dim: (1, 1, 1),
            shared_mem_bytes: 0,
        };
        unsafe { func.launch(cfg, (&input_dev, input.len() as u32, &mut output_dev)) }
            .context("launch dump kernel")?;
        self.dev.synchronize()?;
        let out = self
            .dev
            .dtoh_sync_copy(&output_dev)
            .context("read dump output")?;
        let mut arr = [0u8; 32];
        arr.copy_from_slice(&out);
        Ok(arr)
    }
}
