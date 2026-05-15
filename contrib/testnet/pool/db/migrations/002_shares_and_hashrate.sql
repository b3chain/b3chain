-- B3Chain Pool: shares + 1-minute hashrate buckets

CREATE TABLE IF NOT EXISTS shares (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    worker_id     BIGINT NOT NULL,
    diff          DOUBLE PRECISION NOT NULL,
    is_block      BOOLEAN NOT NULL DEFAULT FALSE,
    block_hash    TEXT,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS shares_user_time_idx
    ON shares(user_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS shares_time_idx
    ON shares(submitted_at DESC);
CREATE INDEX IF NOT EXISTS shares_worker_time_idx
    ON shares(worker_id, submitted_at DESC);

-- 1-minute rolled-up per-user hashrate (for the dashboard graph).
CREATE TABLE IF NOT EXISTS hashrate_buckets (
    user_id        BIGINT NOT NULL,
    bucket_at      TIMESTAMPTZ NOT NULL,
    hashrate_hps   DOUBLE PRECISION NOT NULL,
    shares_count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, bucket_at)
);
CREATE INDEX IF NOT EXISTS hashrate_buckets_time_idx
    ON hashrate_buckets(bucket_at DESC);

CREATE TABLE IF NOT EXISTS pool_hashrate_buckets (
    bucket_at      TIMESTAMPTZ PRIMARY KEY,
    hashrate_hps   DOUBLE PRECISION NOT NULL,
    shares_count   INT NOT NULL DEFAULT 0,
    miners_online  INT NOT NULL DEFAULT 0
);
