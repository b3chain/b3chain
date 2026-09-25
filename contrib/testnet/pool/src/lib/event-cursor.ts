// In-memory high-water mark so the web process only emits Socket.IO events
// for rows inserted after it started.

export function consumeNew<T extends { id: number }>(
    cursor: number,
    rows: T[]
): { cursor: number; fresh: T[] } {
    const fresh = rows.filter((r) => r.id > cursor);
    const next = fresh.reduce((max, r) => (r.id > max ? r.id : max), cursor);
    return { cursor: next, fresh };
}
