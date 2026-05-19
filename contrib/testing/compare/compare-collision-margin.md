# Collision-margin comparison — Merkle-Damgard vs Bao tree

## TL;DR

Both SHA-256 and BLAKE3 target 128-bit collision resistance. The
**construction** they use to build a hash from their compression function
differs in important ways:

- **SHA-256**: Merkle-Damgard chained compression. Strong for unkeyed
  hashing; vulnerable to length extension when used as a naive MAC.
- **BLAKE3**: Bao tree mode. Built-in domain separation between leaves
  and internal nodes, between keyed and unkeyed modes, and between
  position-dependent chunks.

B3Chain does not use the bare BLAKE3 primitive as its PoW; the PoW
is **B3PoW-Scratch v1.1** (a memory-hard construction layered on top
of BLAKE3, see
[`SPEC.md`](../../miner/b3miner-rtl/SPEC.md)). The
collision-resistance analysis below still applies because BLAKE3 is
the inner round function of B3PoW-Scratch, but the discussion of
"length-extension" and "tree mode" is most directly relevant to other
protocol-level uses of the hash where someone might naively
concatenate `(secret || data)` without thinking.

## Merkle-Damgard, briefly

```
H(M) = compress(... compress(IV, m1) ..., mn)
```

- Pad the message; split into 512-bit blocks `m1, m2, ..., mn`.
- Apply `compress` block by block, threading the chaining value.
- Output the final chaining value as the hash.

Properties:

- **Length-extension trick**: given `H(M)` and `len(M)`, an attacker can
  compute `H(M || pad || M')` without knowing `M`, by treating `H(M)` as
  the chaining value at position `len(M) + |pad|`.
- **Multi-collision (Joux 2004)**: a single chain compromise enables
  generating `2^k` collisions on a `k`-stage cascade.
- **Single thread of evaluation**: cannot be parallelised across input
  ranges.
- **Bitcoin's mitigation**: SHA-256d (`H(H(x))`). The outer hash absorbs
  exactly 32 bytes (the inner output), so the attacker cannot extend the
  outer chaining value without inverting the inner hash — which would
  itself be a preimage attack on SHA-256.

## Bao tree, briefly

```
H(M) = root( hash_chunk(c1), hash_chunk(c2), ..., hash_chunk(cn) )
```

- Split `M` into 1 KiB chunks (last may be shorter).
- Each chunk is hashed in chunk mode (domain bit set).
- Pairs of chunks are combined in parent mode (different domain bit).
- Merkle-tree-style, until a single root.

Domain separation is built into the compression function via flag bits,
including:

- `CHUNK_START`, `CHUNK_END`, `PARENT`, `ROOT` (structural)
- `KEYED_HASH`, `DERIVE_KEY_CONTEXT`, `DERIVE_KEY_MATERIAL` (mode)

Properties:

- **No length extension**: a tree-mode hash does not expose a
  resumable chaining value.
- **Multi-target resistant**: keyed mode uses the key as an IV; an
  attacker doing batched preimage search cannot amortise across keys.
- **Parallelisable**: each chunk and each parent computation is
  independent. SIMD lanes can compute 4 / 8 / 16 chunks at once.
- **Streamable**: the tree can be computed incrementally with `O(log n)`
  state.

## Side-by-side comparison

| Property                        | SHA-256 (MD)                | BLAKE3 (Bao)               |
|---------------------------------|----------------------------|----------------------------|
| Block size                      | 64 bytes                   | 64 bytes (compression)     |
| Chunk size                      | n/a                        | 1024 bytes                 |
| Output size                     | 32 bytes                   | 32 bytes (or any XOF len)  |
| Compression fn rounds           | 64                         | 7 (BLAKE2 round, modified) |
| Length-extension by default     | yes                        | no                         |
| Multi-collision tractable       | yes (Joux)                 | no                         |
| Parallelisable                  | no                         | yes (chunk + parent)       |
| Streaming                       | yes (`update()`)           | yes (`update()`)           |
| Keyed (MAC) mode built-in       | no (use HMAC)              | yes (`keyed_hash`)         |
| KDF mode built-in               | no (use HKDF)              | yes (`derive_key`)         |
| Variable output length (XOF)    | no                         | yes                        |
| Domain-separated mode flags     | no                         | yes                        |

## Implications for B3Chain protocol design

1. **Block / tx ID hashing** — `H(H(x))` SHA-256d unchanged. The MD
   construction does not leak via length extension because the inner hash
   normalises the input.
2. **PoW hashing** — **B3PoW-Scratch v1.1**: 1 MB memory-hard
   scratchpad walked by 8 lanes of BLAKE3 with 2048 outer iterations,
   finalised by a single BLAKE3 over the lane state. See
   [`SPEC.md`](../../miner/b3miner-rtl/SPEC.md). The BLAKE3 primitive
   is used as the inner round function; the construction itself is
   parallel, memory-hard, and deliberately incompatible with the bare
   BLAKE3 / SHA-256 ASIC market.
3. **Future MAC / KDF** — when B3Chain needs a keyed primitive (e.g. for
   deterministic peer-id generation, BIP324 negotiation, Lightning HTLC
   secrets), use BLAKE3's built-in `keyed_hash` and `derive_key` rather
   than re-implementing HMAC/HKDF. This is the construction-level win.

## What this comparison is NOT

- A claim that SHA-256 the algorithm is broken. It is not.
- A claim that BLAKE3 collisions are easier to find. They are not (in
  fact the published cryptanalysis margin is comparable; see
  [`compare-attack-surface.md`](compare-attack-surface.md)).
- A claim that "tree hashes are always better". They are better for the
  use cases above; for fixed-size single-block authentication tokens with
  no parallelism opportunity, the MD design is perfectly adequate.

## Sources

- Original Merkle-Damgard analysis: Damgard 1989, Merkle 1989.
- Joux 2004 multi-collisions:
  www.iacr.org/archive/crypto2004/31520306/multicollisions.pdf
- BLAKE3 specification:
  github.com/BLAKE3-team/BLAKE3-specs/blob/master/blake3.pdf
- Bao tree mode:
  github.com/oconnor663/bao
- Bitcoin SHA-256d rationale (mailing-list archive 2010):
  satoshi.nakamotoinstitute.org/emails/cryptography/threads/
