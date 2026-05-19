// Coinbase splice. Mirrors build_coinbase_full() in
// contrib/miner/b3chain-cpuminer.py:501.
//
// The pool sends coinb1 / coinb2 pre-split around an 8-byte placeholder.
// The miner inserts en1 || en2 between the halves.

pub fn build_coinbase(coinb1: &[u8], en1: &[u8], en2: &[u8], coinb2: &[u8]) -> Vec<u8> {
    let mut v = Vec::with_capacity(coinb1.len() + en1.len() + en2.len() + coinb2.len());
    v.extend_from_slice(coinb1);
    v.extend_from_slice(en1);
    v.extend_from_slice(en2);
    v.extend_from_slice(coinb2);
    v
}

/// SHA256(SHA256(x)). Bitcoin txid hash.
pub fn double_sha256(input: &[u8]) -> [u8; 32] {
    use sha2::{Digest, Sha256};
    let h1 = Sha256::digest(input);
    let h2 = Sha256::digest(h1);
    let mut out = [0u8; 32];
    out.copy_from_slice(&h2);
    out
}

/// Coinbase txid in little-endian (== double_sha256(coinbase) since
/// Bitcoin txids are stored LE on the wire).
pub fn coinbase_txid_le(coinbase: &[u8]) -> [u8; 32] {
    double_sha256(coinbase)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splice_concatenates_in_order() {
        let v = build_coinbase(b"AAA", b"BB", b"CC", b"DDD");
        assert_eq!(v, b"AAABBCCDDD");
    }

    #[test]
    fn double_sha256_known_vector() {
        // SHA256d("") == 5df6e0e2 76135864 9d99f8e4 e2c0c4d4 ...
        // See https://en.bitcoin.it/wiki/Test_Cases (or any double-sha
        // reference impl). We compare hex of the first 8 bytes here.
        let h = double_sha256(b"");
        assert_eq!(&hex::encode(h)[..16], "5df6e0e276135864");
    }
}
