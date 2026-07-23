CREATE TABLE IF NOT EXISTS {{RAW_TABLE}} (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    -- metadata
    source_file VARCHAR(255) NOT NULL,
    ingested_at_utc DATETIME NOT NULL,
    row_hash CHAR(64) NOT NULL,

    -- raw payload
    payload JSON NOT NULL,

    -- bookkeeping
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- ensure idempotency
    UNIQUE KEY uq_row_hash (row_hash),
    KEY idx_source_file (source_file),
    KEY idx_ingested_at (ingested_at_utc)
);
