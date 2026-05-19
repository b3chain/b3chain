// Stratum V1 wire-format types.
//
// We model the messages in the loosest possible way: requests carry an
// id + method + params (always a JSON array), responses carry an id +
// result + error. Notifications (server-pushed) have id == null.
//
// We don't impose strict typing on `params` / `result` because the
// pool can extend the protocol with extra trailing fields and we want
// to log -- not reject -- those. Per-message decoding is done in
// stratum/client.rs.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize)]
pub struct Request {
    pub id: u64,
    pub method: &'static str,
    pub params: Value,
}

/// Either a response (matched by `id`) or a notification (`id == null`).
/// Stratum servers also sometimes send messages with both `method` and
/// a non-null `id` (request from server -> client); we treat those as
/// notifications and reply with a generic ok.
#[derive(Debug, Clone, Deserialize)]
pub struct ServerMessage {
    #[serde(default)]
    pub id: Option<Value>,
    #[serde(default)]
    pub method: Option<String>,
    #[serde(default)]
    pub params: Option<Value>,
    #[serde(default)]
    pub result: Option<Value>,
    #[serde(default)]
    pub error: Option<Value>,
}

impl ServerMessage {
    /// True if this is a notification (server-pushed event, no response
    /// required from us).
    pub fn is_notification(&self) -> bool {
        self.method.is_some()
            && matches!(self.id, None | Some(Value::Null))
    }

    /// True if this is a response to one of our requests.
    pub fn is_response(&self) -> bool {
        // It's a response iff there's an integer id AND no method name.
        self.method.is_none()
            && matches!(&self.id, Some(v) if v.is_number())
    }

    /// Returns the response id as u64 if it exists.
    pub fn response_id(&self) -> Option<u64> {
        self.id.as_ref().and_then(|v| v.as_u64())
    }
}
