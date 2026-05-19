// Stratum URL parser. Mirrors parse_stratum_url() in
// contrib/miner/b3chain-cpuminer.py:196 byte-for-byte.

use anyhow::{anyhow, bail, Result};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StratumEndpoint {
    pub host: String,
    pub port: u16,
    pub use_tls: bool,
}

pub fn parse_stratum_url(url: &str) -> Result<StratumEndpoint> {
    let raw = url.trim();
    if raw.starts_with("stratum2://") {
        bail!(
            "Stratum V2 (stratum2://) is not supported by this miner. \
             Use the pool's V1 endpoint at stratum+tcp://...:3333."
        );
    }

    let (use_tls, after_scheme) = if let Some(rest) = raw.strip_prefix("stratum+tcp+ssl://") {
        (true, rest)
    } else if let Some(rest) = raw.strip_prefix("stratum+ssl://") {
        (true, rest)
    } else if let Some(rest) = raw.strip_prefix("stratum+tcp://") {
        (false, rest)
    } else if raw.contains("://") {
        let scheme = raw.split("://").next().unwrap_or("");
        bail!("Unknown stratum URL scheme '{scheme}://' in {url:?}");
    } else {
        (false, raw)
    };

    // Strip a path component if present.
    let host_port = after_scheme.split('/').next().unwrap_or("");
    let (host, port) = host_port
        .rsplit_once(':')
        .ok_or_else(|| anyhow!("Stratum URL missing port: {url:?}"))?;
    if host.is_empty() {
        bail!("Stratum URL missing host: {url:?}");
    }
    let port: u16 = port
        .parse()
        .map_err(|e| anyhow!("Bad port in stratum URL {url:?}: {port} ({e})"))?;
    Ok(StratumEndpoint {
        host: host.to_string(),
        port,
        use_tls,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_plain_tcp() {
        let e = parse_stratum_url("stratum+tcp://pool.b3chain.org:3333").unwrap();
        assert_eq!(e.host, "pool.b3chain.org");
        assert_eq!(e.port, 3333);
        assert!(!e.use_tls);
    }

    #[test]
    fn parse_tls_via_ssl_alias() {
        let e = parse_stratum_url("stratum+ssl://pool.b3chain.org:3334").unwrap();
        assert!(e.use_tls);
        assert_eq!(e.port, 3334);
    }

    #[test]
    fn parse_tls_via_tcp_ssl_alias() {
        let e = parse_stratum_url("stratum+tcp+ssl://pool.b3chain.org:3334").unwrap();
        assert!(e.use_tls);
    }

    #[test]
    fn parse_no_scheme() {
        let e = parse_stratum_url("127.0.0.1:58397").unwrap();
        assert_eq!(e.host, "127.0.0.1");
        assert_eq!(e.port, 58397);
    }

    #[test]
    fn rejects_v2() {
        assert!(parse_stratum_url("stratum2://pool:3333").is_err());
    }

    #[test]
    fn rejects_unknown_scheme() {
        assert!(parse_stratum_url("ws://pool:3333").is_err());
    }

    #[test]
    fn rejects_missing_port() {
        assert!(parse_stratum_url("stratum+tcp://pool").is_err());
    }
}
