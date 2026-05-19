// b3chain-gpuminer CLI.
//
// Mirrors the Python miner's CLI surface so the dashboard's
// "backend = GPU" launcher can use the same argv contract:
//
//   --stratum stratum+tcp://pool:3333
//   --user    name@worker
//   --pass    x
//   --useragent b3chain-gpuminer/0.1
//   --json-log path/to/log.jsonl
//
// Plus GPU-specific flags:
//
//   --gpu          ordinal of the CUDA device (default 0)
//   --batch-size   nonces per kernel launch (default 1<<24 = 16M)
//   --block-size   threads per block (default 256)

use anyhow::{Context, Result};
use clap::Parser;
use std::path::PathBuf;
use std::sync::Arc;

use b3chain_gpuminer::{
    stratum::client::Client,
    util::{log::JsonlLogger, url::parse_stratum_url},
};

#[cfg(feature = "cuda")]
use b3chain_gpuminer::gpu::{Driver, MinerKernel};

#[derive(Parser, Debug)]
#[command(name = "b3chain-gpuminer", version, about = "B3Chain CUDA GPU miner")]
struct Args {
    /// Stratum URL: stratum+tcp://host:port
    #[arg(long)]
    stratum: String,

    /// Worker username, e.g. alice@b3chain.org.gpu1
    #[arg(long)]
    user: String,

    /// Worker password (Stratum requires a non-empty value; "x" is fine)
    #[arg(long, default_value = "x")]
    pass: String,

    /// User-Agent string sent with mining.subscribe
    #[arg(long, default_value = concat!("b3chain-gpuminer/", env!("CARGO_PKG_VERSION")))]
    useragent: String,

    /// Optional JSONL log path. Same schema as the Python miner so the
    /// live mining dashboard ingests it unchanged.
    #[arg(long)]
    json_log: Option<PathBuf>,

    /// CUDA device ordinal.
    #[arg(long, default_value_t = 0)]
    gpu: usize,

    /// Nonces per kernel launch (host -> device round-trip).
    /// Default 2^24 = 16,777,216, which is ~50-200 ms on midrange
    /// GPUs and balances launch overhead vs. clean-job latency.
    #[arg(long, default_value_t = 1u32 << 24)]
    batch_size: u32,

    /// CUDA threads per block. 128 / 256 / 512 are the usual sweet
    /// spots for compute-bound kernels.
    #[arg(long, default_value_t = 256)]
    block_size: u32,

    /// Default share-difficulty target before the pool sends
    /// mining.set_difficulty (mirrors the Python miner).
    #[arg(long, default_value_t = 1024.0)]
    default_diff: f64,
}

#[tokio::main(flavor = "multi_thread")]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_target(false)
        .init();

    let args = Args::parse();
    let endpoint = parse_stratum_url(&args.stratum).context("parsing --stratum")?;
    let logger = Arc::new(
        JsonlLogger::open(args.json_log.as_deref()).context("opening JSONL log")?,
    );

    println!(
        "b3chain GPU miner -- pool mode\n  Pool:    stratum+tcp://{}:{}\n  User:    {}\n  GPU:     {}\n  Batch:   {} nonces/launch\n  PoW:     BLAKE3(BLAKE3(80-byte header))",
        endpoint.host, endpoint.port, args.user, args.gpu, args.batch_size
    );

    if let Some(p) = args.json_log.as_ref() {
        println!("JSONL log -> {}", p.display());
    }

    let (client, handle) = Client::new(
        endpoint.host,
        endpoint.port,
        endpoint.use_tls,
        args.user,
        args.pass,
        args.useragent,
        args.default_diff,
        logger.clone(),
    );

    // Spawn the Stratum task.
    let stratum_task = tokio::spawn(async move {
        if let Err(e) = client.run_forever().await {
            eprintln!("stratum task exited: {e:#}");
        }
    });

    // Spawn the GPU driver.
    #[cfg(feature = "cuda")]
    let gpu_task = {
        let kernel = MinerKernel::new(args.gpu).context("opening CUDA device")?;
        let driver = Driver::new(
            kernel,
            handle,
            logger.clone(),
            args.batch_size,
            args.block_size,
        );
        tokio::spawn(async move {
            if let Err(e) = driver.run().await {
                eprintln!("gpu driver exited: {e:#}");
            }
        })
    };

    #[cfg(not(feature = "cuda"))]
    {
        drop(handle);
        anyhow::bail!(
            "this binary was built without the `cuda` feature; \
             rebuild with `cargo build --release --features cuda` (the default)"
        );
    }

    // The driver owns submit_results (it correlates responses with the
    // pending-share map to emit `share_submit` JSONL events).

    // Wait for Ctrl-C.
    let _ = tokio::signal::ctrl_c().await;
    println!("\ncaught Ctrl-C, shutting down...");

    stratum_task.abort();
    #[cfg(feature = "cuda")]
    gpu_task.abort();
    Ok(())
}
