// Stratum V2 common (extension_type = 0) messages.
//
// Reference: https://github.com/stratum-mining/sv2-spec/blob/main/04-Protocol-Security.md
//            https://github.com/stratum-mining/sv2-spec/blob/main/03-Protocol-Overview.md

import { ReadBuf, WriteBuf } from "../types";
import { encodeFrame } from "../codec";

export const COMMON_EXT = 0;

export const MSG_SETUP_CONNECTION = 0x00;
export const MSG_SETUP_CONNECTION_SUCCESS = 0x01;
export const MSG_SETUP_CONNECTION_ERROR = 0x02;
export const MSG_CHANNEL_ENDPOINT_CHANGED = 0x03;
export const MSG_RECONNECT = 0x04;

export enum SubProtocol {
    Mining = 0,
    JobDeclaration = 1,
    TemplateDistribution = 2,
}

// SetupConnection.flags (only for Mining sub-protocol)
export const MINING_REQUIRES_STANDARD_JOBS = 0x01;
export const MINING_REQUIRES_WORK_SELECTION = 0x02;
export const MINING_REQUIRES_VERSION_ROLLING = 0x04;

export interface SetupConnection {
    protocol: SubProtocol;
    minVersion: number;
    maxVersion: number;
    flags: number;
    endpointHost: string;
    endpointPort: number;
    vendor: string;
    hardwareVersion: string;
    firmware: string;
    deviceId: string;
}

export function encodeSetupConnection(m: SetupConnection): Uint8Array {
    const w = new WriteBuf();
    w.u8(m.protocol)
        .u16(m.minVersion).u16(m.maxVersion).u32(m.flags >>> 0)
        .str0_255(m.endpointHost).u16(m.endpointPort)
        .str0_255(m.vendor).str0_255(m.hardwareVersion)
        .str0_255(m.firmware).str0_255(m.deviceId);
    return encodeFrame(COMMON_EXT, MSG_SETUP_CONNECTION, w.finish());
}

export function decodeSetupConnection(payload: Uint8Array): SetupConnection {
    const r = new ReadBuf(payload);
    const protocol = r.u8() as SubProtocol;
    const minVersion = r.u16();
    const maxVersion = r.u16();
    const flags = r.u32();
    const endpointHost = r.str0_255();
    const endpointPort = r.u16();
    const vendor = r.str0_255();
    const hardwareVersion = r.str0_255();
    const firmware = r.str0_255();
    const deviceId = r.str0_255();
    return { protocol, minVersion, maxVersion, flags, endpointHost, endpointPort, vendor, hardwareVersion, firmware, deviceId };
}

export interface SetupConnectionSuccess {
    usedVersion: number;
    flags: number;
}

export function encodeSetupConnectionSuccess(m: SetupConnectionSuccess): Uint8Array {
    const w = new WriteBuf();
    w.u16(m.usedVersion).u32(m.flags >>> 0);
    return encodeFrame(COMMON_EXT, MSG_SETUP_CONNECTION_SUCCESS, w.finish());
}

export function decodeSetupConnectionSuccess(payload: Uint8Array): SetupConnectionSuccess {
    const r = new ReadBuf(payload);
    return { usedVersion: r.u16(), flags: r.u32() };
}

export interface SetupConnectionError {
    flags: number;
    errorCode: string;
}

export function encodeSetupConnectionError(m: SetupConnectionError): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.flags >>> 0).str0_255(m.errorCode);
    return encodeFrame(COMMON_EXT, MSG_SETUP_CONNECTION_ERROR, w.finish());
}

export function decodeSetupConnectionError(payload: Uint8Array): SetupConnectionError {
    const r = new ReadBuf(payload);
    return { flags: r.u32(), errorCode: r.str0_255() };
}

export interface ChannelEndpointChanged {
    channelId: number;
}

export function encodeChannelEndpointChanged(m: ChannelEndpointChanged): Uint8Array {
    const w = new WriteBuf();
    w.u32(m.channelId);
    return encodeFrame(COMMON_EXT, MSG_CHANNEL_ENDPOINT_CHANGED, w.finish(), true);
}

export interface ReconnectMsg {
    newHost: string;
    newPort: number;
}

export function encodeReconnect(m: ReconnectMsg): Uint8Array {
    const w = new WriteBuf();
    w.str0_255(m.newHost).u16(m.newPort);
    return encodeFrame(COMMON_EXT, MSG_RECONNECT, w.finish());
}
