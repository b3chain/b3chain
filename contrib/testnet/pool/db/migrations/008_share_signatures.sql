-- Every checked share submit. share_id is set only when the row was credited.

CREATE TABLE IF NOT EXISTS share_signatures (
    id            BIGSERIAL PRIMARY KEY,
    share_id      BIGINT REFERENCES shares(id) ON DELETE SET NULL,
    user_id       BIGINT,
    worker_id     BIGINT,
    job_id        TEXT NOT NULL,
    nonce         TEXT NOT NULL,
    pubkey        TEXT,
    signature     TEXT,
    result        TEXT NOT NULL CHECK (result IN ('valid', 'invalid', 'missing')),
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS share_signatures_user_time_idx
    ON share_signatures (user_id, submitted_at DESC);
