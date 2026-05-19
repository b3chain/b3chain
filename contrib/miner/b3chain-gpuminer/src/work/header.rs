// 80-byte block-header serialiser.
//
// Mirrors serialize_header() in contrib/miner/b3chain-cpuminer.py:148:
//
//   version    (4 bytes, little-endian, signed -- but always positive
//               in practice so we treat as u32)
//   prev_hash  (32 bytes, little-endian)
//   merkle_root(32 bytes, little-endian)
//   ntime      (4 bytes, little-endian, unsigned)
//   bits       (4 bytes, little-endian, unsigned)
//   nonce      (4 bytes, little-endian, unsigned)
//
// Totals 80 bytes. The GPU kernel patches the last 4 bytes (nonce) per
// thread; the host emits the first 76 unchanged.

pub const HEADER_LEN: usize = 80;
pub const NONCE_OFFSET: usize = 76;

/// Serialise a header to 80 bytes, with the nonce field set to zero.
/// The GPU kernel will overwrite bytes [76..80) per thread.
pub fn serialize_header_template(
    version: u32,
    prev_hash_le: &[u8; 32],
    merkle_root_le: &[u8; 32],
    ntime: u32,
    bits: u32,
) -> [u8; HEADER_LEN] {
    let mut h = [0u8; HEADER_LEN];
    h[0..4].copy_from_slice(&version.to_le_bytes());
    h[4..36].copy_from_slice(prev_hash_le);
    h[36..68].copy_from_slice(merkle_root_le);
    h[68..72].copy_from_slice(&ntime.to_le_bytes());
    h[72..76].copy_from_slice(&bits.to_le_bytes());
    // bytes 76..80 left as zero (nonce).
    h
}

/// Patch the nonce into a previously-serialised template.
pub fn patch_nonce(header: &mut [u8; HEADER_LEN], nonce: u32) {
    header[NONCE_OFFSET..NONCE_OFFSET + 4].copy_from_slice(&nonce.to_le_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lengths_and_offsets() {
        assert_eq!(HEADER_LEN, 80);
        assert_eq!(NONCE_OFFSET, 76);
    }

    #[test]
    fn serialize_layout() {
        let prev = [0xAAu8; 32];
        let mr = [0xBBu8; 32];
        let h = serialize_header_template(0x2000_0000, &prev, &mr, 0xDEAD_BEEF, 0x207F_FFFF);
        // version
        assert_eq!(&h[0..4], &[0x00, 0x00, 0x00, 0x20]);
        // prev hash
        assert!(h[4..36].iter().all(|&b| b == 0xAA));
        // merkle
        assert!(h[36..68].iter().all(|&b| b == 0xBB));
        // ntime
        assert_eq!(&h[68..72], &[0xEF, 0xBE, 0xAD, 0xDE]);
        // bits
        assert_eq!(&h[72..76], &[0xFF, 0xFF, 0x7F, 0x20]);
        // nonce starts as zero
        assert_eq!(&h[76..80], &[0, 0, 0, 0]);
    }

    #[test]
    fn nonce_patches_last_four_bytes() {
        let mut h = [0u8; 80];
        patch_nonce(&mut h, 0x1234_5678);
        assert_eq!(&h[76..80], &[0x78, 0x56, 0x34, 0x12]);
        // Earlier bytes untouched.
        assert!(h[0..76].iter().all(|&b| b == 0));
    }
}
