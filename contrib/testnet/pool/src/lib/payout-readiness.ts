import { isValidB3AddressForNetwork } from "./address";

export type PayoutBlocker = "not_verified" | "no_address" | "invalid_address" | "below_minimum" | "eligible";

export interface PayoutReadinessInput {
    emailVerified: boolean;
    payoutAddress: string | null;
    balance: number;
    minimum: number;
    network: "mainnet" | "testnet" | "regtest";
}

export interface PayoutReadiness {
    code: PayoutBlocker;
    message: string;
}

export function payoutReadiness(input: PayoutReadinessInput): PayoutReadiness {
    if (!input.emailVerified) {
        return { code: "not_verified", message: "Verify your email before a payout can be sent." };
    }
    const addr = (input.payoutAddress ?? "").trim();
    if (!addr) {
        return { code: "no_address", message: "Set a payout address in Settings." };
    }
    if (!isValidB3AddressForNetwork(addr, input.network)) {
        return { code: "invalid_address", message: "The payout address is not valid for this network." };
    }
    if (!Number.isFinite(input.balance) || input.balance <= 0 || input.balance < input.minimum) {
        return {
            code: "below_minimum",
            message: `Balance is below the ${input.minimum.toFixed(2)} B3C minimum. The hourly job skips this account until it reaches that amount.`,
        };
    }
    return {
        code: "eligible",
        message: "Eligible on the next hourly payout run.",
    };
}
