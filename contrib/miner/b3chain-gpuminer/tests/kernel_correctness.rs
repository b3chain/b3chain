// Phase A exit criterion: the GPU kernel must produce bitwise-identical
// output to the reference `blake3` crate over a large batch of random
// inputs.
//
// Strategy:
//
//   1. Generate 100k random 80-byte headers (the realistic miner input).
//   2. Hash each on the host: blake3(blake3(input).as_bytes()).
//   3. Hash each on the GPU via MinerKernel::double_blake3_dump.
//   4. Compare byte-for-byte. Single mismatch fails the test with the
//      offending input + both digests printed.
//
// We also test:
//
//   * 1-byte through 80-byte inputs (tail padding logic in
//     hash_single_chunk).
//   * Inputs spanning 1, 2, 16 blocks (boundary at 64-byte multiples).
//
// If no CUDA device is available, the test prints "skipped (no CUDA)"
// and passes; CI is expected to run this on a machine with a GPU.

#![cfg(feature = "cuda")]

use rand::{Rng, RngCore, SeedableRng};

use b3chain_gpuminer::gpu::MinerKernel;

const HEADERS: usize = 100_000;

fn host_double_blake3(input: &[u8]) -> [u8; 32] {
    let h1 = blake3::hash(input);
    let h2 = blake3::hash(h1.as_bytes());
    *h2.as_bytes()
}

fn try_open_gpu() -> Option<MinerKernel> {
    match MinerKernel::new(0) {
        Ok(k) => Some(k),
        Err(e) => {
            eprintln!("kernel_correctness: skipping (no CUDA: {e:#})");
            None
        }
    }
}

#[test]
fn double_blake3_matches_host_for_80byte_headers() {
    let Some(kernel) = try_open_gpu() else {
        return;
    };

    let mut rng = rand::rngs::StdRng::seed_from_u64(0xb3_b3_c4);
    let mut header = [0u8; 80];
    let mut mismatches = 0usize;
    for i in 0..HEADERS {
        rng.fill_bytes(&mut header);
        let want = host_double_blake3(&header);
        let got = kernel
            .double_blake3_dump(&header)
            .expect("kernel dump call");
        if want != got {
            if mismatches < 3 {
                eprintln!(
                    "MISMATCH at iter {i}:\n  header  = {}\n  want    = {}\n  got     = {}",
                    hex::encode(header),
                    hex::encode(want),
                    hex::encode(got)
                );
            }
            mismatches += 1;
        }
    }
    assert_eq!(
        mismatches, 0,
        "{mismatches} of {HEADERS} 80-byte hashes did not match host reference"
    );
}

#[test]
fn double_blake3_matches_host_for_short_inputs() {
    let Some(kernel) = try_open_gpu() else {
        return;
    };

    // Sweep 1..=130 bytes, exercising the 64-byte block boundary
    // (block 1 -> block 2 transition, where CHUNK_END flag attaches).
    let mut rng = rand::rngs::StdRng::seed_from_u64(0x5eed_5eed);
    for len in 1..=130usize {
        let mut buf = vec![0u8; len];
        rng.fill_bytes(&mut buf);
        let want = host_double_blake3(&buf);
        let got = kernel.double_blake3_dump(&buf).expect("kernel dump call");
        assert_eq!(
            want, got,
            "mismatch at len={len}: host={} gpu={}",
            hex::encode(want),
            hex::encode(got)
        );
    }
}

#[test]
fn double_blake3_matches_host_at_block_boundaries() {
    let Some(kernel) = try_open_gpu() else {
        return;
    };

    // Exact multiples of 64 hit the "is_last && tail == 0" path.
    for &len in &[64usize, 128, 192, 256, 320, 384, 448, 512, 576, 640, 704, 768, 832, 896, 960, 1024] {
        let mut buf = vec![0u8; len];
        // Deterministic, non-zero pattern so a swapped index would
        // surface as a hash difference (an all-zeros input has the
        // same hash regardless of order).
        for (i, b) in buf.iter_mut().enumerate() {
            *b = (i as u8).wrapping_mul(31).wrapping_add(7);
        }
        let want = host_double_blake3(&buf);
        let got = kernel.double_blake3_dump(&buf).expect("kernel dump call");
        assert_eq!(
            want, got,
            "boundary mismatch at len={len}: host={} gpu={}",
            hex::encode(want),
            hex::encode(got)
        );
    }
}

#[test]
fn search_kernel_finds_solution_under_loose_target() {
    // With the most-permissive 256-bit target (all 0xFF), the very first
    // nonce we try MUST produce a "candidate" (every hash is <= target).
    // That validates the search-side wiring (atomicAdd, results buffer,
    // header patching) end-to-end.
    let Some(mut kernel) = try_open_gpu() else {
        return;
    };

    // A deterministic header template -- the test asserts on candidate
    // count and header reconstruction, not on the digest itself.
    let mut header = [0u8; 80];
    for (i, b) in header.iter_mut().enumerate() {
        *b = (i as u8).wrapping_mul(13).wrapping_add(2);
    }
    let target = [0xffu8; 32];

    let plan = b3chain_gpuminer::gpu::KernelLaunch {
        header_template_le: &header,
        share_target_le: &target,
        nonce_start: 0,
        nonce_count: 256,
        block_size: 64,
    };
    let res = kernel.launch(plan).expect("kernel launch");
    // Every nonce in [0, 256) hit the target -- but we cap at 64 results.
    assert!(res.candidates.len() == 64, "expected 64 candidates, got {}", res.candidates.len());
    assert!(res.overflow, "expected overflow with all-FF target");

    // Reconstruct one candidate's hash on the host and compare.
    let cand = &res.candidates[0];
    let mut h = header;
    h[76..80].copy_from_slice(&cand.nonce.to_le_bytes());
    let want = host_double_blake3(&h);
    assert_eq!(
        want, cand.hash_le,
        "search kernel returned mismatched hash for nonce={}: host={} gpu={}",
        cand.nonce,
        hex::encode(want),
        hex::encode(cand.hash_le)
    );

    // Also: the nonce field of the candidate must round-trip the
    // patched bytes 76..80 of the header.
    assert_eq!(&h[76..80], &cand.nonce.to_le_bytes());

    // Avoid the unused-import warning when only this test runs.
    let _ = rand::thread_rng().gen::<u32>();
}
