// build.rs -- compile the CUDA kernel to PTX with nvcc and stash the
// path in OUT_DIR so src/gpu/device.rs can include_bytes! it.
//
// Strategy: keep this small. We do NOT use bindgen_cuda / cuda_builder
// crates because they pin transitive deps that conflict with cudarc.
// All we need is `nvcc -ptx kernels/miner.cu -o $OUT_DIR/miner.ptx`.
//
// If the `cuda` feature is disabled OR the toolchain is missing, we
// emit a tiny stub PTX so the crate still compiles for `cargo check`.
// The runtime will detect the stub and refuse to start with a clear
// "build the crate with the cuda feature" error.

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=kernels/miner.cu");
    println!("cargo:rerun-if-changed=kernels/blake3.cuh");
    println!("cargo:rerun-if-env-changed=CUDA_PATH");
    println!("cargo:rerun-if-env-changed=CUDA_ARCH");

    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let ptx_out = out_dir.join("miner.ptx");

    let cuda_enabled = env::var_os("CARGO_FEATURE_CUDA").is_some();
    if !cuda_enabled {
        write_stub(&ptx_out);
        return;
    }

    if let Err(e) = compile(&ptx_out) {
        eprintln!("cargo:warning=CUDA kernel build failed: {e}");
        eprintln!("cargo:warning=Falling back to stub PTX. The binary will run \
                   but refuse to mine until you install the CUDA Toolkit and rebuild.");
        write_stub(&ptx_out);
    }
}

fn compile(ptx_out: &PathBuf) -> anyhow::Result<()> {
    // Pick the SM target. CUDA_ARCH overrides; default to sm_75 (Turing,
    // covers 1660/2060/2070/2080/T4) which is forward-compatible with
    // newer GPUs via JIT in the driver.
    let arch = env::var("CUDA_ARCH").unwrap_or_else(|_| "sm_75".to_string());

    let nvcc = locate_nvcc()?;
    let kernel = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?)
        .join("kernels/miner.cu");

    let status = Command::new(&nvcc)
        .args([
            "-ptx",
            "--use_fast_math",
            "-O3",
            "-arch", &arch,
            "-o",
        ])
        .arg(ptx_out)
        .arg(&kernel)
        .status()
        .map_err(|e| anyhow::anyhow!("failed to spawn nvcc at {}: {e}", nvcc.display()))?;

    if !status.success() {
        anyhow::bail!("nvcc {} returned {}", nvcc.display(), status);
    }
    Ok(())
}

fn locate_nvcc() -> anyhow::Result<PathBuf> {
    // 1) explicit override
    if let Ok(p) = env::var("NVCC") {
        return Ok(PathBuf::from(p));
    }
    // 2) PATH
    if let Ok(path) = env::var("PATH") {
        let exe = if cfg!(windows) { "nvcc.exe" } else { "nvcc" };
        for dir in env::split_paths(&path) {
            let candidate = dir.join(exe);
            if candidate.is_file() {
                return Ok(candidate);
            }
        }
    }
    // 3) CUDA_PATH (Windows installer sets this)
    if let Ok(cp) = env::var("CUDA_PATH") {
        let exe = if cfg!(windows) { "nvcc.exe" } else { "nvcc" };
        let candidate = PathBuf::from(cp).join("bin").join(exe);
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    // 4) common default (Linux)
    let linux_default = PathBuf::from("/usr/local/cuda/bin/nvcc");
    if linux_default.is_file() {
        return Ok(linux_default);
    }
    anyhow::bail!("nvcc not found on PATH, in $NVCC, or via $CUDA_PATH")
}

fn write_stub(ptx_out: &PathBuf) {
    // Tiny but valid PTX header so cudarc::Module::load can parse it
    // far enough to fail with "missing kernel" rather than "garbage in
    // PTX". The runtime will see no `double_blake3_search` symbol and
    // bail out with a useful message.
    let stub = b"//\n// b3chain-gpuminer stub PTX (cuda feature disabled or toolchain missing)\n//\n.version 7.0\n.target sm_50\n.address_size 64\n";
    std::fs::write(ptx_out, stub).expect("write stub PTX");
}
