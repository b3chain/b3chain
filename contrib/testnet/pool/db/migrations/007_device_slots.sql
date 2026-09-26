-- Account device slots. An empty row has a null pubkey.
-- A locked row is that device's passport and is not rewritten.

CREATE TABLE IF NOT EXISTS device_slots (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot_no    INT NOT NULL,
    pubkey     TEXT,
    locked_at  TIMESTAMPTZ,
    UNIQUE (user_id, slot_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS device_slots_pubkey_uidx
    ON device_slots (pubkey)
    WHERE pubkey IS NOT NULL;
