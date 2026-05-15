-- Stratum V2 session / channel / declared-job bookkeeping.
--
-- SV2 shares are written to the existing `shares` table by the same
-- IPC pipeline V1 uses; this file records SV2-specific *protocol* state
-- (who connected, which channel they opened, which JD job they declared)
-- so we can attribute ops events and audit JD usage. None of these
-- tables are on the share-write hot path.

CREATE TABLE IF NOT EXISTS sv2_sessions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    user_identity   TEXT NOT NULL,
    role            TEXT NOT NULL,                    -- 'mining' | 'jd' | 'tp' | 'translator'
    peer_addr       TEXT NOT NULL,
    static_pub      BYTEA,                            -- 32 bytes if known (JD client)
    sv2_version     INTEGER NOT NULL DEFAULT 2,
    flags           BIGINT NOT NULL DEFAULT 0,
    vendor          TEXT,
    firmware        TEXT,
    device_id       TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sv2_sessions_user_idx
    ON sv2_sessions (user_id);
CREATE INDEX IF NOT EXISTS sv2_sessions_started_idx
    ON sv2_sessions (started_at DESC);

CREATE TABLE IF NOT EXISTS sv2_channels (
    id                 BIGSERIAL PRIMARY KEY,
    session_id         BIGINT NOT NULL REFERENCES sv2_sessions(id) ON DELETE CASCADE,
    channel_id         BIGINT NOT NULL,                -- pool-side u32
    kind               TEXT NOT NULL,                  -- 'standard' | 'extended' | 'group'
    extranonce_prefix  BYTEA NOT NULL,
    extranonce_size    INTEGER NOT NULL,
    nominal_hash_rate  DOUBLE PRECISION NOT NULL DEFAULT 0,
    user_identity      TEXT NOT NULL,
    opened_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sv2_channels_session_idx
    ON sv2_channels (session_id);

-- Job-Declaration bookkeeping. Each row is a single mining_job_token
-- handed out to a JD client. consumed_at flips when the matching
-- DeclareMiningJob arrives.
CREATE TABLE IF NOT EXISTS sv2_declared_jobs (
    id                       BIGSERIAL PRIMARY KEY,
    session_id               BIGINT REFERENCES sv2_sessions(id) ON DELETE SET NULL,
    user_identifier          TEXT NOT NULL,
    mining_job_token         BYTEA NOT NULL UNIQUE,
    coinbase_max_extra_size  INTEGER NOT NULL,
    issued_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at               TIMESTAMPTZ NOT NULL,
    consumed_at              TIMESTAMPTZ,
    -- Recorded at DeclareMiningJob time:
    declared_version         BIGINT,
    declared_coinbase_prefix BYTEA,
    declared_coinbase_suffix BYTEA,
    declared_tx_count        INTEGER,
    rejected_reason          TEXT
);

CREATE INDEX IF NOT EXISTS sv2_declared_jobs_active_idx
    ON sv2_declared_jobs (consumed_at NULLS FIRST, expires_at);
