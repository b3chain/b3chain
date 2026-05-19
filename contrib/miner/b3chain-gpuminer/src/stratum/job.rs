// Mining job state.
//
// Mirrors `CurrentJob` and the bits of `StratumPoolClient` state that
// worker threads consume in contrib/miner/b3chain-cpuminer.py:
//   extranonce1, extranonce2_size, share_difficulty, share_target,
//   current_job, clean_epoch.
//
// This is the OUTPUT of the Stratum client and the INPUT to the GPU
// driver. Wrapping it in a watch channel lets the driver wake up
// instantly on a clean_jobs notify or a difficulty change without
// polling.

use num_bigint::BigUint;

use crate::util::target;

/// A snapshot of one `mining.notify` job.
#[derive(Debug, Clone)]
pub struct CurrentJob {
    pub job_id: String,
    /// 32 bytes, big-endian (display order, as the pool sends it).
    pub prev_hash_be: [u8; 32],
    pub coinb1: Vec<u8>,
    pub coinb2: Vec<u8>,
    /// Each 32 bytes, big-endian (display order, as on the wire).
    pub merkle_branches_be: Vec<[u8; 32]>,
    pub version: u32,
    pub bits: u32,
    pub ntime: u32,
    pub clean_jobs: bool,
    pub received_at: f64,
    pub network_target: BigUint,
    pub network_difficulty: f64,
}

impl CurrentJob {
    /// `prev_hash` in little-endian, as the header serialiser expects.
    pub fn prev_hash_le(&self) -> [u8; 32] {
        let mut le = self.prev_hash_be;
        le.reverse();
        le
    }
}

/// Mining state shared between the Stratum client task and the GPU
/// driver task. Updated under a mutex by the client; the driver reads
/// it (cheap, the client write rate is at most a few times per second)
/// at the start of each kernel launch.
#[derive(Debug, Clone)]
pub struct MiningState {
    pub extranonce1: Vec<u8>,
    pub extranonce2_size: usize,
    pub share_difficulty: f64,
    pub share_target: BigUint,
    pub current_job: Option<CurrentJob>,
    /// Bumped on every `clean_jobs=true` notify, on every `set_extranonce`,
    /// and on every (re)connect. Workers compare their snapshot of this
    /// counter at every nonce iteration -- if it changed, the in-flight
    /// search is abandoned immediately.
    pub clean_epoch: u64,
}

impl MiningState {
    pub fn new(default_difficulty: f64) -> Self {
        Self {
            extranonce1: Vec::new(),
            extranonce2_size: 0,
            share_difficulty: default_difficulty,
            share_target: target::target_from_share_difficulty(default_difficulty),
            current_job: None,
            clean_epoch: 0,
        }
    }
}
