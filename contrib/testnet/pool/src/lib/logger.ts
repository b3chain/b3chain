import pino from "pino";
import { config } from "../config";

export function makeLogger(name: string) {
    return pino({
        name,
        level: config.log.level,
        base: undefined,
        timestamp: pino.stdTimeFunctions.isoTime,
    });
}

export type Logger = ReturnType<typeof makeLogger>;
