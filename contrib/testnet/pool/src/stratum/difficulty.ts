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
    private windowStart = Date.now();
    private sharesInWindow = 0;

    constructor(public readonly params: VardiffParams) {
        this.currentDiff = params.initialDiff;
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

        const observedInterval = this.sharesInWindow > 0 ? elapsed / this.sharesInWindow : elapsed;
        // ratio > 1 means we want a HIGHER diff (shares too frequent)
        const ratio = this.params.targetSeconds > 0
            ? observedInterval > 0 ? this.params.targetSeconds / observedInterval : this.params.maxStep
            : 1;
        let multiplier = 1 / ratio;
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
}
