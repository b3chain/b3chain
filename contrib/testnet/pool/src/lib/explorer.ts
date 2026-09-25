const EXPLORER_ORIGIN = "https://explorer.b3chain.org";

export function explorerBlockUrl(hash: string): string {
    return `${EXPLORER_ORIGIN}/block/${encodeURIComponent(hash)}`;
}

export function explorerTxUrl(txid: string): string {
    return `${EXPLORER_ORIGIN}/tx/${encodeURIComponent(txid)}`;
}
