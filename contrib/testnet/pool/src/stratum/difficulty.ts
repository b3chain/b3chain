// Per-connection variable difficulty (vardiff).
//
// Goal: keep the average inter-share interval near `targetSeconds`. Every
// `retuneSeconds` we sample (sharesInWindow / windowSeconds) and adjust the
// difficulty multiplicatively, clamped to [min, max] and to a 4x change per
// step so a single hash spike doesn't blow up the diff.

export interface VardiffParams {
    targetSeconds: number;   // e.g. 10
    retuneSeconds: number;   // e.g. 30
    minDiff: number;         // e.g. 64
    maxDiff: number;         // e.g. 16_000_000
    initialDiff: number;
    maxStep: number;         // e.g. 4 (no more than 4x per retune)
}

export class Vardiff {
    private currentDiff: number;
    private windowStart: number;
    private sharesInWindow = 0;

    constructor(public readonly params: VardiffParams, startTime?: number) {
        this.currentDiff = params.initialDiff;
        // Allow tests (and any callers using a virtual clock) to anchor
        // the window to an explicit start time.  Defaults to wall clock.
        this.windowStart = startTime ?? Date.now();
    }

    get diff(): number {
        return this.currentDiff;
    }

    onShareAccepted(): void {
        this.sharesInWindow++;
    }

    /** Returns a new diff if it should be pushed to the client, otherwise null. */
    maybeRetune(now = Date.now()): number | null {
        const elapsed = (now - this.windowStart) / 1000;
        if (elapsed < this.params.retuneSeconds) return null;

        // No share in this window is not evidence that shares are too frequent.
        // A 600s target over a 30s empty window must not multiply difficulty.
        if (this.sharesInWindow === 0) {
            this.windowStart = now;
            if (elapsed < this.params.targetSeconds) return null;
        }
        const observedInterval = this.sharesInWindow > 0 ? elapsed / this.sharesInWindow : elapsed;
        // ratio > 1 means we want a HIGHER diff (shares too frequent).
        const ratio = this.params.targetSeconds > 0
            ? observedInterval > 0 ? this.params.targetSeconds / observedInterval : 1
            : 1;
        let multiplier = ratio;
        // clamp single-step magnitude
        if (multiplier > this.params.maxStep) multiplier = this.params.maxStep;
        if (multiplier < 1 / this.params.maxStep) multiplier = 1 / this.params.maxStep;

        let next = this.currentDiff * multiplier;
        if (next < this.params.minDiff) next = this.params.minDiff;
        if (next > this.params.maxDiff) next = this.params.maxDiff;

        this.windowStart = now;
        this.sharesInWindow = 0;

        // Don't bother retuning unless the change is meaningful (>10%).
        if (Math.abs(next - this.currentDiff) / this.currentDiff < 0.1) return null;

        this.currentDiff = next;
        return next;
    }

    /** Operator or miner suggestion. Rejects non-positive and out-of-range values. */
    setDiff(next: number): number {
        if (!Number.isFinite(next) || next <= 0) {
            throw new Error(`difficulty must be finite and > 0, got ${next}`);
        }
        if (next < this.params.minDiff || next > this.params.maxDiff) {
            throw new Error(
                `difficulty ${next} outside [${this.params.minDiff}, ${this.params.maxDiff}]`
            );
        }
        this.currentDiff = next;
        this.windowStart = Date.now();
        this.sharesInWindow = 0;
        return next;
    }
}
