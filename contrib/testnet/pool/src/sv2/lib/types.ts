// Stratum V2 type system encoders / decoders.
//
// Reference: https://github.com/stratum-mining/sv2-spec/blob/main/03-Protocol-Overview.md
//
// All multi-byte integers are little-endian. Sequences and length-prefixed
// byte/string types use a length prefix whose width depends on the type
// (B0_255/STR0_255 use u8, B0_64K uses u16, B0_16M uses u24).
//
// The encoders write to a growing Buffer and the decoders track a cursor
// over a Uint8Array view. Both raise on truncated / malformed input.

export class WriteBuf {
    private chunks: Uint8Array[] = [];
    private len = 0;

    u8(v: number): this { this.push(Uint8Array.from([v & 0xff])); return this; }
    u16(v: number): this {
        const b = new Uint8Array(2);
        new DataView(b.buffer).setUint16(0, v & 0xffff, true);
        return this.push(b);
    }
    u24(v: number): this {
        const b = new Uint8Array(3);
        b[0] = v & 0xff;
        b[1] = (v >>> 8) & 0xff;
        b[2] = (v >>> 16) & 0xff;
        return this.push(b);
    }
    u32(v: number): this {
        const b = new Uint8Array(4);
        new DataView(b.buffer).setUint32(0, v >>> 0, true);
        return this.push(b);
    }
    u64(v: bigint): this {
        const b = new Uint8Array(8);
        new DataView(b.buffer).setBigUint64(0, BigInt.asUintN(64, v), true);
        return this.push(b);
    }
    bool(v: boolean): this { return this.u8(v ? 1 : 0); }
    bytesRaw(b: Uint8Array): this { return this.push(b); }
    u256(b: Uint8Array): this {
        if (b.length !== 32) throw new Error(`U256 must be 32 bytes, got ${b.length}`);
        return this.push(b);
    }
    pubkey(b: Uint8Array): this { return this.u256(b); }
    signature(b: Uint8Array): this {
        if (b.length !== 64) throw new Error(`SIGNATURE must be 64 bytes, got ${b.length}`);
        return this.push(b);
    }
    b0_255(b: Uint8Array): this {
        if (b.length > 255) throw new Error(`B0_255 length ${b.length} > 255`);
        return this.u8(b.length).push(b);
    }
    b0_64k(b: Uint8Array): this {
        if (b.length > 0xffff) throw new Error(`B0_64K length ${b.length} > 65535`);
        return this.u16(b.length).push(b);
    }
    b0_16m(b: Uint8Array): this {
        if (b.length > 0xffffff) throw new Error(`B0_16M length ${b.length} > 16777215`);
        return this.u24(b.length).push(b);
    }
    str0_255(s: string): this {
        const enc = new TextEncoder().encode(s);
        return this.b0_255(enc);
    }
    seq0_255<T>(items: T[], encOne: (w: WriteBuf, item: T) => void): this {
        if (items.length > 255) throw new Error(`SEQ0_255 length ${items.length} > 255`);
        this.u8(items.length);
        for (const it of items) encOne(this, it);
        return this;
    }
    seq0_64k<T>(items: T[], encOne: (w: WriteBuf, item: T) => void): this {
        if (items.length > 0xffff) throw new Error(`SEQ0_64K length ${items.length} > 65535`);
        this.u16(items.length);
        for (const it of items) encOne(this, it);
        return this;
    }

    private push(b: Uint8Array): this {
        this.chunks.push(b);
        this.len += b.length;
        return this;
    }

    finish(): Uint8Array {
        const out = new Uint8Array(this.len);
        let off = 0;
        for (const c of this.chunks) { out.set(c, off); off += c.length; }
        return out;
    }
}

export class ReadBuf {
    private off = 0;
    constructor(private readonly buf: Uint8Array) {}

    get pos(): number { return this.off; }
    get rem(): number { return this.buf.length - this.off; }
    eof(): boolean { return this.off >= this.buf.length; }

    private need(n: number): void {
        if (this.off + n > this.buf.length) {
            throw new Error(`SV2 read: need ${n} bytes at offset ${this.off}, have ${this.buf.length - this.off}`);
        }
    }

    u8(): number { this.need(1); return this.buf[this.off++]!; }
    u16(): number {
        this.need(2);
        const v = new DataView(this.buf.buffer, this.buf.byteOffset + this.off, 2).getUint16(0, true);
        this.off += 2;
        return v;
    }
    u24(): number {
        this.need(3);
        const a = this.buf[this.off]!, b = this.buf[this.off + 1]!, c = this.buf[this.off + 2]!;
        this.off += 3;
        return a | (b << 8) | (c << 16);
    }
    u32(): number {
        this.need(4);
        const v = new DataView(this.buf.buffer, this.buf.byteOffset + this.off, 4).getUint32(0, true);
        this.off += 4;
        return v;
    }
    u64(): bigint {
        this.need(8);
        const v = new DataView(this.buf.buffer, this.buf.byteOffset + this.off, 8).getBigUint64(0, true);
        this.off += 8;
        return v;
    }
    bool(): boolean { return this.u8() !== 0; }
    bytesRaw(n: number): Uint8Array {
        this.need(n);
        const out = this.buf.slice(this.off, this.off + n);
        this.off += n;
        return out;
    }
    u256(): Uint8Array { return this.bytesRaw(32); }
    pubkey(): Uint8Array { return this.bytesRaw(32); }
    signature(): Uint8Array { return this.bytesRaw(64); }
    b0_255(): Uint8Array { return this.bytesRaw(this.u8()); }
    b0_64k(): Uint8Array { return this.bytesRaw(this.u16()); }
    b0_16m(): Uint8Array { return this.bytesRaw(this.u24()); }
    str0_255(): string { return new TextDecoder("utf-8", { fatal: true }).decode(this.b0_255()); }
    seq0_255<T>(decOne: (r: ReadBuf) => T): T[] {
        const n = this.u8();
        const out: T[] = [];
        for (let i = 0; i < n; i++) out.push(decOne(this));
        return out;
    }
    seq0_64k<T>(decOne: (r: ReadBuf) => T): T[] {
        const n = this.u16();
        const out: T[] = [];
        for (let i = 0; i < n; i++) out.push(decOne(this));
        return out;
    }
}

export function hexToBytes(hex: string): Uint8Array {
    const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
    if (clean.length % 2 !== 0) throw new Error("odd-length hex");
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16);
    return out;
}

export function bytesToHex(b: Uint8Array): string {
    let s = "";
    for (const x of b) s += x.toString(16).padStart(2, "0");
    return s;
}
