import { createHash } from "crypto";

/** SHA-256 of jobId|extranonce2|ntime|nonce. ntime and nonce are 8 lowercase hex chars. */
export function shareDigest(jobId: string, extranonce2Hex: string, ntime: number, nonce: number): Buffer {
    const ntimeHex = (ntime >>> 0).toString(16).padStart(8, "0");
    const nonceHex = (nonce >>> 0).toString(16).padStart(8, "0");
    const canon = `${jobId}|${extranonce2Hex.toLowerCase()}|${ntimeHex}|${nonceHex}`;
    return createHash("sha256").update(canon).digest();
}

export function nonceHex(nonce: number): string {
    return (nonce >>> 0).toString(16).padStart(8, "0");
}
