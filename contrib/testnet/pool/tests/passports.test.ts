import { test } from "node:test";
import assert from "node:assert/strict";
import { MemoryPassportStore } from "../src/lib/passports";

test("empty slot locks on success and stays empty when lock is skipped", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    const hold = new Set<number>();
    const slot = await store.addEmpty(7);
    const reserved = await store.reserveEmpty(7, hold);
    assert.equal(reserved?.id, slot.id);
    assert.equal(await store.reserveEmpty(7, hold), null);
    assert.equal(await store.lock(slot.id, "ab".repeat(64)), true);
    hold.delete(slot.id);
    assert.equal((await store.findSlotByPubkey("ab".repeat(64)))?.userId, 7);
    const again = await store.addEmpty(7);
    const hold2 = new Set<number>();
    const reserved2 = await store.reserveEmpty(7, hold2);
    assert.equal(reserved2?.id, again.id);
    hold2.delete(again.id);
    assert.equal((await store.findSlotByPubkey("cd".repeat(64))), null);
    assert.equal((await store.reserveEmpty(7, new Set()))?.id, again.id);
});

test("a locked key is not given a second slot", async () => {
    const store = new MemoryPassportStore();
    store.addUser("miner@example.com", 7);
    const slot = await store.addEmpty(7);
    const hold = new Set<number>();
    await store.reserveEmpty(7, hold);
    await store.lock(slot.id, "11".repeat(64));
    hold.delete(slot.id);
    await store.addEmpty(7);
    const found = await store.findSlotByPubkey("11".repeat(64));
    assert.equal(found?.slotNo, 1);
    const next = await store.reserveEmpty(7, new Set());
    assert.equal(next?.slotNo, 2);
});
