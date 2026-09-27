-- Raw layer: all CSV business columns as text + load metadata

CREATE TABLE IF NOT EXISTS raw_customer (
    csv_row_index   text,
    customer_id     text,
    age             text,
    region          text,
    loaded_at       timestamp NOT NULL,
    source_file     text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_customer_source_file
    ON raw_customer (source_file);

CREATE TABLE IF NOT EXISTS raw_policy (
    csv_row_index     text,
    customer_id       text,
    policy_id         text,
    coverage_amount   text,
    policy_type       text,
    premium_amount    text,
    loaded_at         timestamp NOT NULL,
    source_file       text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_policy_source_file
    ON raw_policy (source_file);

CREATE TABLE IF NOT EXISTS raw_event (
    csv_row_index     text,
    policy_id         text,
    event_timestamp   text,
    event_type        text,
    loaded_at         timestamp NOT NULL,
    source_file       text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_event_source_file
    ON raw_event (source_file);
