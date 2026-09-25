export type RejectReason = "duplicate" | "low-diff" | "invalid" | "other";

export type RejectColumn =
    | "rejected_duplicate"
    | "rejected_low_diff"
    | "rejected_invalid"
    | "rejected_other";

export function normalizeRejectReason(reason: string): RejectReason {
    if (reason === "duplicate" || reason === "low-diff" || reason === "invalid") return reason;
    return "other";
}

export function rejectColumn(reason: string): RejectColumn {
    switch (normalizeRejectReason(reason)) {
        case "duplicate":
            return "rejected_duplicate";
        case "low-diff":
            return "rejected_low_diff";
        case "invalid":
            return "rejected_invalid";
        default:
            return "rejected_other";
    }
}
