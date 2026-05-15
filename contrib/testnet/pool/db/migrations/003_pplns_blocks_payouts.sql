-- B3Chain Pool: PPLNS ledger (blocks, balance entries, payouts)

CREATE TABLE IF NOT EXISTS blocks (
    id              BIGSERIAL PRIMARY KEY,
    height          BIGINT NOT NULL,
    hash            TEXT NOT NULL UNIQUE,
    finder_user_id  BIGINT REFERENCES users(id) ON DELETE SET NULL,
    finder_worker_id BIGINT REFERENCES workers(id) ON DELETE SET NULL,
    reward_b3c      NUMERIC(20,8) NOT NULL,
    pool_fee_b3c    NUMERIC(20,8) NOT NULL DEFAULT 0,
    confirmations   INT NOT NULL DEFAULT 0,
    is_confirmed    BOOLEAN NOT NULL DEFAULT FALSE,
    is_orphan       BOOLEAN NOT NULL DEFAULT FALSE,
    pplns_credited  BOOLEAN NOT NULL DEFAULT FALSE,
    found_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS blocks_height_idx ON blocks(height DESC);
CREATE INDEX IF NOT EXISTS blocks_unconfirmed_idx
    ON blocks(is_confirmed, is_orphan)
    WHERE NOT is_confirmed AND NOT is_orphan;

CREATE TABLE IF NOT EXISTS payouts (
    id          BIGSERIAL PRIMARY KEY,
    txid        TEXT,
    confirmed   BOOLEAN NOT NULL DEFAULT FALSE,
    total_b3c   NUMERIC(20,8) NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Append-only ledger. User balance = SUM(delta_b3c).
CREATE TABLE IF NOT EXISTS balance_entries (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    block_id    BIGINT REFERENCES blocks(id) ON DELETE SET NULL,
    payout_id   BIGINT REFERENCES payouts(id) ON DELETE SET NULL,
    delta_b3c   NUMERIC(20,8) NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('credit', 'debit', 'fee', 'adjustment')),
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS balance_entries_user_idx
    ON balance_entries(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS balance_entries_payout_idx
    ON balance_entries(payout_id);

-- Per-user payout-line resolution at the moment of payout.
CREATE TABLE IF NOT EXISTS payout_recipients (
    payout_id   BIGINT NOT NULL REFERENCES payouts(id) ON DELETE CASCADE,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    address     TEXT NOT NULL,
    amount_b3c  NUMERIC(20,8) NOT NULL,
    PRIMARY KEY (payout_id, user_id)
);
