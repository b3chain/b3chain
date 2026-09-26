//! Host B3PoW-Scratch v1.1.1. Matches `b3miner-rtl/ref/b3pow_ref.py`.
//! Used to build the parent pad once per job and to recheck a GPU share
//! before it is submitted.

const SCRATCH_BYTES: usize = 1_048_576;
const LANES: usize = 8;
const LANE_BYTES: usize = SCRATCH_BYTES / LANES;
const BLOCK_BYTES: usize = 64;
const LANE_BLOCKS: usize = LANE_BYTES / BLOCK_BYTES;
const ITERATIONS: usize = 2048;
const INNER_ROUNDS: usize = 2;

const BLAKE3_IV: [u32; 8] = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
];
const BLAKE3_PERM: [usize; 16] = [2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8];
const ITER_MUL: [u64; 8] = [
    0xA0761D6478BD642F,
    0xE7037ED1A0B428DB,
    0x8EBC6AF09C88C6E3,
    0x589965CC75374CC3,
    0x1D8E4E27C47D124F,
    0xEB44ACCAB455D165,
    0xC863B19A77C75D70,
    0x6E5C6F88AA5BDA77,
];
const LANE_SHUFFLE: [usize; 8] = [1, 6, 3, 0, 5, 2, 7, 4];

fn rotr32(x: u32, n: u32) -> u32 {
    x.rotate_right(n)
}

fn g(s: &mut [u32; 16], a: usize, b: usize, c: usize, d: usize, mx: u32, my: u32) {
    s[a] = s[a].wrapping_add(s[b]).wrapping_add(mx);
    s[d] = rotr32(s[d] ^ s[a], 16);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] = rotr32(s[b] ^ s[c], 12);
    s[a] = s[a].wrapping_add(s[b]).wrapping_add(my);
    s[d] = rotr32(s[d] ^ s[a], 8);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] = rotr32(s[b] ^ s[c], 7);
}

fn round_fn(state: &mut [u32; 16], m: &[u32; 16]) {
    g(state, 0, 4, 8, 12, m[0], m[1]);
    g(state, 1, 5, 9, 13, m[2], m[3]);
    g(state, 2, 6, 10, 14, m[4], m[5]);
    g(state, 3, 7, 11, 15, m[6], m[7]);
    g(state, 0, 5, 10, 15, m[8], m[9]);
    g(state, 1, 6, 11, 12, m[10], m[11]);
    g(state, 2, 7, 8, 13, m[12], m[13]);
    g(state, 3, 4, 9, 14, m[14], m[15]);
}

fn permute_msg(m: &[u32; 16]) -> [u32; 16] {
    let mut out = [0u32; 16];
    for i in 0..16 {
        out[i] = m[BLAKE3_PERM[i]];
    }
    out
}

fn le_words(buf: &[u8]) -> Vec<u32> {
    buf.chunks_exact(4)
        .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}

fn pack_le_words(words: &[u32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(words.len() * 4);
    for w in words {
        out.extend_from_slice(&w.to_le_bytes());
    }
    out
}

fn blake3_hash(input: &[u8]) -> [u8; 32] {
    *blake3::hash(input).as_bytes()
}

fn blake3_xof(input: &[u8], out: &mut [u8]) {
    let mut hasher = blake3::Hasher::new();
    hasher.update(input);
    hasher.finalize_xof().fill(out);
}

/// Parent-derived 1 MiB pad. Reused for every nonce of the same parent.
pub fn init_scratchpad(prev_block_hash: &[u8; 32]) -> Vec<u8> {
    let mut pad = vec![0u8; SCRATCH_BYTES];
    let mut input = [0u8; 36];
    input[..32].copy_from_slice(prev_block_hash);
    for i in 0..(SCRATCH_BYTES / BLOCK_BYTES) {
        input[32..36].copy_from_slice(&(i as u32).to_le_bytes());
        let start = i * BLOCK_BYTES;
        blake3_xof(&input, &mut pad[start..start + BLOCK_BYTES]);
    }
    pad
}

fn init_lanes(seed: &[u8; 32]) -> [[u8; 32]; 8] {
    let mut lanes = [[0u8; 32]; 8];
    for (lane, out) in lanes.iter_mut().enumerate() {
        let mut msg = [0u8; 36];
        msg[..32].copy_from_slice(seed);
        msg[32..36].copy_from_slice(&(lane as u32).to_le_bytes());
        *out = blake3_hash(&msg);
    }
    lanes
}

fn derive_addresses(lanes: &[[u8; 32]; 8], iter_idx: u64) -> [usize; 8] {
    let mut addrs = [0usize; 8];
    for lane in 0..LANES {
        let lo = u64::from_le_bytes(lanes[lane][0..8].try_into().unwrap());
        let hi = u64::from_le_bytes(lanes[lane][8..16].try_into().unwrap());
        let mul = (hi ^ iter_idx).wrapping_mul(ITER_MUL[lane]);
        let mixed = lo ^ mul.rotate_right(23);
        addrs[lane] = (mixed as usize) & (LANE_BLOCKS - 1);
    }
    addrs
}

fn mix_step(lanes: &[[u8; 32]; 8], blocks: &[[u8; 64]; 8]) -> ([[u8; 32]; 8], [[u8; 64]; 8]) {
    let mut computed = [[0u8; 32]; 8];
    let mut written = [[0u8; 64]; 8];
    for lane in 0..LANES {
        let cv = le_words(&lanes[lane]);
        let msg0 = le_words(&blocks[lane]);
        let mut state = [0u32; 16];
        for i in 0..8 {
            state[i] = cv[i];
        }
        for i in 0..4 {
            state[8 + i] = BLAKE3_IV[i];
        }
        state[12] = 0;
        state[13] = 0;
        state[14] = BLOCK_BYTES as u32;
        state[15] = 0;
        let mut m = [0u32; 16];
        m.copy_from_slice(&msg0);
        for _ in 0..INNER_ROUNDS {
            round_fn(&mut state, &m);
            m = permute_msg(&m);
        }
        let mut new_cv = [0u32; 8];
        for i in 0..8 {
            new_cv[i] = state[i] ^ state[i + 8];
        }
        computed[lane].copy_from_slice(&pack_le_words(&new_cv));
        let permuted = pack_le_words(&m);
        for i in 0..BLOCK_BYTES {
            written[lane][i] = blocks[lane][i] ^ permuted[i];
        }
    }
    let mut shuffled = [[0u8; 32]; 8];
    for lane in 0..LANES {
        shuffled[lane] = computed[LANE_SHUFFLE[lane]];
    }
    (shuffled, written)
}

/// Full PoW hash. `pad` is mutated; pass a fresh parent pad per nonce.
pub fn b3pow_scratch_on_pad(header: &[u8; 80], pad: &mut [u8]) -> [u8; 32] {
    assert_eq!(pad.len(), SCRATCH_BYTES);
    let seed = blake3_hash(header);
    let mut lanes = init_lanes(&seed);
    for iter in 0..ITERATIONS {
        let addrs = derive_addresses(&lanes, iter as u64);
        let mut blocks = [[0u8; 64]; 8];
        for lane in 0..LANES {
            let base = lane * LANE_BYTES + addrs[lane] * BLOCK_BYTES;
            blocks[lane].copy_from_slice(&pad[base..base + BLOCK_BYTES]);
        }
        let (new_lanes, new_blocks) = mix_step(&lanes, &blocks);
        for lane in 0..LANES {
            let base = lane * LANE_BYTES + addrs[lane] * BLOCK_BYTES;
            pad[base..base + BLOCK_BYTES].copy_from_slice(&new_blocks[lane]);
        }
        lanes = new_lanes;
    }
    let mut final_msg = Vec::with_capacity(260);
    for lane in &lanes {
        final_msg.extend_from_slice(lane);
    }
    final_msg.extend_from_slice(&header[76..80]);
    blake3_hash(&final_msg)
}

pub fn b3pow_scratch(header: &[u8; 80], prev_block_hash: &[u8; 32]) -> [u8; 32] {
    let mut pad = init_scratchpad(prev_block_hash);
    b3pow_scratch_on_pad(header, &mut pad)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cache_pair_nonce_0_and_1() {
        let h0 = hex::decode("010000000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f2000000000000000000000000000000000000000000000000000000000000000008041a967ffff7f1d00000000").unwrap();
        let h1 = hex::decode("010000000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f2000000000000000000000000000000000000000000000000000000000000000008041a967ffff7f1d01000000").unwrap();
        let prev = hex::decode("0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20").unwrap();
        let mut header0 = [0u8; 80];
        let mut header1 = [0u8; 80];
        let mut parent = [0u8; 32];
        header0.copy_from_slice(&h0);
        header1.copy_from_slice(&h1);
        parent.copy_from_slice(&prev);
        let g0 = b3pow_scratch(&header0, &parent);
        let g1 = b3pow_scratch(&header1, &parent);
        assert_eq!(hex::encode(g0), "c9b61079e2e50c4dacc51af107043d4a0b47c84945bc8d6d1df6b801b6430313");
        assert_eq!(hex::encode(g1), "fa6993083b67ebb0a4876f65d94ded886fb75e46cab7f4283ca7c13abbf89e18");
    }
}
