// Async Stratum V1 client.
//
// Direct port of contrib/miner/b3chain-cpuminer.py:529-1000 (the
// `StratumPoolClient` class plus the `pool_mining_worker` outer loop).
//
// Architecture:
//
//   * One tokio task per `Client` runs `run_forever()`. It owns a
//     TcpStream, a request-id counter, a pending-response map, and
//     the shared MiningState.
//   * A bounded mpsc channel `submit_tx` accepts share submits from
//     the GPU driver. The reader-loop side only handles inbound
//     traffic; outbound mining.submit calls happen on the same task
//     via select! between socket reads and submit_rx pulls.
//   * MiningState updates are surfaced via a tokio::sync::watch so the
//     GPU driver wakes up on the same trigger that incremented
//     `clean_epoch` (the equivalent of the Python miner's tight
//     polling loop on `clean_epoch`).
//
// The wire framing matches the server-side framer at
// contrib/testnet/pool/src/stratum/client.ts (newline-delimited JSON
// with line accumulation across recv() boundaries).

use anyhow::{anyhow, bail, Context, Result};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::sync::{mpsc, oneshot, watch, Mutex};
use tokio::time::timeout;

use crate::stratum::job::{CurrentJob, MiningState};
use crate::stratum::messages::ServerMessage;
use crate::util::{log::JsonlLogger, target};

/// Submit-side payload pushed by the GPU driver into the client.
#[derive(Debug, Clone)]
pub struct ShareSubmit {
    pub job_id: String,
    pub extranonce2_hex: String,
    pub ntime: u32,
    pub nonce: u32,
    /// Used by the caller to correlate `SubmitOutcome::resp` with the
    /// share. The client doesn't interpret it.
    pub seq: u64,
}

/// Result of one mining.submit roundtrip.
#[derive(Debug, Clone)]
pub struct SubmitOutcome {
    pub seq: u64,
    pub accepted: bool,
    pub error: Option<Value>,
    pub rtt_ms: u128,
}

/// Sent over the watch channel every time MiningState changes.
#[derive(Debug, Clone)]
pub struct JobUpdate {
    pub state: MiningState,
}

/// Public handle the binary uses to drive the client. Sender-only;
/// inbound state changes flow through `state_rx`.
#[derive(Clone)]
pub struct ClientHandle {
    pub submit_tx: mpsc::Sender<ShareSubmit>,
    pub submit_results: Arc<Mutex<mpsc::Receiver<SubmitOutcome>>>,
    pub state_rx: watch::Receiver<JobUpdate>,
}

pub struct Client {
    host: String,
    port: u16,
    use_tls: bool,
    user: String,
    password: String,
    useragent: String,
    default_diff: f64,

    logger: Arc<JsonlLogger>,

    // Internal state.
    state: Arc<Mutex<MiningState>>,
    state_tx: watch::Sender<JobUpdate>,
    submit_rx: mpsc::Receiver<ShareSubmit>,
    submit_results_tx: mpsc::Sender<SubmitOutcome>,
}

impl Client {
    /// Build a Client and a paired ClientHandle. Channels are created
    /// here so the caller can hand the handle off to the GPU driver
    /// before run_forever() is started.
    pub fn new(
        host: impl Into<String>,
        port: u16,
        use_tls: bool,
        user: impl Into<String>,
        password: impl Into<String>,
        useragent: impl Into<String>,
        default_diff: f64,
        logger: Arc<JsonlLogger>,
    ) -> (Self, ClientHandle) {
        let initial_state = MiningState::new(default_diff);
        let state = Arc::new(Mutex::new(initial_state.clone()));
        let (state_tx, state_rx) = watch::channel(JobUpdate {
            state: initial_state,
        });
        let (submit_tx, submit_rx) = mpsc::channel::<ShareSubmit>(64);
        let (submit_results_tx, submit_results_rx) = mpsc::channel::<SubmitOutcome>(64);

        let me = Self {
            host: host.into(),
            port,
            use_tls,
            user: user.into(),
            password: password.into(),
            useragent: useragent.into(),
            default_diff,
            logger,
            state,
            state_tx,
            submit_rx,
            submit_results_tx,
        };
        let handle = ClientHandle {
            submit_tx,
            submit_results: Arc::new(Mutex::new(submit_results_rx)),
            state_rx,
        };
        (me, handle)
    }

    /// Connect, handshake, then process traffic until the connection
    /// drops or we hit a fatal error. On drop, sleep with exponential
    /// backoff and reconnect. Bumps `clean_epoch` on every reconnect.
    pub async fn run_forever(mut self) -> Result<()> {
        let mut attempt: u32 = 0;
        loop {
            attempt += 1;
            match self.run_one_session().await {
                Ok(_) => {
                    // Disconnected cleanly (server closed). Reconnect.
                    self.logger
                        .emit("disconnect", &json!({"reason":"reader exit","attempt":attempt}));
                }
                Err(e) => {
                    self.logger.emit(
                        "disconnect",
                        &json!({"reason": format!("{e:#}"), "attempt": attempt}),
                    );
                }
            }
            // Bump epoch + clear job so the GPU driver pauses.
            {
                let mut s = self.state.lock().await;
                s.current_job = None;
                s.extranonce1.clear();
                s.clean_epoch = s.clean_epoch.wrapping_add(1);
                let _ = self.state_tx.send(JobUpdate { state: s.clone() });
            }
            // Backoff: 5s, 10s, 20s, 40s, 60s (capped).
            let mut delay = 5u64.saturating_mul(1u64 << attempt.min(4)); // 5,10,20,40,80
            delay = delay.min(60);
            tokio::time::sleep(Duration::from_secs(delay)).await;
        }
    }

    async fn run_one_session(&mut self) -> Result<()> {
        // Connect.
        if self.use_tls {
            // We don't bring tokio-rustls in by default; the live
            // testnet pool uses plain TCP on 3333. If you point this
            // miner at a TLS endpoint, build with the (future) `tls`
            // feature -- TODO Phase D backlog.
            bail!("TLS Stratum endpoints are not supported in v0.1; use stratum+tcp://");
        }
        let addr = format!("{}:{}", self.host, self.port);
        let stream = TcpStream::connect(&addr)
            .await
            .with_context(|| format!("connecting to {addr}"))?;
        // TCP_NODELAY mirrors the Python miner.
        let _ = stream.set_nodelay(true);

        self.logger.emit(
            "connect",
            &json!({
                "host": &self.host,
                "port": self.port,
                "use_tls": self.use_tls,
                "useragent": &self.useragent,
            }),
        );
        eprintln!(
            "[{}] connected to {}:{} (TCP)",
            crate::util::log::utc_iso(now_secs()),
            self.host,
            self.port
        );

        // Split for concurrent read + write.
        let (rd, mut wr) = stream.into_split();
        let mut rdr = BufReader::new(rd);

        // Per-session id counter and pending-response map. Wrapped in
        // an Arc<Mutex> because the writer side (us) issues requests
        // and the reader side (us, in the same select! arm) routes
        // responses by id.
        let next_id = Arc::new(std::sync::atomic::AtomicU64::new(1));
        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<ServerMessage>>>> =
            Arc::new(Mutex::new(HashMap::new()));

        // Subscribe.
        let sub_id = next_id.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        write_json_line(
            &mut wr,
            &json!({
                "id": sub_id,
                "method": "mining.subscribe",
                "params": [&self.useragent],
            }),
        )
        .await?;

        // Read until we get the response to sub_id, dispatching any
        // notifications that arrive in between.
        let sub_resp = self
            .read_until_response(&mut rdr, sub_id, Duration::from_secs(15), &pending)
            .await?;
        let (en1_hex, en2_size) = parse_subscribe(&sub_resp)?;
        {
            let mut s = self.state.lock().await;
            s.extranonce1 = hex::decode(&en1_hex).context("decode extranonce1")?;
            s.extranonce2_size = en2_size;
            // bump epoch so any in-flight worker abandons stale en1
            s.clean_epoch = s.clean_epoch.wrapping_add(1);
            let _ = self.state_tx.send(JobUpdate { state: s.clone() });
        }
        self.logger.emit(
            "subscribed",
            &json!({"extranonce1": en1_hex, "extranonce2_size": en2_size}),
        );

        // Authorize.
        let auth_id = next_id.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let pwd = if self.password.is_empty() {
            "x".to_string()
        } else {
            self.password.clone()
        };
        write_json_line(
            &mut wr,
            &json!({
                "id": auth_id,
                "method": "mining.authorize",
                "params": [&self.user, pwd],
            }),
        )
        .await?;
        let auth_resp = self
            .read_until_response(&mut rdr, auth_id, Duration::from_secs(15), &pending)
            .await?;
        let ok = matches!(&auth_resp.result, Some(Value::Bool(true)));
        self.logger
            .emit("authorized", &json!({"user": &self.user, "ok": ok}));
        if !ok {
            bail!("authorize returned false: {:?}", auth_resp.error);
        }

        // Main loop: select! between
        //   * inbound JSON-RPC line  -> dispatch (notify or unmatched response)
        //   * outbound submit request -> write line + record pending entry
        //                                 (response is routed back via pending map)
        //   * submit-response routed -> pushed onto submit_results_tx
        let pending_for_loop = pending.clone();
        let next_id_for_loop = next_id.clone();
        let mut line_buf = String::new();
        loop {
            line_buf.clear();
            tokio::select! {
                // Inbound traffic.
                read_res = rdr.read_line(&mut line_buf) => {
                    let n = read_res?;
                    if n == 0 {
                        // EOF.
                        return Ok(());
                    }
                    let line = line_buf.trim();
                    if line.is_empty() { continue; }
                    let msg: ServerMessage = match serde_json::from_str(line) {
                        Ok(m) => m,
                        Err(e) => {
                            self.logger.emit("parse-error", &json!({"err": e.to_string(), "line": line}));
                            continue;
                        }
                    };
                    self.dispatch(msg, &pending_for_loop).await;
                }

                // Outbound submit.
                Some(s) = self.submit_rx.recv() => {
                    let id = next_id_for_loop.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    let nonce_hex = format!("{:08x}", s.nonce);
                    let ntime_hex = format!("{:08x}", s.ntime);
                    let req = json!({
                        "id": id,
                        "method": "mining.submit",
                        "params": [&self.user, &s.job_id, &s.extranonce2_hex, &ntime_hex, &nonce_hex],
                    });
                    let started = Instant::now();
                    let (tx, rx) = oneshot::channel::<ServerMessage>();
                    pending_for_loop.lock().await.insert(id, tx);
                    if let Err(e) = write_json_line(&mut wr, &req).await {
                        // Network died. Surface error and let outer loop reconnect.
                        let _ = self.submit_results_tx.send(SubmitOutcome {
                            seq: s.seq, accepted: false,
                            error: Some(json!({"network": e.to_string()})),
                            rtt_ms: started.elapsed().as_millis(),
                        }).await;
                        return Err(anyhow!("submit write failed: {e}"));
                    }
                    // Spawn a tiny task to await the response and forward it.
                    let results_tx = self.submit_results_tx.clone();
                    let logger = self.logger.clone();
                    tokio::spawn(async move {
                        match timeout(Duration::from_secs(30), rx).await {
                            Ok(Ok(resp)) => {
                                let accepted = matches!(&resp.result, Some(Value::Bool(true)))
                                    && resp.error.is_none();
                                let outcome = SubmitOutcome {
                                    seq: s.seq, accepted,
                                    error: resp.error.clone(),
                                    rtt_ms: started.elapsed().as_millis(),
                                };
                                logger.emit("submit_response", &json!({
                                    "share_seq": s.seq,
                                    "job_id": s.job_id,
                                    "accepted": accepted,
                                    "error": resp.error,
                                    "rtt_ms": outcome.rtt_ms,
                                }));
                                let _ = results_tx.send(outcome).await;
                            }
                            _ => {
                                logger.emit("submit_response", &json!({
                                    "share_seq": s.seq,
                                    "job_id": s.job_id,
                                    "accepted": false,
                                    "error": "timeout",
                                    "rtt_ms": started.elapsed().as_millis(),
                                }));
                                let _ = results_tx.send(SubmitOutcome {
                                    seq: s.seq, accepted: false,
                                    error: Some(json!("timeout")),
                                    rtt_ms: started.elapsed().as_millis(),
                                }).await;
                            }
                        }
                    });
                }
            }
        }
    }

    async fn dispatch(
        &self,
        msg: ServerMessage,
        pending: &Arc<Mutex<HashMap<u64, oneshot::Sender<ServerMessage>>>>,
    ) {
        if msg.is_notification() {
            let method = msg.method.clone().unwrap_or_default();
            let params = msg.params.clone().unwrap_or(Value::Null);
            match method.as_str() {
                "mining.set_difficulty" => self.on_set_difficulty(&params).await,
                "mining.notify" => self.on_mining_notify(&params).await,
                "mining.set_extranonce" => self.on_set_extranonce(&params).await,
                _ => {
                    self.logger.emit(
                        "unknown-notify",
                        &json!({"method": method, "params": params}),
                    );
                }
            }
            return;
        }
        if let Some(id) = msg.response_id() {
            let mut p = pending.lock().await;
            if let Some(tx) = p.remove(&id) {
                let _ = tx.send(msg);
            }
        }
    }

    async fn read_until_response(
        &self,
        rdr: &mut BufReader<tokio::net::tcp::OwnedReadHalf>,
        wanted_id: u64,
        within: Duration,
        pending: &Arc<Mutex<HashMap<u64, oneshot::Sender<ServerMessage>>>>,
    ) -> Result<ServerMessage> {
        let deadline = Instant::now() + within;
        let mut line = String::new();
        loop {
            line.clear();
            let now = Instant::now();
            if now >= deadline {
                bail!("timeout waiting for response id {wanted_id}");
            }
            let n = timeout(deadline - now, rdr.read_line(&mut line)).await??;
            if n == 0 {
                bail!("EOF before response to id {wanted_id}");
            }
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let msg: ServerMessage = match serde_json::from_str(trimmed) {
                Ok(m) => m,
                Err(e) => {
                    self.logger
                        .emit("parse-error", &json!({"err": e.to_string(), "line": trimmed}));
                    continue;
                }
            };
            // Notifications during handshake are valid (set_difficulty
            // / notify can arrive before subscribe response in theory);
            // dispatch them via the same path.
            if msg.is_notification() {
                self.dispatch(msg, pending).await;
                continue;
            }
            if let Some(id) = msg.response_id() {
                if id == wanted_id {
                    return Ok(msg);
                }
                // It's a response to a different (earlier) request -
                // route through pending map.
                let mut p = pending.lock().await;
                if let Some(tx) = p.remove(&id) {
                    let _ = tx.send(msg);
                }
            }
        }
    }

    async fn on_set_difficulty(&self, params: &Value) {
        let new_diff = params
            .get(0)
            .and_then(|v| v.as_f64())
            .unwrap_or(self.default_diff);
        if new_diff <= 0.0 {
            return;
        }
        let new_target = target::target_from_share_difficulty(new_diff);
        let be_hex = target::to_be_hex_64(&new_target);
        {
            let mut s = self.state.lock().await;
            s.share_difficulty = new_diff;
            s.share_target = new_target;
            let _ = self.state_tx.send(JobUpdate { state: s.clone() });
        }
        self.logger.emit(
            "set_difficulty",
            &json!({"share_difficulty": new_diff, "share_target_be": be_hex}),
        );
    }

    async fn on_set_extranonce(&self, params: &Value) {
        let en1_hex = params.get(0).and_then(|v| v.as_str()).unwrap_or("");
        let en2_size = params.get(1).and_then(|v| v.as_u64()).unwrap_or(0) as usize;
        let bytes = match hex::decode(en1_hex) {
            Ok(b) => b,
            Err(_) => return,
        };
        {
            let mut s = self.state.lock().await;
            s.extranonce1 = bytes;
            s.extranonce2_size = en2_size;
            s.clean_epoch = s.clean_epoch.wrapping_add(1);
            let _ = self.state_tx.send(JobUpdate { state: s.clone() });
        }
        self.logger.emit(
            "set_extranonce",
            &json!({"extranonce1": en1_hex, "extranonce2_size": en2_size}),
        );
    }

    async fn on_mining_notify(&self, params: &Value) {
        let arr = match params.as_array() {
            Some(a) if a.len() >= 9 => a,
            _ => {
                self.logger.emit("notify-bad", &json!({"params": params}));
                return;
            }
        };
        let job_id = arr[0].as_str().unwrap_or("").to_string();
        let prev_be_hex = arr[1].as_str().unwrap_or("").to_string();
        let coinb1_hex = arr[2].as_str().unwrap_or("");
        let coinb2_hex = arr[3].as_str().unwrap_or("");
        let branches_arr = arr[4].as_array().cloned().unwrap_or_default();
        let ver_hex = stringify_field(&arr[5]);
        let bits_hex = stringify_field(&arr[6]);
        let ntime_hex = stringify_field(&arr[7]);
        let clean_jobs = arr[8].as_bool().unwrap_or(false);

        let coinb1 = match hex::decode(coinb1_hex) {
            Ok(b) => b,
            Err(e) => {
                self.logger
                    .emit("notify-decode-error", &json!({"err": e.to_string()}));
                return;
            }
        };
        let coinb2 = match hex::decode(coinb2_hex) {
            Ok(b) => b,
            Err(e) => {
                self.logger
                    .emit("notify-decode-error", &json!({"err": e.to_string()}));
                return;
            }
        };
        let mut branches_be = Vec::with_capacity(branches_arr.len());
        for b in &branches_arr {
            let h = b.as_str().unwrap_or("");
            let bytes = match hex::decode(h) {
                Ok(v) if v.len() == 32 => v,
                _ => {
                    self.logger
                        .emit("notify-decode-error", &json!({"err": "bad branch"}));
                    return;
                }
            };
            let mut arr32 = [0u8; 32];
            arr32.copy_from_slice(&bytes);
            branches_be.push(arr32);
        }
        let mut prev_be = [0u8; 32];
        match hex::decode(&prev_be_hex) {
            Ok(v) if v.len() == 32 => prev_be.copy_from_slice(&v),
            _ => {
                self.logger
                    .emit("notify-decode-error", &json!({"err": "bad prev_hash"}));
                return;
            }
        }
        let version = parse_hex_int(&ver_hex);
        let bits = parse_hex_int(&bits_hex);
        let ntime = parse_hex_int(&ntime_hex);

        let net_target = target::target_from_nbits(bits as u32);
        let net_diff = target::network_difficulty_from_bits(bits as u32);

        let job = CurrentJob {
            job_id: job_id.clone(),
            prev_hash_be: prev_be,
            coinb1,
            coinb2,
            merkle_branches_be: branches_be.clone(),
            version: version as u32,
            bits: bits as u32,
            ntime: ntime as u32,
            clean_jobs,
            received_at: now_secs(),
            network_target: net_target.clone(),
            network_difficulty: net_diff,
        };

        {
            let mut s = self.state.lock().await;
            s.current_job = Some(job.clone());
            if clean_jobs {
                s.clean_epoch = s.clean_epoch.wrapping_add(1);
            }
            let _ = self.state_tx.send(JobUpdate { state: s.clone() });
        }

        self.logger.emit(
            "notify",
            &json!({
                "job_id": job_id,
                "prev_hash_be": prev_be_hex,
                "coinb1": coinb1_hex,
                "coinb2": coinb2_hex,
                "merkle_branches": branches_arr.iter().map(stringify_field).collect::<Vec<_>>(),
                "version": version,
                "bits": bits,
                "ntime": ntime,
                "clean_jobs": clean_jobs,
                "network_target_be": target::to_be_hex_64(&net_target),
                "network_difficulty": net_diff,
            }),
        );
    }
}

// --- Helpers ----------------------------------------------------------------

async fn write_json_line(
    wr: &mut tokio::net::tcp::OwnedWriteHalf,
    v: &Value,
) -> Result<()> {
    let mut s = serde_json::to_string(v)?;
    s.push('\n');
    wr.write_all(s.as_bytes())
        .await
        .context("writing stratum line")?;
    wr.flush().await.context("flushing stratum line")?;
    Ok(())
}

fn parse_subscribe(resp: &ServerMessage) -> Result<(String, usize)> {
    let r = resp
        .result
        .as_ref()
        .ok_or_else(|| anyhow!("subscribe response missing result: {resp:?}"))?;
    let arr = r
        .as_array()
        .ok_or_else(|| anyhow!("subscribe result is not an array: {r:?}"))?;
    if arr.len() < 3 {
        bail!("subscribe result too short: {arr:?}");
    }
    let en1_hex = arr[1]
        .as_str()
        .ok_or_else(|| anyhow!("subscribe[1] not a string"))?
        .to_string();
    let en2_size = arr[2]
        .as_u64()
        .ok_or_else(|| anyhow!("subscribe[2] not a number"))? as usize;
    Ok((en1_hex, en2_size))
}

fn stringify_field(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => v.to_string(),
    }
}

fn parse_hex_int(s: &str) -> u64 {
    let t = s.trim();
    let t = t.strip_prefix("0x").or_else(|| t.strip_prefix("0X")).unwrap_or(t);
    u64::from_str_radix(t, 16).unwrap_or(0)
}

fn now_secs() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

