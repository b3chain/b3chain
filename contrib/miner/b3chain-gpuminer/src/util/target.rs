// Target / difficulty math.
//
// Mirrors `target_from_share_difficulty` and `target_from_nbits` in
// contrib/miner/b3chain-cpuminer.py and the canonical pool
// implementation at contrib/testnet/pool/src/lib/difficulty-math.ts.
//
// Byte-identical output is the contract: a target produced here MUST
// be the same 32 little-endian bytes that the pool produces, otherwise
// shares we believe are valid will be rejected.

use num_bigint::BigUint;
use num_traits::{One, Zero};

/// Pool diff-1 target (constant, mirrors POOL_DIFF1_TARGET in the
/// Python miner and the TS pool).
///
///   0x00000000 ffff0000 0000... (256 bits, big-endian display order)
pub fn pool_diff1_target() -> BigUint {
    // 256-bit value with 0xFFFF in bytes 30..28 (big-endian indexing).
    BigUint::parse_bytes(
        b"00000000ffff0000000000000000000000000000000000000000000000000000",
        16,
    )
    .expect("pool_diff1_target: hex parse")
}

/// share_target = floor(POOL_DIFF1_TARGET / share_difficulty)
///
/// Uses a 1_000_000 scale so fractional difficulties (e.g. the test-net
/// 0.0001) survive the integer divide. Mirrors
/// targetFromShareDifficulty() in difficulty-math.ts.
pub fn target_from_share_difficulty(share_diff: f64) -> BigUint {
    if !share_diff.is_finite() || share_diff <= 0.0 {
        return uint256_max();
    }
    let scale: u64 = 1_000_000;
    let scaled = (share_diff * scale as f64) as i128;
    if scaled <= 0 {
        return uint256_max();
    }
    let scaled_b = BigUint::from(scaled as u128);
    let lhs = pool_diff1_target() * BigUint::from(scale);
    lhs / scaled_b
}

/// Convert compact nBits to a 256-bit target.
///
/// Bitcoin-style: top byte is the exponent, low 23 bits are the
/// mantissa, sign bit (bit 23) is NOT used here (b3chain rejects
/// negative targets at consensus).
pub fn target_from_nbits(nbits: u32) -> BigUint {
    let exp = (nbits >> 24) as u32;
    let mant = (nbits & 0x007f_ffff) as u32;
    let mant = BigUint::from(mant);
    if exp <= 3 {
        // Right-shift the mantissa.
        let shift = 8 * (3 - exp);
        mant >> shift
    } else {
        // Left-shift the mantissa.
        let shift = 8 * (exp - 3);
        mant << shift
    }
}

/// Network difficulty corresponding to nBits (diff-1 units).
pub fn network_difficulty_from_bits(nbits: u32) -> f64 {
    let target = target_from_nbits(nbits);
    if target.is_zero() {
        return f64::INFINITY;
    }
    let scale: u64 = 10_000_000;
    let lhs = pool_diff1_target() * BigUint::from(scale);
    let q = lhs / target;
    // Convert quotient to f64. Quotient < 2^63 in practice for any
    // realistic difficulty; we use to_string() round-trip to dodge
    // BigUint's lack of a direct f64 conversion in older versions.
    let s = q.to_string();
    s.parse::<f64>().unwrap_or(f64::NAN) / scale as f64
}

/// 256-bit max value (= (1 << 256) - 1).
pub fn uint256_max() -> BigUint {
    let mut v = BigUint::one();
    v <<= 256;
    v - BigUint::one()
}

/// Convert a 256-bit BigUint into 32 little-endian bytes (zero-padded /
/// truncated to fit). Matches Python's `int.to_bytes(32, "little")`.
pub fn to_le_bytes_32(v: &BigUint) -> [u8; 32] {
    let mut out = [0u8; 32];
    let bytes = v.to_bytes_le();
    let n = bytes.len().min(32);
    out[..n].copy_from_slice(&bytes[..n]);
    out
}

/// Big-endian hex string ("00..ffff..") for logging.
pub fn to_be_hex_64(v: &BigUint) -> String {
    let mut le = to_le_bytes_32(v);
    le.reverse();
    hex::encode(le)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The Python miner serialises the diff-1 target as
    ///   00000000ffff0000000000000000000000000000000000000000000000000000
    /// (big-endian). Make sure our BigUint round-trips that exact string.
    #[test]
    fn diff1_target_be_hex_matches_python() {
        let v = pool_diff1_target();
        assert_eq!(
            to_be_hex_64(&v),
            "00000000ffff0000000000000000000000000000000000000000000000000000"
        );
    }

    /// share_diff = 1 -> target == diff1.
    #[test]
    fn share_diff_one_equals_diff1() {
        let t = target_from_share_difficulty(1.0);
        assert_eq!(t, pool_diff1_target());
    }

    /// share_diff = 1024 (the default in the Python miner) gives
    /// the value the miner has been logging:
    ///   0x00000000003fffc0...   (BE; exact bits depend on the divide)
    /// We just check the BE hex for the leading bytes.
    #[test]
    fn share_diff_1024_leading_bytes() {
        let t = target_from_share_difficulty(1024.0);
        let be = to_be_hex_64(&t);
        // 0xffff0000 / 1024 = 0x003fffc0..., scaled match.
        assert!(be.starts_with("00000000003fffc"), "got {be}");
    }

    /// nBits = 0x1d1ffff0 (b3chain mainnet/testnet tip we keep
    /// seeing in notify) decodes to a target with leading zero bytes.
    #[test]
    fn nbits_decode_known_value() {
        let t = target_from_nbits(0x1d1f_fff0);
        let be = to_be_hex_64(&t);
        // exp=0x1d=29 -> shift left by 8*(29-3)=208 bits = 26 bytes.
        // Mantissa 0x1ffff0 occupies bytes [3..6) (BE), then 26 bytes of 0.
        assert!(be.starts_with("0000001ffff0"), "got {be}");
    }
}
