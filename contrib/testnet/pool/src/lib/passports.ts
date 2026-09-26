import { query } from "./db";

export interface PassportSlot {
    id: number;
    userId: number;
    slotNo: number;
    pubkey: string | null;
}

export interface PassportStore {
    findUserId(email: string): Promise<number | null>;
    findSlotByPubkey(pubkey: string): Promise<PassportSlot | null>;
    reserveEmpty(userId: number, hold: Set<number>): Promise<PassportSlot | null>;
    lock(id: number, pubkey: string): Promise<boolean>;
    addEmpty(userId: number): Promise<PassportSlot>;
}

export class MemoryPassportStore implements PassportStore {
    private users = new Map<string, number>();
    private slots: PassportSlot[] = [];
    private nextId = 1;

    addUser(email: string, id: number): void {
        this.users.set(email, id);
    }

    async findUserId(email: string): Promise<number | null> {
        return this.users.get(email) ?? null;
    }

    async findSlotByPubkey(pubkey: string): Promise<PassportSlot | null> {
        return this.slots.find((s) => s.pubkey === pubkey) ?? null;
    }

    async reserveEmpty(userId: number, hold: Set<number>): Promise<PassportSlot | null> {
        const slot = this.slots
            .filter((s) => s.userId === userId && s.pubkey === null && !hold.has(s.id))
            .sort((a, b) => a.slotNo - b.slotNo)[0];
        if (!slot) return null;
        hold.add(slot.id);
        return slot;
    }

    async lock(id: number, pubkey: string): Promise<boolean> {
        const slot = this.slots.find((s) => s.id === id);
        if (!slot || slot.pubkey !== null) return false;
        if (this.slots.some((s) => s.pubkey === pubkey)) return false;
        slot.pubkey = pubkey;
        return true;
    }

    async addEmpty(userId: number): Promise<PassportSlot> {
        const slotNo = this.slots.filter((s) => s.userId === userId).reduce((m, s) => Math.max(m, s.slotNo), 0) + 1;
        const slot: PassportSlot = { id: this.nextId++, userId, slotNo, pubkey: null };
        this.slots.push(slot);
        return slot;
    }
}

export class PgPassportStore implements PassportStore {
    async findUserId(email: string): Promise<number | null> {
        const rows = await query<{ id: string }>("SELECT id::text AS id FROM users WHERE email = $1 LIMIT 1", [email]);
        return rows.length ? parseInt(rows[0]!.id, 10) : null;
    }

    async findSlotByPubkey(pubkey: string): Promise<PassportSlot | null> {
        const rows = await query<{ id: string; user_id: string; slot_no: number; pubkey: string }>(
            `SELECT id::text AS id, user_id::text AS user_id, slot_no, pubkey
               FROM device_slots WHERE pubkey = $1 LIMIT 1`,
            [pubkey]
        );
        if (!rows.length) return null;
        const r = rows[0]!;
        return { id: parseInt(r.id, 10), userId: parseInt(r.user_id, 10), slotNo: r.slot_no, pubkey: r.pubkey };
    }

    async reserveEmpty(userId: number, hold: Set<number>): Promise<PassportSlot | null> {
        const rows = await query<{ id: string; user_id: string; slot_no: number }>(
            `SELECT id::text AS id, user_id::text AS user_id, slot_no
               FROM device_slots
              WHERE user_id = $1 AND pubkey IS NULL
              ORDER BY slot_no ASC`,
            [userId]
        );
        const row = rows.find((r) => !hold.has(parseInt(r.id, 10)));
        if (!row) return null;
        const slot = { id: parseInt(row.id, 10), userId: parseInt(row.user_id, 10), slotNo: row.slot_no, pubkey: null };
        hold.add(slot.id);
        return slot;
    }

    async lock(id: number, pubkey: string): Promise<boolean> {
        const rows = await query<{ id: string }>(
            `UPDATE device_slots
                SET pubkey = $2, locked_at = NOW()
              WHERE id = $1 AND pubkey IS NULL
              RETURNING id::text AS id`,
            [id, pubkey]
        );
        return rows.length > 0;
    }

    async addEmpty(userId: number): Promise<PassportSlot> {
        const rows = await query<{ id: string; user_id: string; slot_no: number }>(
            `INSERT INTO device_slots(user_id, slot_no)
             VALUES ($1, COALESCE((SELECT MAX(slot_no) FROM device_slots WHERE user_id = $1), 0) + 1)
             RETURNING id::text AS id, user_id::text AS user_id, slot_no`,
            [userId]
        );
        const r = rows[0]!;
        return { id: parseInt(r.id, 10), userId: parseInt(r.user_id, 10), slotNo: r.slot_no, pubkey: null };
    }
}

export type AdminSlotRow = {
    userId: string;
    email: string;
    slotNo: number | null;
    pubkey: string | null;
    lockedAt: string | null;
}

export async function listAccountSlots(): Promise<AdminSlotRow[]> {
    return query<AdminSlotRow>(
        `SELECT u.id::text AS "userId", u.email,
                s.slot_no AS "slotNo", s.pubkey,
                s.locked_at::text AS "lockedAt"
           FROM users u
           LEFT JOIN device_slots s ON s.user_id = u.id
          ORDER BY u.id ASC, s.slot_no ASC NULLS LAST
          LIMIT 500`
    );
}
