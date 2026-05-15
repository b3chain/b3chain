# B3Chain Mining Documentation

## Proof-of-Work Algorithm

B3Chain uses **double BLAKE3-256** for proof-of-work:

```
PoW_hash = BLAKE3(BLAKE3(block_header))
```

where `block_header` is the standard 80-byte serialized block header:

| Field           | Size    | Encoding     |
|-----------------|---------|--------------|
| nVersion        | 4 bytes | int32, LE    |
| hashPrevBlock   | 32 bytes| uint256, LE  |
| hashMerkleRoot  | 32 bytes| uint256, LE  |
| nTime           | 4 bytes | uint32, LE   |
| nBits           | 4 bytes | uint32, LE   |
| nNonce          | 4 bytes | uint32, LE   |

**Important:** Block identity hashes (block hash, txid, merkle tree) still
use double SHA-256, same as Bitcoin. Only the PoW validation uses BLAKE3.

## BLAKE3 Test Vectors

Test vectors for verifying a BLAKE3 implementation byte-for-byte
(single hash, double hash, and full 80-byte block-header vectors) are
maintained in [`doc/stratum.md`](stratum.md#2-test-vectors), the
authoritative pool-implementer reference. Any change to this hashing
must be reflected there first.

## Mining with getblocktemplate (BIP 22/23)

### Workflow

1. Call `getblocktemplate` with `{"rules": ["segwit"]}`
2. Build the block header from the template fields
3. Iterate nonce values, computing `BLAKE3(BLAKE3(header))`
4. When `PoW_hash <= target`, submit via `submitblock`

### Example (Python pseudocode)

```python
import blake3, struct

def double_blake3(header_bytes):
    h1 = blake3.blake3(header_bytes).digest()
    return blake3.blake3(h1).digest()

# Get template from RPC
template = rpc.call("getblocktemplate", [{"rules": ["segwit"]}])
target = target_from_nbits(int(template["bits"], 16))

# Build header
header = struct.pack('<i', template["version"])
header += bytes.fromhex(template["previousblockhash"])[::-1]  # LE
header += merkle_root  # computed from coinbase + txns
header += struct.pack('<III', template["curtime"],
                      int(template["bits"], 16), 0)

# Mine
for nonce in range(0xFFFFFFFF):
    header = header[:76] + struct.pack('<I', nonce)
    pow_hash = double_blake3(header)
    if int.from_bytes(pow_hash, 'little') <= target:
        submit_block(header, transactions)
        break
```

### Reference Miner

A complete reference CPU miner is provided at:

```
contrib/miner/b3chain-cpuminer.py
```

Usage:
```bash
# Install dependency
pip3 install blake3

# Mine on regtest
python3 contrib/miner/b3chain-cpuminer.py --regtest \
    --coinbaseaddr b3rt1q...your_address...

# Benchmark hash rate
python3 contrib/miner/b3chain-cpuminer.py --benchmark
```

## Stratum Protocol Notes

Stratum / pool implementer guidance has moved to its own document:
[`doc/stratum.md`](stratum.md). It covers share validation, block
submission, extranonce handling, default ports, and the BLAKE3
specification reference.

## Performance Considerations

BLAKE3 is significantly faster than SHA256d on modern hardware:

- **CPU:** BLAKE3 is ~5-10x faster than SHA256d per core (due to SIMD)
- **GPU:** BLAKE3 GPU mining kernels are straightforward to implement
- **ASIC:** No BLAKE3 ASICs exist as of 2026; this provides a period of
  CPU/GPU-accessible mining

The b3chain difficulty adjustment algorithm accounts for BLAKE3's speed
by setting appropriate initial difficulty targets.

## Difficulty Adjustment

B3Chain uses Bitcoin's standard difficulty retarget algorithm:

- **Retarget interval:** Every 2016 blocks
- **Target block time:** 600 seconds (10 minutes)
- **Max adjustment:** 4x up or down per period

### Early Difficulty Guard

For the first 10,000 blocks, an additional guard prevents chain stalls:
if a block takes longer than 20 minutes (2x target), difficulty decreases
by 25%. This ensures the chain remains usable during the bootstrap period
when hashrate may be volatile.

After block 10,000, standard Bitcoin difficulty adjustment applies exclusively.
