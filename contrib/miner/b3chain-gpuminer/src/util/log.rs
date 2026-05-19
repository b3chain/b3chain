// JSONL logger -- writes the SAME event schema as the Python miner so
// the live mining dashboard at contrib/miner/tests/mining_dashboard.py
// can ingest GPU-miner output unchanged.
//
// Schema:
//   * Every line is a single JSON object terminated by '\n'.
//   * Every object has at least:
//       "ts":  unix epoch float (seconds), 6-digit precision
//       "event": short event name (e.g. "connect", "share_submit")
//   * The remaining fields are event-specific and MUST match the Python
//     miner exactly so the dashboard parser keeps working. See
//     `JsonlLogger.emit()` and the per-event call sites in
//     contrib/miner/b3chain-cpuminer.py.
//
// Implementation notes:
//   * We don't buffer; each emit() flushes. The miner emits a few hundred
//     events per second at most (mostly progress + share); the file
//     writes are absorbed by the OS page cache.
//   * Internally guarded by a Mutex so multiple async tasks can share
//     one logger.

use anyhow::{Context, Result};
use serde::Serialize;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub struct JsonlLogger {
    inner: Mutex<Option<File>>,
}

impl JsonlLogger {
    pub fn open(path: Option<&Path>) -> Result<Self> {
        let inner = match path {
            None => None,
            Some(p) => {
                let f = File::options()
                    .create(true)
                    .append(true)
                    .open(p)
                    .with_context(|| format!("opening JSONL log {}", p.display()))?;
                Some(f)
            }
        };
        Ok(Self {
            inner: Mutex::new(inner),
        })
    }

    pub fn null() -> Self {
        Self {
            inner: Mutex::new(None),
        }
    }

    /// Emit one event. `payload` MUST serialise to a JSON object; we
    /// inject `ts` and `event` ourselves so callers can't accidentally
    /// override them.
    pub fn emit<S: Serialize>(&self, event: &str, payload: &S) {
        let line = match build_line(event, payload) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("logger: serialise '{event}' failed: {e}");
                return;
            }
        };
        if let Some(file) = self.inner.lock().unwrap().as_mut() {
            if let Err(e) = file.write_all(line.as_bytes()) {
                eprintln!("logger: write failed: {e}");
            }
        }
    }
}

fn build_line<S: Serialize>(event: &str, payload: &S) -> Result<String> {
    // Build the JSON line manually so "ts" and "event" come first
    // (matching the Python miner's field order, which the dashboard
    // doesn't depend on but is nice for grep-by-eye).
    let val = serde_json::to_value(payload)?;
    let payload_obj = val
        .as_object()
        .ok_or_else(|| anyhow::anyhow!("logger payload must be a JSON object"))?;

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);

    let mut s = String::with_capacity(64 + payload_obj.len() * 32);
    s.push('{');
    // ts as a JSON number with full f64 precision.
    s.push_str("\"ts\":");
    s.push_str(&serde_json::to_string(&now)?);
    s.push_str(",\"event\":");
    s.push_str(&serde_json::to_string(event)?);
    for (k, v) in payload_obj {
        s.push(',');
        s.push_str(&serde_json::to_string(k)?);
        s.push(':');
        s.push_str(&serde_json::to_string(v)?);
    }
    s.push('}');
    s.push('\n');
    Ok(s)
}

/// Convert a unix-epoch float to the same ISO-8601 millisecond format
/// the Python miner uses for stdout (utc_iso() in b3chain-cpuminer.py).
pub fn utc_iso(t: f64) -> String {
    let secs = t.trunc() as i64;
    let ms = ((t.fract() * 1000.0).round() as i64).clamp(0, 999);
    let dt = chrono::DateTime::<chrono::Utc>::from_timestamp(secs, 0)
        .unwrap_or_else(|| chrono::DateTime::<chrono::Utc>::from_timestamp(0, 0).unwrap());
    format!("{}.{:03}Z", dt.format("%Y-%m-%dT%H:%M:%S"), ms)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use tempfile_lite::TempDir;

    // Inline a tiny tempfile shim so we don't need the `tempfile` dep
    // just for one test. Lives in this test module only.
    mod tempfile_lite {
        use std::path::{Path, PathBuf};
        pub struct TempDir(PathBuf);
        impl TempDir {
            pub fn new() -> std::io::Result<Self> {
                let mut p = std::env::temp_dir();
                p.push(format!(
                    "b3chain-gpuminer-test-{}",
                    std::process::id()
                ));
                std::fs::create_dir_all(&p)?;
                Ok(Self(p))
            }
            pub fn path(&self) -> &Path {
                &self.0
            }
        }
        impl Drop for TempDir {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
    }

    #[test]
    fn emits_object_with_ts_and_event_first() {
        let dir = TempDir::new().unwrap();
        let p = dir.path().join("log.jsonl");
        let l = JsonlLogger::open(Some(&p)).unwrap();
        l.emit("connect", &serde_json::json!({
            "host": "127.0.0.1",
            "port": 58397u16,
            "use_tls": false
        }));
        let mut s = String::new();
        File::open(&p).unwrap().read_to_string(&mut s).unwrap();
        let line = s.trim_end();
        assert!(line.starts_with(r#"{"ts":"#), "got {line}");
        assert!(line.contains(r#""event":"connect""#));
        assert!(line.contains(r#""host":"127.0.0.1""#));
    }

    #[test]
    fn null_logger_is_silent() {
        let l = JsonlLogger::null();
        l.emit("noop", &serde_json::json!({"a": 1}));
    }

    #[test]
    fn utc_iso_format_smoketest() {
        let s = utc_iso(1700000000.123);
        assert!(s.ends_with("Z"));
        assert!(s.contains("T"));
        // millisecond field has 3 digits.
        let ms = &s[s.len() - 4..s.len() - 1];
        assert_eq!(ms.len(), 3);
    }
}
