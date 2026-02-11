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

These vectors can be used to verify your BLAKE3 implementation is correct.

### Single BLAKE3

```
BLAKE3("") = af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262
BLAKE3("b3chain") = 492530272073ef2fb434ca4d9492bcea09502b24642b7e04021892bdda2aa806
```

### Double BLAKE3

```
BLAKE3(BLAKE3("")) = 82878ed8a480ee41775636820e05a934ca5c747223ca64306658ee5982e6c227
BLAKE3(BLAKE3("b3chain")) = f09be63a21ff0bc5646b5ddcadef1c43f8e0e47815793cff909cab0a345396d3
```

### Block Header Vectors

**80 zero bytes:**
```
Header:    00000000...00000000 (80 bytes of 0x00)
PoW hash:  fb6d63b21d8c9f215de0e4fd9f4d0e7ed53ff023c7243e76f5a7367b2a4507b6
ID hash:   14508459b221041eab257d2baaa7459775ba748246c8403609eb708f0e57e74b
```

**Version=1, rest zeros:**
```
Header:    01000000 00...00 (version=1, 76 zero bytes)
PoW hash:  a8b60a455b3576a701ed73ad8ebf838839917a0331bfb6dfa99b77641c858c61
ID hash:   4ddd9f0855d58a375be5a763e5f51ece853d30525fcd9a3e477c2194fedb549f
```

Note: "PoW hash" and "ID hash" are shown in big-endian display format
(most significant byte first), which is how block hashes are displayed.
The actual byte order in memory is little-endian.

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

For mining pool implementers, the following differences from Bitcoin apply:

1. **Hash algorithm:** Replace SHA256d with double BLAKE3-256 for PoW
   validation. All other hashes (merkle root, txid, etc.) remain SHA256d.

2. **Work validation:** The pool validates shares by checking:
   ```
   BLAKE3(BLAKE3(header)) <= share_target
   ```

3. **Block submission:** Submitted blocks are validated by the node using
   `BLAKE3(BLAKE3(header)) <= block_target` in `CheckProofOfWork()`.

4. **Extranonce:** Standard extranonce handling in the coinbase transaction
   works identically to Bitcoin. Only the final PoW hash computation differs.

5. **Target encoding:** nBits compact encoding is identical to Bitcoin.

6. **Default ports:**

   | Network | P2P Port | RPC Port |
   |---------|----------|----------|
   | Mainnet | 8533     | 8534     |
   | Testnet | 18533    | 18534    |
   | Regtest | 18544    | 18545    |

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
