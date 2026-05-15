// Stratum V2 framing.
//
// The 6-byte SV2 frame header is:
//   u16 LE  extension_type   (bit 15 = channel_msg flag, bits 0-14 = extension number)
//   u8      msg_type
//   u24 LE  msg_length       (length of the payload, max 16 MiB - 1)
//
// For channel messages (extension_type bit 15 set), the channel_id is the
// first u32 of the payload. We expose that here as a convenience but every
// concrete message decoder also re-reads it.
//
// During the Noise handshake the frames are sent in clear. After the
// handshake completes, every frame is wrapped in a Noise transport message
// (one or more 65 535-byte ciphertext segments, each with its own 16-byte
// AEAD tag). The transport wrapping lives in noise.ts; this file only deals
// with the inner SV2 framing.

import { ReadBuf, WriteBuf } from "./types";

export const SV2_HEADER_LEN = 6;
export const SV2_MAX_PAYLOAD_LEN = 0xff_ffff; // 16 MiB - 1

export const CHANNEL_MSG_FLAG = 0x8000;

export interface Sv2FrameHeader {
    extensionType: number;
    msgType: number;
    msgLength: number;
    channelMsg: boolean;
}

export interface Sv2Frame {
    header: Sv2FrameHeader;
    payload: Uint8Array;
}

export function encodeFrame(
    extensionType: number,
    msgType: number,
    payload: Uint8Array,
    channelMsg = false
): Uint8Array {
    if (payload.length > SV2_MAX_PAYLOAD_LEN) {
        throw new Error(`SV2 payload too large: ${payload.length}`);
    }
    const ext = (extensionType & 0x7fff) | (channelMsg ? CHANNEL_MSG_FLAG : 0);
    const w = new WriteBuf();
    w.u16(ext).u8(msgType).u24(payload.length).bytesRaw(payload);
    return w.finish();
}

export function decodeHeader(buf: Uint8Array, offset = 0): Sv2FrameHeader {
    if (offset + SV2_HEADER_LEN > buf.length) {
        throw new Error(`SV2 header truncated at offset ${offset}`);
    }
    const r = new ReadBuf(buf.slice(offset, offset + SV2_HEADER_LEN));
    const ext = r.u16();
    const msgType = r.u8();
    const msgLength = r.u24();
    return {
        extensionType: ext & 0x7fff,
        msgType,
        msgLength,
        channelMsg: (ext & CHANNEL_MSG_FLAG) !== 0,
    };
}

// Reads as many complete frames as fit in `buf`, returning them and the
// number of bytes consumed. Used by the per-connection frame splitter once
// a chunk has arrived from the socket (or from the Noise transport).
export function splitFrames(buf: Uint8Array): { frames: Sv2Frame[]; consumed: number } {
    const frames: Sv2Frame[] = [];
    let off = 0;
    while (off + SV2_HEADER_LEN <= buf.length) {
        const header = decodeHeader(buf, off);
        const total = SV2_HEADER_LEN + header.msgLength;
        if (off + total > buf.length) break;
        const payload = buf.slice(off + SV2_HEADER_LEN, off + total);
        frames.push({ header, payload });
        off += total;
    }
    return { frames, consumed: off };
}

// Helper: read the leading channel_id from a channel-message payload.
export function payloadChannelId(payload: Uint8Array): number {
    if (payload.length < 4) throw new Error("channel msg payload too short");
    return new DataView(payload.buffer, payload.byteOffset, 4).getUint32(0, true);
}
