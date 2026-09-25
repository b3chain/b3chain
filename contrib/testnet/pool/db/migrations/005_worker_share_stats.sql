-- Per-worker difficulty and reject counters. Counters, not one row per reject.

ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_difficulty DOUBLE PRECISION;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS rejected_duplicate BIGINT NOT NULL DEFAULT 0;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS rejected_low_diff BIGINT NOT NULL DEFAULT 0;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS rejected_invalid BIGINT NOT NULL DEFAULT 0;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS rejected_other BIGINT NOT NULL DEFAULT 0;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_reject_reason TEXT;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS last_reject_at TIMESTAMPTZ;
