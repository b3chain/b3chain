// B3Chain PoW hash: BLAKE3(BLAKE3(header)).
// Mirrors src/primitives/block.cpp:CBlockHeader::GetPoWHash() in b3chaind.

import { blake3 } from "@noble/hashes/blake3";

export function blake3d(data: Uint8Array): Uint8Array {
    return blake3(blake3(data));
}

export function blake3once(data: Uint8Array): Uint8Array {
    return blake3(data);
}
