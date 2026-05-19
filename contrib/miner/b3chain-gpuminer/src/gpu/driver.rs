// GPU work dispatcher.
//
// Owns the MinerKernel and one extranonce2 counter. On every iteration:
//
//   1. Read the latest MiningState from the watch channel (job +
//      share_target + extranonce1 + clean_epoch).
//   2. Wait for a job to be present.
//   3. Build the coinbase (coinb1 || en1 || en2 || coinb2), the
//      coinbase txid, the merkle root, and the 80-byte header
//      template -- all on the host.
//   4. Hand the header + share target + a [nonce_start, nonce_start +
//      BATCH_NONCES) range to MinerKernel::launch().
//   5. For each candidate returned, build a ShareSubmit and push it
//      onto the Stratum client's submit channel. Save the deep-detail
//      payload in a pending map keyed by share_seq so the response
//      handler can emit a `share_submit` event matching the Python
//      miner's JSONL schema.
//   6. Increment nonce_start. If we hit u32::MAX, bump extranonce2
//      and start over.
//   7. Emit a "progress" JSONL event roughly once per second.
//
// Whenever clean_epoch changes mid-iteration, we abandon the in-flight
// work as soon as the current launch returns. The kernel itself is
// short (~50-200 ms per launch), so latency to react to a clean job
// is bounded by one launch duration.

use anyhow::{Context, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::Mutex;

use crate::gpu::device::{KernelLaunch, MinerKernel};
use crate::stratum::client::{ClientHandle, ShareSubmit};
use crate::stratum::job::{CurrentJob, MiningState};
use crate::util::{log::JsonlLogger, target};
use crate::work::{
    coinbase::{build_coinbase, coinbase_txid_le},
    header::serialize_header_template,
    merkle::compute_merkle_root,
};

/// Captured at the moment we decide to submit a share -- everything the
/// JSONL `share_submit` event needs except the server response fields.
#[derive(Debug, Clone)]
struct ShareDetails {
    seq: u64,
    thread: u32,
    job_id: String,
    extranonce1_hex: String,
    extranonce2_hex: String,
    ntime: u32,
    nonce: u32,
    coinbase_hex: String,
    coinbase_txid_be_hex: String,
    merkle_root_be_hex: String,
    header_hex: String,
    pow_hash_le_hex: String,
    pow_hash_be_hex: String,
    block_hash_be_hex: String,
    is_block: bool,
    pow_int_dec: String,
    share_target_be_hex: String,
    share_difficulty: f64,
    network_target_be_hex: String,
    network_difficulty: f64,
    attempts_for_job: u64,
    found_at: f64,
}

pub struct Driver {
    kernel: MinerKernel,
    handle: ClientHandle,
    logger: Arc<JsonlLogger>,
    batch_nonces: u32,
    block_size: u32,
    thread_idx: u32,
    share_seq: u64,
    pending: Arc<Mutex<HashMap<u64, ShareDetails>>>,
}

impl Driver {
    pub fn new(
        kernel: MinerKernel,
        handle: ClientHandle,
        logger: Arc<JsonlLogger>,
        batch_nonces: u32,
        block_size: u32,
    ) -> Self {
        Self {
            kernel,
            handle,
            logger,
            batch_nonces,
            block_size,
            thread_idx: 0,
            share_seq: 0,
            pending: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Spawn the response-handler task BEFORE entering the main work
    /// loop. It owns the submit_results receiver and emits one
    /// `share_submit` JSONL event per response.
    fn spawn_response_handler(&self) {
        let pending = self.pending.clone();
        let logger = self.logger.clone();
        let results_arc = self.handle.submit_results.clone();
        tokio::spawn(async move {
            let mut rx = results_arc.lock().await;
            while let Some(out) = rx.recv().await {
                let details = pending.lock().await.remove(&out.seq);
                let Some(d) = details else { continue };
                let mut payload = json!({
                    "share_seq": d.seq,
                    "thread": d.thread,
                    "job_id": d.job_id,
                    "extranonce1": d.extranonce1_hex,
                    "extranonce2": d.extranonce2_hex,
                    "ntime": d.ntime,
                    "ntime_hex": format!("{:08x}", d.ntime),
                    "nonce": d.nonce,
                    "nonce_hex": format!("{:08x}", d.nonce),
                    "coinbase": d.coinbase_hex,
                    "coinbase_txid_be": d.coinbase_txid_be_hex,
                    "merkle_root_be": d.merkle_root_be_hex,
                    "header_hex": d.header_hex,
                    "pow_hash_le": d.pow_hash_le_hex,
                    "pow_hash_be": d.pow_hash_be_hex,
                    "pow_int_dec": d.pow_int_dec,
                    "block_hash_be": d.block_hash_be_hex,
                    "share_target_be": d.share_target_be_hex,
                    "share_difficulty": d.share_difficulty,
                    "network_target_be": d.network_target_be_hex,
                    "network_difficulty": d.network_difficulty,
                    "is_block": d.is_block,
                    "attempts_for_job": d.attempts_for_job,
                    "found_at": d.found_at,
                    "server_rtt_ms": out.rtt_ms as f64,
                    "accepted": out.accepted,
                });
                if let Some(obj) = payload.as_object_mut() {
                    obj.insert("error".into(), out.error.clone().unwrap_or(Value::Null));
                }
                logger.emit("share_submit", &payload);
            }
        });
    }

    pub async fn run(mut self) -> Result<()> {
        self.spawn_response_handler();

        let mut state_rx = self.handle.state_rx.clone();
        let mut en2_counter: u64 = 0;
        let mut last_progress = Instant::now();
        let mut attempts_since_progress: u64 = 0;
        let mut attempts_for_job: u64 = 0;
        let mut last_clean_epoch: u64 = 0;
        let mut last_job_id: Option<String> = None;

        loop {
            // Wait for a job + extranonce1.
            let snap = loop {
                let s: MiningState = state_rx.borrow().state.clone();
                if s.current_job.is_some() && !s.extranonce1.is_empty() {
                    break s;
                }
                if state_rx.changed().await.is_err() {
                    return Ok(());
                }
            };

            let job: CurrentJob = snap.current_job.clone().unwrap();
            let share_target_le = target::to_le_bytes_32(&snap.share_target);

            if last_job_id.as_deref() != Some(job.job_id.as_str())
                || last_clean_epoch != snap.clean_epoch
            {
                attempts_for_job = 0;
                last_job_id = Some(job.job_id.clone());
                last_clean_epoch = snap.clean_epoch;
                en2_counter = 0;
            }

            // Build the per-en2 coinbase + merkle + header template.
            let en2_size = snap.extranonce2_size.max(1);
            let en2 = encode_extranonce2(en2_counter, en2_size);
            let coinbase = build_coinbase(&job.coinb1, &snap.extranonce1, &en2, &job.coinb2);
            let cb_txid_le = coinbase_txid_le(&coinbase);
            let merkle_root_le = compute_merkle_root(&cb_txid_le, &job.merkle_branches_be);
            let prev_le = job.prev_hash_le();
            let header_template = serialize_header_template(
                job.version,
                &prev_le,
                &merkle_root_le,
                job.ntime,
                job.bits,
            );

            let extranonce1_hex = hex::encode(&snap.extranonce1);
            let extranonce2_hex = hex::encode(&en2);
            let coinbase_hex = hex::encode(&coinbase);
            let coinbase_txid_be_hex = hex::encode({
                let mut be = cb_txid_le;
                be.reverse();
                be
            });
            let merkle_root_be_hex = hex::encode({
                let mut be = merkle_root_le;
                be.reverse();
                be
            });
            let share_target_be_hex = target::to_be_hex_64(&snap.share_target);
            let network_target_be_hex = target::to_be_hex_64(&job.network_target);

            // Sweep all 2^32 nonces in batches.
            let total_nonces: u64 = 1u64 << 32;
            let mut nonces_done: u64 = 0;
            while nonces_done < total_nonces {
                let s: MiningState = state_rx.borrow().state.clone();
                if s.clean_epoch != last_clean_epoch
                    || s.current_job.as_ref().map(|j| j.job_id.as_str())
                        != last_job_id.as_deref()
                {
                    break;
                }

                let nonce_start: u32 = nonces_done as u32;
                let remaining: u64 = total_nonces - nonces_done;
                let count: u32 = remaining.min(self.batch_nonces as u64) as u32;

                let res = self
                    .kernel
                    .launch(KernelLaunch {
                        header_template_le: &header_template,
                        share_target_le: &share_target_le,
                        nonce_start,
                        nonce_count: count,
                        block_size: self.block_size,
                    })
                    .context("kernel launch")?;

                attempts_since_progress += count as u64;
                attempts_for_job += count as u64;

                for cand in res.candidates {
                    self.share_seq += 1;
                    let mut full_header = header_template;
                    full_header[76..80].copy_from_slice(&cand.nonce.to_le_bytes());
                    let pow_le = cand.hash_le;
                    let mut pow_be = pow_le;
                    pow_be.reverse();
                    let pow_int_dec = bytes_le_to_decimal(&pow_le);
                    let is_block = pow_le_le_target(&pow_le, &job.network_target);
                    let block_hash_le = sha256d(&full_header);
                    let mut block_hash_be = block_hash_le;
                    block_hash_be.reverse();

                    let details = ShareDetails {
                        seq: self.share_seq,
                        thread: self.thread_idx,
                        job_id: job.job_id.clone(),
                        extranonce1_hex: extranonce1_hex.clone(),
                        extranonce2_hex: extranonce2_hex.clone(),
                        ntime: job.ntime,
                        nonce: cand.nonce,
                        coinbase_hex: coinbase_hex.clone(),
                        coinbase_txid_be_hex: coinbase_txid_be_hex.clone(),
                        merkle_root_be_hex: merkle_root_be_hex.clone(),
                        header_hex: hex::encode(full_header),
                        pow_hash_le_hex: hex::encode(pow_le),
                        pow_hash_be_hex: hex::encode(pow_be),
                        pow_int_dec,
                        block_hash_be_hex: hex::encode(block_hash_be),
                        is_block,
                        share_target_be_hex: share_target_be_hex.clone(),
                        share_difficulty: snap.share_difficulty,
                        network_target_be_hex: network_target_be_hex.clone(),
                        network_difficulty: job.network_difficulty,
                        attempts_for_job,
                        found_at: now_secs(),
                    };

                    // Forensic: emit pre-submit immediately so even
                    // network-loss leaves the share fully recorded.
                    self.logger.emit(
                        "share_pre_submit",
                        &details_to_json(&details),
                    );

                    self.pending.lock().await.insert(self.share_seq, details);
                    let _ = self
                        .handle
                        .submit_tx
                        .send(ShareSubmit {
                            job_id: job.job_id.clone(),
                            extranonce2_hex: extranonce2_hex.clone(),
                            ntime: job.ntime,
                            nonce: cand.nonce,
                            seq: self.share_seq,
                        })
                        .await;
                }

                if res.overflow {
                    self.logger.emit(
                        "kernel-overflow",
                        &json!({"batch_nonces": count, "max_results": 64u32}),
                    );
                }

                nonces_done = nonces_done.saturating_add(count as u64);

                let elapsed = last_progress.elapsed().as_secs_f64();
                if elapsed >= 1.0 {
                    let rate = attempts_since_progress as f64 / elapsed.max(1e-9);
                    self.logger.emit(
                        "progress",
                        &json!({
                            "thread": self.thread_idx,
                            "job_id": job.job_id,
                            "extranonce2": extranonce2_hex,
                            "attempts": attempts_for_job,
                            "hashrate": rate,
                            "best_pow_be": "",
                        }),
                    );
                    attempts_since_progress = 0;
                    last_progress = Instant::now();
                }
            }

            let s_now: MiningState = state_rx.borrow().state.clone();
            if s_now.clean_epoch == last_clean_epoch
                && s_now.current_job.as_ref().map(|j| j.job_id.as_str()) == last_job_id.as_deref()
            {
                en2_counter = en2_counter.saturating_add(1);
            }
        }
    }
}

fn details_to_json(d: &ShareDetails) -> Value {
    json!({
        "share_seq": d.seq,
        "thread": d.thread,
        "job_id": d.job_id,
        "extranonce1": d.extranonce1_hex,
        "extranonce2": d.extranonce2_hex,
        "ntime": d.ntime,
        "ntime_hex": format!("{:08x}", d.ntime),
        "nonce": d.nonce,
        "nonce_hex": format!("{:08x}", d.nonce),
        "coinbase": d.coinbase_hex,
        "coinbase_txid_be": d.coinbase_txid_be_hex,
        "merkle_root_be": d.merkle_root_be_hex,
        "header_hex": d.header_hex,
        "pow_hash_le": d.pow_hash_le_hex,
        "pow_hash_be": d.pow_hash_be_hex,
        "pow_int_dec": d.pow_int_dec,
        "block_hash_be": d.block_hash_be_hex,
        "share_target_be": d.share_target_be_hex,
        "share_difficulty": d.share_difficulty,
        "network_target_be": d.network_target_be_hex,
        "network_difficulty": d.network_difficulty,
        "is_block": d.is_block,
        "attempts_for_job": d.attempts_for_job,
        "found_at": d.found_at,
    })
}

/// Pack a u64 counter into `size` bytes, big-endian.
fn encode_extranonce2(counter: u64, size: usize) -> Vec<u8> {
    let mut v = vec![0u8; size];
    let bytes = counter.to_be_bytes();
    let n = size.min(8);
    v[size - n..].copy_from_slice(&bytes[8 - n..]);
    v
}

fn sha256d(data: &[u8]) -> [u8; 32] {
    let h1 = Sha256::digest(data);
    let h2 = Sha256::digest(h1);
    let mut out = [0u8; 32];
    out.copy_from_slice(&h2);
    out
}

/// Decimal string of a 256-bit little-endian byte array, used for the
/// `pow_int_dec` JSONL field. Mirrors Python's `str(int.from_bytes(b, "little"))`.
fn bytes_le_to_decimal(le: &[u8]) -> String {
    use num_bigint::BigUint;
    BigUint::from_bytes_le(le).to_string()
}

/// Returns true iff the little-endian POW byte array <= the network target.
fn pow_le_le_target(pow_le: &[u8; 32], net_target: &num_bigint::BigUint) -> bool {
    use num_bigint::BigUint;
    let pow_int = BigUint::from_bytes_le(pow_le);
    pow_int <= *net_target
}

fn now_secs() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extranonce2_4byte_be() {
        assert_eq!(encode_extranonce2(0x12345678, 4), vec![0x12, 0x34, 0x56, 0x78]);
    }

    #[test]
    fn extranonce2_8byte_be() {
        assert_eq!(
            encode_extranonce2(0x0102030405060708, 8),
            vec![1, 2, 3, 4, 5, 6, 7, 8]
        );
    }

    #[test]
    fn extranonce2_smaller_size_truncates_high_bytes() {
        assert_eq!(encode_extranonce2(0xFFFF_AABB, 2), vec![0xAA, 0xBB]);
    }

    #[test]
    fn bytes_le_to_decimal_zero() {
        assert_eq!(bytes_le_to_decimal(&[0u8; 32]), "0");
    }

    #[test]
    fn bytes_le_to_decimal_smoke() {
        let mut le = [0u8; 32];
        le[0] = 5;
        assert_eq!(bytes_le_to_decimal(&le), "5");
    }
}
