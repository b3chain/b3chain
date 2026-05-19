// Phase B exit criterion: the Stratum client completes a full
// subscribe/authorize handshake against an in-process mock server that
// matches the wire behaviour of the real pool, then receives one
// set_difficulty + one notify and surfaces both via the watch channel.
//
// Direct port of the MockStratumServer in
// contrib/miner/test_pool_miner.py (so we drive the new client through
// the same scenarios as the Python miner already passes).
//
// We do NOT exercise mining.submit in this test -- that requires the
// GPU to find a candidate first, which is Phase C territory. We only
// confirm: connect, subscribe, authorize, set_difficulty, notify all
// reach the right state.

use serde_json::{json, Value};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream};
use tokio::time::timeout;

use b3chain_gpuminer::stratum::client::Client;
use b3chain_gpuminer::util::log::JsonlLogger;

const EXTRANONCE1: &str = "deadbeef";
const EXTRANONCE2_SIZE: u64 = 4;
const JOB_ID: &str = "0000001";
const PREV_BE: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const COINB1_HEX: &str = "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff10";
const COINB2_HEX: &str = "0a2f6233636861696e2fffffffff0100f9029500000000160014deadbeefdeadbeefdeadbeefdeadbeefdeadbeef00000000";
const VERSION: u32 = 0x2000_0000;
const BITS: u32 = 0x207f_ffff;
const SHARE_DIFFICULTY: f64 = 0.0001;

async fn write_line(wr: &mut tokio::net::tcp::OwnedWriteHalf, v: Value) {
    let mut s = serde_json::to_string(&v).unwrap();
    s.push('\n');
    let _ = wr.write_all(s.as_bytes()).await;
    let _ = wr.flush().await;
}

async fn run_mock_server(listener: TcpListener) {
    let (sock, _peer) = match listener.accept().await {
        Ok(p) => p,
        Err(_) => return,
    };
    let _ = sock.set_nodelay(true);
    let (rd, mut wr) = sock.into_split();
    let mut rdr = BufReader::new(rd);
    let mut line = String::new();

    loop {
        line.clear();
        let n = match timeout(Duration::from_secs(15), rdr.read_line(&mut line)).await {
            Ok(Ok(n)) => n,
            _ => return,
        };
        if n == 0 {
            return;
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let msg: Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(_) => return,
        };
        let id = msg.get("id").cloned().unwrap_or(Value::Null);
        let method = msg.get("method").and_then(|v| v.as_str()).unwrap_or("");
        match method {
            "mining.subscribe" => {
                write_line(
                    &mut wr,
                    json!({
                        "id": id,
                        "result": [
                            [["mining.set_difficulty", "subid"], ["mining.notify", "subid"]],
                            EXTRANONCE1,
                            EXTRANONCE2_SIZE,
                        ],
                        "error": null,
                    }),
                )
                .await;
            }
            "mining.authorize" => {
                write_line(&mut wr, json!({"id": id, "result": true, "error": null})).await;
                let ntime = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|d| d.as_secs() as u32)
                    .unwrap_or(0);
                write_line(
                    &mut wr,
                    json!({
                        "id": null,
                        "method": "mining.set_difficulty",
                        "params": [SHARE_DIFFICULTY],
                    }),
                )
                .await;
                write_line(
                    &mut wr,
                    json!({
                        "id": null,
                        "method": "mining.notify",
                        "params": [
                            JOB_ID,
                            PREV_BE,
                            COINB1_HEX,
                            COINB2_HEX,
                            [] as [Value; 0],
                            format!("0x{:08x}", VERSION),
                            format!("0x{:08x}", BITS),
                            format!("0x{:08x}", ntime),
                            true,
                        ],
                    }),
                )
                .await;
            }
            "mining.submit" => {
                write_line(&mut wr, json!({"id": id, "result": true, "error": null})).await;
            }
            _ => {
                write_line(&mut wr, json!({"id": id, "result": true, "error": null})).await;
            }
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn full_handshake_and_first_notify() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(run_mock_server(listener));

    let logger = Arc::new(JsonlLogger::null());
    let (client, handle) = Client::new(
        addr.ip().to_string(),
        addr.port(),
        false,
        "test@b3chain.org.gpu1",
        "x",
        "b3chain-gpuminer-test/0.1",
        1024.0,
        logger,
    );

    let client_task = tokio::spawn(async move {
        // run_forever loops; we only need one session to land. The
        // test will drop the handle which closes submit_tx and lets
        // the client task exit naturally on next reconnect attempt.
        let _ = client.run_forever().await;
    });

    // Wait for the state to surface a job + non-empty extranonce1 +
    // share_difficulty == 0.0001.
    let mut state_rx = handle.state_rx.clone();
    let mut got_job = false;
    let deadline = tokio::time::Instant::now() + Duration::from_secs(15);
    while tokio::time::Instant::now() < deadline {
        let s = state_rx.borrow().state.clone();
        if s.current_job.is_some()
            && !s.extranonce1.is_empty()
            && (s.share_difficulty - SHARE_DIFFICULTY).abs() < 1e-9
        {
            let j = s.current_job.unwrap();
            assert_eq!(j.job_id, JOB_ID);
            assert_eq!(j.bits, BITS);
            assert_eq!(j.version, VERSION);
            assert_eq!(s.extranonce1, hex::decode(EXTRANONCE1).unwrap());
            assert_eq!(s.extranonce2_size, EXTRANONCE2_SIZE as usize);
            got_job = true;
            break;
        }
        if state_rx.changed().await.is_err() {
            break;
        }
    }
    assert!(got_job, "did not see a notify within 15s");

    client_task.abort();
}

/// Exercise a parse_stratum_url + connect roundtrip against the same
/// mock, just to make sure the URL parser ports cleanly.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn url_parse_and_connect() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        // Just accept and close.
        let _ = listener.accept().await;
    });

    let url = format!("stratum+tcp://{}:{}", addr.ip(), addr.port());
    let endpoint = b3chain_gpuminer::util::url::parse_stratum_url(&url).unwrap();
    assert_eq!(endpoint.port, addr.port());
    assert!(!endpoint.use_tls);
    // Round-trip TCP connect.
    let _stream = TcpStream::connect((endpoint.host.as_str(), endpoint.port))
        .await
        .unwrap();
}
