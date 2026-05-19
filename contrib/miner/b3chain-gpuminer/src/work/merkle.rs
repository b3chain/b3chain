// Merkle root from a coinbase txid + a list of branch hashes.
//
// Mirrors compute_merkle_root_from_branches() in
// contrib/miner/b3chain-cpuminer.py:511 -- the contract is that
// branches arrive over the wire in big-endian display order and must
// be reversed to little-endian before concatenation, then SHA256d'd
// pairwise with the running accumulator.

use crate::work::coinbase::double_sha256;

/// `coinbase_txid_le` is little-endian (the natural raw output of
/// SHA256d). `branches_be` are 32-byte hashes in BIG-ENDIAN display
/// order (as the pool sends them in mining.notify). Returns the
/// 32-byte merkle root in little-endian.
pub fn compute_merkle_root(coinbase_txid_le: &[u8; 32], branches_be: &[[u8; 32]]) -> [u8; 32] {
    let mut cur: [u8; 32] = *coinbase_txid_le;
    let mut buf = [0u8; 64];
    for br_be in branches_be {
        // Reverse the branch to little-endian, then SHA256d(cur || br_le).
        let mut br_le = *br_be;
        br_le.reverse();
        buf[..32].copy_from_slice(&cur);
        buf[32..].copy_from_slice(&br_le);
        cur = double_sha256(&buf);
    }
    cur
}

#[cfg(test)]
mod tests {
    use super::*;

    /// With zero branches the merkle root equals the coinbase txid.
    #[test]
    fn zero_branches_is_identity() {
        let txid: [u8; 32] = [
            1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
            25, 26, 27, 28, 29, 30, 31, 32,
        ];
        assert_eq!(compute_merkle_root(&txid, &[]), txid);
    }

    /// Single branch: result == SHA256d(txid_le || branch_le).
    #[test]
    fn single_branch_matches_explicit_compute() {
        let txid_le: [u8; 32] = [0x11; 32];
        let branch_be: [u8; 32] = [0x22; 32];
        let mut branch_le = branch_be;
        branch_le.reverse();
        let mut buf = [0u8; 64];
        buf[..32].copy_from_slice(&txid_le);
        buf[32..].copy_from_slice(&branch_le);
        let expect = double_sha256(&buf);
        let got = compute_merkle_root(&txid_le, &[branch_be]);
        assert_eq!(got, expect);
    }
}
