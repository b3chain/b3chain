// B3PoW-Scratch v1.1 -- TypeScript port of the canonical Python reference
// at contrib/miner/b3miner-rtl/ref/b3pow_ref.py. The two implementations
// MUST produce byte-identical 32-byte PoW hashes for every input
// (header, prev_block_hash); CI parity is enforced by
// `tests/b3pow-scratch.test.ts` against the consensus vectors at
// `src/test/data/b3pow_consensus_vectors.json`.
//
// Normative spec: contrib/miner/b3miner-rtl/SPEC.md
//
// Pool design notes:
//
//   * `b3powScratch()` MUTATES its `pad` argument as part of the RMW
//     loop. The pool validator MUST pass a fresh copy per call. The
//     pristine "just-initialised" pad is what's amortisable across
//     siblings of the same parent; see `pad-cache.ts`.
//
//   * Pure-TypeScript performance is in the low double-digits H/s
//     range. That's fine for the pool because (a) we only validate
//     submitted shares, not mine them, and (b) clients pre-filter
//     against their local share-target before submitting, so the pool
//     only sees ~1-10 shares/sec/worker at the share difficulty.
//
//   * BLAKE3 primitive is supplied by @noble/hashes/blake3 (already a
//     pool dep). The reduced-round mixer is implemented inline because
//     no off-the-shelf library exposes BLAKE3's internal G-function
//     with a configurable round count.

import { blake3 } from "@noble/hashes/blake3";

// ----------------------------------------------------------------------------
// Locked constants (mirror of ref/b3pow_ref.py and rtl/params_pkg.sv)
// ----------------------------------------------------------------------------
export const SPEC_VERSION = 0x00010101; // 1.1.1 (F-1: ITER_MUL[7] distinct)

export const SCRATCH_BYTES = 1_048_576; // 1 MiB
export const LANES = 8;
export const LANE_BYTES = SCRATCH_BYTES / LANES; // 131072
export const BLOCK_BYTES = 64;
export const LANE_BLOCKS = LANE_BYTES / BLOCK_BYTES; // 2048
export const ITERATIONS = 2048;
export const INNER_ROUNDS = 2;
export const BLAKE3_ROUNDS = 7;
export const SCRATCH_BLOCKS = SCRATCH_BYTES / BLOCK_BYTES; // 16384

// BLAKE3 IV (first 8 of SHA-256 IV)
const BLAKE3_IV: readonly number[] = Object.freeze([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

const BLAKE3_PERM: readonly number[] = Object.freeze([
    2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8,
]);

// wyhash secret table (SPEC.md §3). All entries are odd, well-distributed,
// pairwise distinct. v1.1.1 fixed F-1 by giving lane 7 a distinct constant.
const ITER_MUL: readonly bigint[] = Object.freeze([
    0xA0761D6478BD642Fn,
    0xE7037ED1A0B428DBn,
    0x8EBC6AF09C88C6E3n,
    0x589965CC75374CC3n,
    0x1D8E4E27C47D124Fn,
    0xEB44ACCAB455D165n,
    0xC863B19A77C75D70n,
    0x6E5C6F88AA5BDA77n,
]);

// Lane shuffle: L' = (5*L + 1) mod 8 (SPEC §6.5).
const LANE_SHUFFLE: readonly number[] = Object.freeze([1, 6, 3, 0, 5, 2, 7, 4]);

const MASK32 = 0xffffffff;
const MASK64 = 0xffffffffffffffffn;

// ----------------------------------------------------------------------------
// Low-level helpers
// ----------------------------------------------------------------------------
function rotr32(x: number, n: number): number {
    const v = x >>> 0;
    return ((v >>> n) | (v << (32 - n))) >>> 0;
}

function rotr64(x: bigint, n: number): bigint {
    const nb = BigInt(n);
    return (((x >> nb) | (x << (64n - nb))) & MASK64);
}

function add32(a: number, b: number, c: number = 0): number {
    return (((a + b) >>> 0) + c) >>> 0;
}

function readLEWord(buf: Uint8Array, off: number): number {
    return (
        (buf[off] |
            (buf[off + 1] << 8) |
            (buf[off + 2] << 16) |
            (buf[off + 3] << 24)) >>>
        0
    );
}

function readLEUint64(buf: Uint8Array, off: number): bigint {
    const lo = BigInt(readLEWord(buf, off));
    const hi = BigInt(readLEWord(buf, off + 4));
    return lo | (hi << 32n);
}

function writeLEWords(words: number[]): Uint8Array {
    const out = new Uint8Array(words.length * 4);
    for (let i = 0; i < words.length; i++) {
        const w = words[i] >>> 0;
        out[i * 4] = w & 0xff;
        out[i * 4 + 1] = (w >>> 8) & 0xff;
        out[i * 4 + 2] = (w >>> 16) & 0xff;
        out[i * 4 + 3] = (w >>> 24) & 0xff;
    }
    return out;
}

function leWords(buf: Uint8Array): number[] {
    if (buf.length % 4 !== 0) {
        throw new Error("buffer length must be a multiple of 4");
    }
    const out = new Array<number>(buf.length / 4);
    for (let i = 0; i < out.length; i++) {
        out[i] = readLEWord(buf, i * 4);
    }
    return out;
}

// ----------------------------------------------------------------------------
// BLAKE3 G function and round (matches reference)
// ----------------------------------------------------------------------------
function g(
    s: number[],
    a: number, b: number, c: number, d: number,
    mx: number, my: number,
): void {
    s[a] = add32(s[a], s[b], mx);
    s[d] = rotr32((s[d] ^ s[a]) >>> 0, 16);
    s[c] = add32(s[c], s[d]);
    s[b] = rotr32((s[b] ^ s[c]) >>> 0, 12);
    s[a] = add32(s[a], s[b], my);
    s[d] = rotr32((s[d] ^ s[a]) >>> 0, 8);
    s[c] = add32(s[c], s[d]);
    s[b] = rotr32((s[b] ^ s[c]) >>> 0, 7);
}

function roundFn(state: number[], m: number[]): void {
    // columns
    g(state, 0, 4, 8, 12, m[0], m[1]);
    g(state, 1, 5, 9, 13, m[2], m[3]);
    g(state, 2, 6, 10, 14, m[4], m[5]);
    g(state, 3, 7, 11, 15, m[6], m[7]);
    // diagonals
    g(state, 0, 5, 10, 15, m[8], m[9]);
    g(state, 1, 6, 11, 12, m[10], m[11]);
    g(state, 2, 7, 8, 13, m[12], m[13]);
    g(state, 3, 4, 9, 14, m[14], m[15]);
}

function permuteMsg(m: number[]): number[] {
    const out = new Array<number>(16);
    for (let i = 0; i < 16; i++) out[i] = m[BLAKE3_PERM[i]];
    return out;
}

/** Reduced-round BLAKE3 compression used by the mix step (SPEC §6.5).
 *  Runs `innerRounds` rounds (default 2) and returns
 *  `(new_cv_words, permuted_msg)`. */
function blake3ShortCompress(
    cv: number[],
    block: number[],
    innerRounds: number = INNER_ROUNDS,
): { newCv: number[]; permutedMsg: number[] } {
    const state: number[] = [
        cv[0], cv[1], cv[2], cv[3],
        cv[4], cv[5], cv[6], cv[7],
        BLAKE3_IV[0], BLAKE3_IV[1], BLAKE3_IV[2], BLAKE3_IV[3],
        0, 0, BLOCK_BYTES, 0,
    ];
    let m = block.slice();
    for (let r = 0; r < innerRounds; r++) {
        roundFn(state, m);
        m = permuteMsg(m);
    }
    const newCv = new Array<number>(8);
    for (let i = 0; i < 8; i++) newCv[i] = (state[i] ^ state[i + 8]) >>> 0;
    return { newCv, permutedMsg: m };
}

// ----------------------------------------------------------------------------
// BLAKE3 wrappers
// ----------------------------------------------------------------------------
function blake3Hash(data: Uint8Array): Uint8Array {
    return blake3(data);
}

function blake3Xof(data: Uint8Array, outLen: number): Uint8Array {
    // @noble/hashes/blake3 accepts a dkLen option for the XOF.
    return blake3(data, { dkLen: outLen });
}

// ----------------------------------------------------------------------------
// Top-level B3PoW-Scratch v1.1
// ----------------------------------------------------------------------------

export interface B3PowResult {
    powHash: Uint8Array; // 32 bytes, little-endian on the wire
    iterations: number;
}

/** Build the 1 MiB scratchpad from `prevBlockHashLE` per SPEC §6.1.
 *  The returned buffer is a fresh `Uint8Array` of length 1 048 576. */
export function initScratchpad(prevBlockHashLE: Uint8Array): Uint8Array {
    if (prevBlockHashLE.length !== 32) {
        throw new Error("prevBlockHashLE must be 32 bytes");
    }
    const pad = new Uint8Array(SCRATCH_BYTES);
    const seedBuf = new Uint8Array(32 + 4);
    seedBuf.set(prevBlockHashLE, 0);
    for (let i = 0; i < SCRATCH_BLOCKS; i++) {
        seedBuf[32] = i & 0xff;
        seedBuf[33] = (i >>> 8) & 0xff;
        seedBuf[34] = (i >>> 16) & 0xff;
        seedBuf[35] = (i >>> 24) & 0xff;
        const chunk = blake3Xof(seedBuf, BLOCK_BYTES);
        pad.set(chunk, i * BLOCK_BYTES);
    }
    return pad;
}

function initLanes(seed: Uint8Array): Uint8Array[] {
    if (seed.length !== 32) throw new Error("seed must be 32 bytes");
    const tmp = new Uint8Array(32 + 4);
    tmp.set(seed, 0);
    const out: Uint8Array[] = new Array(LANES);
    for (let L = 0; L < LANES; L++) {
        tmp[32] = L & 0xff;
        tmp[33] = (L >>> 8) & 0xff;
        tmp[34] = (L >>> 16) & 0xff;
        tmp[35] = (L >>> 24) & 0xff;
        out[L] = blake3Hash(tmp);
    }
    return out;
}

function deriveAddresses(lanes: Uint8Array[], iterIdx: number): number[] {
    const mask = LANE_BLOCKS - 1;
    const itr = BigInt(iterIdx >>> 0);
    const addrs = new Array<number>(LANES);
    for (let L = 0; L < LANES; L++) {
        const lo = readLEUint64(lanes[L], 0);
        const hi = readLEUint64(lanes[L], 8);
        const mul = ((hi ^ itr) * ITER_MUL[L]) & MASK64;
        const mixed = lo ^ rotr64(mul, 23);
        addrs[L] = Number(mixed & BigInt(mask));
    }
    return addrs;
}

function readScratchpadBlocks(pad: Uint8Array, addrs: number[]): Uint8Array[] {
    const out: Uint8Array[] = new Array(LANES);
    for (let L = 0; L < LANES; L++) {
        const base = L * LANE_BYTES + addrs[L] * BLOCK_BYTES;
        out[L] = pad.subarray(base, base + BLOCK_BYTES);
    }
    return out;
}

function writeScratchpadBlocks(
    pad: Uint8Array,
    addrs: number[],
    newBlocks: Uint8Array[],
): void {
    for (let L = 0; L < LANES; L++) {
        const base = L * LANE_BYTES + addrs[L] * BLOCK_BYTES;
        pad.set(newBlocks[L], base);
    }
}

function mixStep(
    lanes: Uint8Array[],
    blocks: Uint8Array[],
): { newLanes: Uint8Array[]; newBlocks: Uint8Array[] } {
    const newLanes = new Array<Uint8Array>(LANES);
    const newBlocks = new Array<Uint8Array>(LANES);

    for (let L = 0; L < LANES; L++) {
        const cv = leWords(lanes[L]); // 8 words
        const msg = leWords(blocks[L]); // 16 words
        const { newCv, permutedMsg } = blake3ShortCompress(cv, msg);
        newLanes[L] = writeLEWords(newCv);

        // Writeback = original block XOR serialised permuted_msg
        const permBytes = writeLEWords(permutedMsg);
        const wb = new Uint8Array(BLOCK_BYTES);
        for (let i = 0; i < BLOCK_BYTES; i++) wb[i] = blocks[L][i] ^ permBytes[i];
        newBlocks[L] = wb;
    }

    // Apply lane shuffle.
    const shuffled = new Array<Uint8Array>(LANES);
    for (let L = 0; L < LANES; L++) shuffled[L] = newLanes[LANE_SHUFFLE[L]];
    return { newLanes: shuffled, newBlocks };
}

function serialiseLanes(lanes: Uint8Array[]): Uint8Array {
    const out = new Uint8Array(LANES * 32);
    for (let L = 0; L < LANES; L++) out.set(lanes[L], L * 32);
    return out;
}

/** Top-level B3PoW-Scratch v1.1 PoW function (SPEC §5).
 *
 *  @param header           80-byte block header (little-endian on wire).
 *  @param prevBlockHashLE  32-byte SHA-256d hash of the parent block,
 *                          raw little-endian (i.e. the bytes that appear
 *                          inside `header` at offset 4..36).
 *  @param pad              Optional pre-initialised pad. **This buffer
 *                          is mutated in place** by the RMW loop; callers
 *                          that intend to reuse the pristine init across
 *                          multiple nonces must pass a fresh copy each
 *                          call (see `pad-cache.ts`).
 */
export function b3powScratch(
    header: Uint8Array,
    prevBlockHashLE: Uint8Array,
    pad?: Uint8Array,
): B3PowResult {
    if (header.length !== 80) throw new Error("header must be 80 bytes");
    if (prevBlockHashLE.length !== 32) {
        throw new Error("prevBlockHashLE must be 32 bytes");
    }

    const nonce = header.subarray(76, 80);
    const seed = blake3Hash(header);

    const padBuf = pad ?? initScratchpad(prevBlockHashLE);
    if (padBuf.length !== SCRATCH_BYTES) {
        throw new Error(
            `pad must be ${SCRATCH_BYTES} bytes, got ${padBuf.length}`,
        );
    }

    let lanes = initLanes(seed);

    for (let r = 0; r < ITERATIONS; r++) {
        const addrs = deriveAddresses(lanes, r);
        const blocks = readScratchpadBlocks(padBuf, addrs).map(
            (b) => new Uint8Array(b),
        );
        const { newLanes, newBlocks } = mixStep(lanes, blocks);
        writeScratchpadBlocks(padBuf, addrs, newBlocks);
        lanes = newLanes;
    }

    const tail = new Uint8Array(LANES * 32 + 4);
    tail.set(serialiseLanes(lanes), 0);
    tail.set(nonce, LANES * 32);
    const powHash = blake3Hash(tail);
    return { powHash, iterations: ITERATIONS };
}

/** Convenience: little-endian 256-bit integer view of a 32-byte buffer. */
export function intLE(buf: Uint8Array): bigint {
    if (buf.length !== 32) throw new Error("expected 32-byte buffer");
    let acc = 0n;
    for (let i = 31; i >= 0; i--) acc = (acc << 8n) | BigInt(buf[i]);
    return acc;
}

/** Decode Bitcoin-compact nBits to a 256-bit target integer. */
export function nbitsToTarget(nbits: number): bigint {
    const size = (nbits >>> 24) & 0xff;
    const word = BigInt(nbits & 0x007fffff);
    if (size <= 3) return word >> BigInt(8 * (3 - size));
    return word << BigInt(8 * (size - 3));
}

/** Returns true iff this header is a valid PoW. */
export function checkPow(
    header: Uint8Array,
    prevBlockHashLE: Uint8Array,
    nbits: number,
    pad?: Uint8Array,
): boolean {
    const res = b3powScratch(header, prevBlockHashLE, pad);
    return intLE(res.powHash) <= nbitsToTarget(nbits);
}
