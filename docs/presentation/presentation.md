# 1. Project structure

## Overview

```mermaid
flowchart LR
  csv["data/*.csv"] --> init

  subgraph pg["Postgres on Docker"]
    direction LR
    init["**0_initialize** with SQL DDL<br/>→ Initialize raw_* tables"]
    load["**1_load** with Python<br/>→ Populate raw_* tables"]
    transform["**2_transform** with dbt<br/>→ Generates stg_ / marts_*"]
    init --> load --> transform
  end
```

| Step             | Tool                             | What it does                                                                                      |
| ---------------- | -------------------------------- | ------------------------------------------------------------------------------------------------- |
| Initialize       | Docker Compose + `psql`          | Start Postgres; apply `0_initialize/init.sql` to create `raw_*` tables                            |
| Load             | Python (`uv` + pandas + psycopg) | Read CSVs as text; map entity from filename; delete-insert by `source_file`; fail on schema shift |
| Transform / test | dbt (`dbt-postgres`)             | Build `stg_` → `marts_`; run generic + singular tests                                             |

## How to run

```bash
# 1. Start Postgres
docker compose up -d

# 2. Create raw_* tables
docker exec -i insure4all-postgres \
  psql -U insure4all -d insure4all < 0_initialize/init.sql

# 3. Install deps (first time / after lock changes)
uv sync

# 4. Load CSVs (idempotent per source_file)
uv run python 1_load/load_raw.py \
  customer.csv customer_additional.csv \
  policy.csv policy_additional.csv \
  event.csv event_additional.csv

# 5. Transform + test
cd 2_transform
uv run dbt deps
DBT_PROFILES_DIR=. uv run dbt build
```

Connection: `postgresql://insure4all:insure4all@localhost:5433/insure4all`

## Idempotency on rerun

- **Load:** for each CSV basename, `DELETE … WHERE source_file = ?` then insert. Same file reloaded replaces only its rows; other files in the same `raw_`* table stay. Different basenames (e.g. `*_additional.csv`) **append**.
- **Init DDL:** `CREATE TABLE IF NOT EXISTS` — safe to re-run.
- **dbt:** models are rebuilt from SQL definitions; marts are tables/views refreshed by `dbt build`.

---

# 2. Data modeling

## 3-layer structure

| Layer     | Does                                                       | Does not                                   |
| --------- | ---------------------------------------------------------- | ------------------------------------------ |
| **raw**   | Land source files 1:1 as text + load metadata              | Cast types, dedupe, parse JSON-like fields |
| **stg**   | Dedup, type cast, parse `policy_type`, clean nulls/domains | Answer business report questions           |
| **marts** | Aggregate to report grains; expose metrics for analytics   | Hold raw lineage columns                   |

## Models by layer (upstream deps)

- **raw**
  - `raw_customer` ← CSVs `customer.csv`, `customer_additional.csv`
  - `raw_policy` ← CSVs `policy.csv`, `policy_additional.csv`
  - `raw_event` ← CSV `event.csv`, `event_additional.csv`
- **stg**
  - `stg_customer` ← `source('raw', 'raw_customer')` (dedupe by `customer_id`)
  - `stg_policy` ← `source('raw', 'raw_policy')` (dedupe by `policy_id`; parse `policy_type` JSON)
  - `stg_event` ← `source('raw', 'raw_event')` (dedupe by `policy_id` + `event_timestamp`; cast timestamp / trim `event_type`; `event_sk`)
- **marts**
  - `mart_monthly_sales_by_brand_type` ← `stg_event` **inner join** `stg_policy` on `policy_id` (filter `event_type = 'purchase'`)
  - `mart_claims_by_region` ← `stg_event` **inner join** `stg_policy` on `policy_id` **inner join** `stg_customer` on `customer_id` (filter `event_type = 'claim'`)
  - `mart_monthly_retention_by_brand_type` ← `stg_event` **inner join** `stg_policy` on `policy_id` (filter `renewal` / `cancellation`; latest event per policy-month)

## Mart tables — grain and metrics

| Mart                                   | Grain                                        | Metrics / columns                                          |
| -------------------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| `mart_monthly_sales_by_brand_type`     | `sales_month` × `brand` × `product_type`     | `sale_count`, `premium_amount_sum`                         |
| `mart_claims_by_region`                | `claim_month` × `region`                     | `claim_count` (overall claims/region = rollup over months) |
| `mart_monthly_retention_by_brand_type` | `retention_month` × `brand` × `product_type` | `renewal_count`, `cancellation_count`, `retention_rate`    |

---

# 3. Answers to specific requests

## Monthly sales per brand per type

- **How:** query `mart_monthly_sales_by_brand_type` (or `select` * filtered by month).
- **Assumptions:**
  - A “sale” = a `purchase` event that joins to a policy.
  - Sale date / month = the purchase **event** timestamp (`date_trunc('month', event_timestamp)`), not a separate invoice or policy start date.
  - Brand / product type come from the policy (not the event).
  - Null `product_type` → `'unknown'` so rows are not dropped.
  - `premium_amount_sum` skips null premiums; `sale_count` still counts those purchases.

## Claims per region

- **How:** query `mart_claims_by_region`; for overall by region, `sum(claim_count) group by region`.
- **Assumptions:**
  - A claim = `event_type = 'claim'`.
  - Region comes from the **customer** linked via policy (not from the event).
  - Orphan events/policies (failed joins) are excluded.
  - Grain is monthly; overall is a rollup.

## Monthly retention rate (renewed vs cancelled) per brand per product type

- **How:** query `mart_monthly_retention_by_brand_type`.
- **Assumptions:**
  - Brief says “customers”; implemented at **policy** grain (brand × type only exist on policies).
  - Only `renewal` / `cancellation` events; if both in the same month for a policy, **latest timestamp** wins.
  - `retention_rate = renewal_count / (renewal_count + cancellation_count)` (null if denominator is 0).
  - Null `product_type` → `'unknown'`.

## Adding `*_additional.csv` and rerunning

- **How:** place files under `data/` with names starting with the entity key; load with the same script; re-run `dbt build`.
- **Assumptions:**
  - Same entity → same `raw_*` table; loader appends by distinct `source_file`.
  - Staging dedup: prefer latest `loaded_at`; for customers, prefer `customer_additional.csv` on tie; for events, grain is `policy_id` + `event_timestamp`.

```bash
uv run python 1_load/load_raw.py \
  customer_additional.csv policy_additional.csv event_additional.csv
cd 2_transform && DBT_PROFILES_DIR=. uv run dbt build
```

---

# 4. Data tests

Severity defaults to **error**; only **WARN** is called out.

## Methodology by layer

| Layer           | What we test for                                                                                                                                                        |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **raw**         | • Load completeness (`not_null`) • Soft data-quality signals (`expression_is_true` as WARN)                                                                             |
| **stg**         | • Cleaned grain (`unique`, `not_null`) • Domain validity (`accepted_values` / `accepted_range`, `expression_is_true`) • Referential integrity (`relationships` as WARN) |
| **marts**       | • Analytics grain (`unique`, `not_null`) • Schema lock (enforced contracts)                                                                                             |
| **cross-layer** | Cross-model reconciliation with singular tests (e.g. row counts before and after join)                                                                                  |

## Details

### raw layer

| Model        | not_null                                                             | expression_is_true                 |
| ------------ | -------------------------------------------------------------------- | ---------------------------------- |
| raw_customer | • customer_id • loaded_at • source_file                              | • age (WARN)                       |
| raw_policy   | • customer_id • policy_id • loaded_at • source_file                  | • coverage (WARN) • premium (WARN) |
| raw_event    | • policy_id • event_timestamp • event_type • loaded_at • source_file |                                    |

### stg layer

| Model        | not_null                                              | unique_*                                                            | accepted_*                                                                                                                         | expression_is_true                  | relationships                                   |
| ------------ | ----------------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- | ----------------------------------------------- |
| stg_customer | • customer_id • region                                | • unique: customer_id                                               | • age (range 0–120) • region (values: East, West, North, South, London)                                                            |                                     |                                                 |
| stg_policy   | • customer_id • policy_id • brand                     | • unique: policy_id                                                 | • brand (values: InsureCorp, LifeSecure, SafeGuard, ProtectPlus) • product_type (values: life, health, auto, home; where not null) | • policy_id (`~ '^(POL-)?[0-9]+$'`) | • customer_id → stg_customer.customer_id (WARN) |
| stg_event    | • event_sk • policy_id • event_timestamp • event_type | • unique: event_sk • unique_combination: policy_id, event_timestamp | • event_type (values: purchase, claim, renewal, cancellation)                                                                      |                                     | • policy_id → stg_policy.policy_id (WARN)       |

### marts layer

| Model                                | not_null                                                                      | unique_*                                                   | contract   |
| ------------------------------------ | ----------------------------------------------------------------------------- | ---------------------------------------------------------- | ---------- |
| mart_monthly_sales_by_brand_type     | • sales_month • brand • product_type • sale_count                             |                                                            | • enforced |
| mart_claims_by_region                | • claim_month • region • claim_count                                          | • unique_combination: claim_month, region                  | • enforced |
| mart_monthly_retention_by_brand_type | • retention_month • brand • product_type • renewal_count • cancellation_count | • unique_combination: retention_month, brand, product_type | • enforced |

### singular tests

| Model                                    | reconciliation                                                             |
| ---------------------------------------- | -------------------------------------------------------------------------- |
| assert_sales_count_matches_purchases.sql | • sum(mart sale_count) = count of stg purchase events joined to stg_policy |
