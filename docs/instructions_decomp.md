# Insure4All Analytics Pipeline — Decomposed Instructions

This document decomposes the business brief into a concrete project structure, layer contracts, testing strategy, and explicit assumptions for the Insure4All demo pipeline.

## 1. Requirement source


| Item                                          | Path / note                                         |
| --------------------------------------------- | --------------------------------------------------- |
| Business brief                                | `[docs/instructions.md](instructions.md)`           |
| Path mentioned in `[prompt.md](../prompt.md)` | `./docs/instructions.md` — matches current location |
| Source CSVs                                   | `[data/](../data/)` — **read-only** (see constraint below) |


Authoritative brief is `[docs/instructions.md](instructions.md)` (aligned with `prompt.md`). This file is design/decomposition only; it does not itself create `docker-compose.yml`, the loader, or dbt code (see §8).

### Hard constraint: never modify `data/`

**Under no circumstances may agents or humans rewrite, rename columns in, reformat, or otherwise change files under `[data/](../data/)`.** Treat source CSVs as immutable inputs.

- Ingest / cleaning / header mapping (e.g. empty first column → `csv_row_index`) happens **only in memory** in the loader or in dbt, never by editing the CSV on disk.
- If a schema or quality issue appears in source files, document it and handle it in code/tests; do not “fix” the CSV in place.

---




## 2. Business goals (from the brief)

Ingest customer, policy, and event CSVs for Insure4All; validate data; support future additional CSV ingestion; and produce analytics-ready tables that answer:

1. **Monthly sales** per brand per product type
2. **Claims** per region (with monthly breakout; overall via rollup)
3. **Overall retention rate** for customers (renewed vs cancelled), per brand per product type, as a monthly report
4. Ability to add `*_additional.csv` files and re-run reports

---



## 3. Target project structure

```text
ageas_project/
├── data/                          # source CSVs (read-only)
├── docs/
│   ├── instructions.md            # business brief (A1)
│   └── instructions_decomp.md     # this file
├── docker-compose.yml             # PostgreSQL (service only; no auto DDL)
├── 0_initialize/
│   └── init.sql                   # raw_* DDL — run manually before load
├── 1_load/                        # Python ingestion layer
│   ├── config.yaml                # entity name → raw table mapping
│   └── load_raw.py
├── 2_transform/                   # dbt transformations + tests
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── models/
│   │   ├── sources.yml
│   │   ├── staging/
│   │   └── marts/
│   └── tests/
├── pyproject.toml
└── uv.lock
```



### 3.1 End-to-end data flow

```mermaid
flowchart LR
  csv["data/*.csv"] --> load["Python loader"]
  load --> raw["Postgres raw_ tables"]
  raw --> stg["dbt stg_"]
  stg --> marts["dbt marts_"]
```



---



## 4. PostgreSQL + Docker Compose



### 4.1 Service

- Single Postgres service defined in `docker-compose.yml` (image e.g. `postgres:16`).
- Named volume for persistence; host port mapped (e.g. `5433:5432`).
- Credentials via environment variables (e.g. `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`).
- **`0_initialize/init.sql` is not mounted into `docker-entrypoint-initdb.d`.** After the container is up, create raw tables manually (e.g. `docker exec -i … psql … < 0_initialize/init.sql`) **before** running the Python loader. Re-run after wiping the volume (`docker compose down -v`).




### 4.2 Physical raw tables

DDL lives in `[0_initialize/init.sql](../0_initialize/init.sql)`. Three tables only. Additional CSV files land in the same tables; they do **not** create new tables.




| Table          | Source files (default)                    |
| -------------- | ----------------------------------------- |
| `raw_customer` | `customer.csv`, `customer_additional.csv` |
| `raw_policy`   | `policy.csv`, `policy_additional.csv`     |
| `raw_event`    | `event.csv`, `event_additional.csv`       |




### 4.3 Column contract (all raw tables)

- Every CSV column is stored as `text` (including amounts, ages, timestamps).
- Plus two metadata columns:
  - `loaded_at` — `timestamp` (load time, same for all rows in one load batch per file)
  - `source_file` — `text` (basename, e.g. `customer_additional.csv`)
- The unnamed first CSV column (pandas-style row index; original header is empty, e.g. `,customer_id,...`) is mapped **in the loader only** to `csv_row_index` (`text`) for lineage/debug, dropped in staging, and never used as a business key (`event.csv` currently has index `0` on every row). Source files under `data/` must not be rewritten to add this name.


---



## 5. Loading / ingestion layer (Python)



### 5.1 Behaviour

- **Prerequisite:** raw tables from `0_initialize/init.sql` must already exist (manual apply after Postgres is up; see §4.1).
- CLI passes CSV filenames; entity key = stem before first `_`, looked up in `1_load/config.yaml` → target raw table.

- Default mapping as in §4.2.

- All CSV fields read as **strings**.
- Header handling: keep names exact (no strip). The only rename is empty / pandas `Unnamed:*` on the **first** column → `csv_row_index` (in memory). Other mismatches (including whitespace in names) are schema-shift errors.
- Sets `loaded_at` and `source_file` on insert.

- **Load mode by** `source_file` **name (A4):**
  - **Different** basenames targeting the same entity table (e.g. `customer.csv` + `customer_additional.csv` → `raw_customer`): **append** each file’s rows (do not delete the other file’s data).
  - **Same** basename loaded again (re-ingest / correction of one file): **delete-then-insert** only rows with that `source_file`, so re-runs stay idempotent without wiping sibling files.
- **Schema shift:** if a CSV’s columns differ from the existing raw table (new/missing/renamed fields), the loader must **fail loudly and surface a schema-shift error** (do not silently ignore extra columns or invent defaults). Resolving it is an explicit migration: alter `raw_`*, update dbt sources/stg, then reload.
- Same-entity additional files: add a config row only; no new raw table. New *entity* types: extend config **and** create matching `raw_`* + dbt source/stg.



### 5.2 Observed source volumes (current data)


| File                      | Rows  | Notes                                                |
| ------------------------- | ----- | ---------------------------------------------------- |
| `customer.csv`            | 3880  | Unique `customer_id`                                 |
| `customer_additional.csv` | 32    | 5 IDs overlap main; attributes identical             |
| `policy.csv`              | 4985  | Unique `policy_id`                                   |
| `policy_additional.csv`   | 44    | No overlap with main                                 |
| `event.csv`               | 11999 | Unique on `(policy_id, event_timestamp, event_type)` |
| `event_additional.csv`    | 71    | No overlap with main                                 |


---



## 6. dbt layers



### 6.1 `raw_` (source layer)

- Declared as **dbt sources** (e.g. `sources.yml`), pointing at the Postgres tables populated by the loader.
- **No** duplicate `raw_`* models that re-copy the same data, unless a thin pass-through is required for tooling; the contract is “source = physical raw tables”.



### 6.2 `stg_` (staging / clean)

One model per raw table:


| Model          | Grain / PK                                 | Role                                         |
| -------------- | ------------------------------------------ | -------------------------------------------- |
| `stg_customer` | `customer_id`                              | Dedup + cast + clean age/region              |
| `stg_policy`   | `policy_id`                                | Parse `policy_type`, cast amounts, clean IDs |
| `stg_event`    | `event_sk` / `(policy_id, event_timestamp)` | Dedup + cast timestamp, normalize event_type |




#### 6.2.1 `stg_customer`


| Rule     | Detail                                                                                                                                                 |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Dedup    | Prefer latest `loaded_at`; if tie, prefer `customer_additional.csv` over `customer.csv` (explicit merge order). Overlap today: 5 IDs, same attributes. |
| `age`    | Cast to `integer`. Empty age → `null`. Negative age → `null`. Keep ages in 0–120 (including under-18).                                                 |
| `region` | Trim; keep as string. Observed values: East, West, North, South, London (London only in additional).                                                   |
| Drop     | `csv_row_index`                                                                                                                                        |


**Observed DQ (inputs):** empty age ≈ 38; negative age ≈ 55; under-18 with non-negative age ≈ 90.

#### 6.2.2 `stg_policy`


| Rule              | Detail                                                                                                                                   |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Dedup             | By `policy_id`; keep latest `loaded_at` on conflict (none today across files).                                                           |
| `policy_type`     | Parse Python-literal-like dict string → `brand`, `product_type`. `trim(product_type)` so `'auto '` → `'auto'`.                           |
| Null product type | ~252 rows with `type: None` → `product_type` stays **null** in stg; marts coalesce to `'unknown'` so sales are not dropped.              |
| `coverage_amount` | Cast to `numeric`. Sentinel `-2147483649` (~49 rows) → `null`.                                                                           |
| `premium_amount`  | Cast to `numeric`. Empty (~104 rows) → `null`.                                                                                           |
| `policy_id`       | Keep as-is (including ~97 IDs without `POL-` prefix).                                                                                    |
| Drop              | `csv_row_index`, raw JSON-like `policy_type` string (or keep as `_raw_policy_type` if useful for audit — default: drop from stg output). |
| Brand / type      | Come only from parsed `policy_type`, not from events.                                                                                    |




#### 6.2.3 `stg_event`


| Rule                  | Detail                                                                                                                                                                                                  |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dedup                 | By `(policy_id, event_timestamp)`; keep latest `loaded_at` on conflict. Same policy may still have multiple rows of the same `event_type` at **different** times — retain those.                          |
| Surrogate key         | `event_sk` = `dbt_utils.generate_surrogate_key(['policy_id', 'event_timestamp'])`. Unique + not_null; natural grain also tested via `unique_combination_of_columns`.                                    |
| `event_timestamp`     | Cast to `timestamp without time zone`. No timezone conversion.                                                                                                                                          |
| `event_type`          | Observed: `purchase`, `claim`, `renewal`, `cancellation`.                                                                                                                                               |
| Drop                  | `csv_row_index`                                                                                                                                                                                         |
| Timezone              | Treat CSV timestamps as naive local/business time; do not invent a timezone.                                                                                                                            |
| Referential integrity | Current data: all policies resolve to a customer; all events resolve to a policy. Staging does not drop orphans; marts that join exclude unmatched rows. Monitor with tests if future files break this. |




### 6.3 `marts_` (business products)



#### 6.3.1 `mart_monthly_sales_by_brand_type`


| Attribute  | Definition                                                                                                                                          |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Grain      | `sales_month` × `brand` × `product_type`                                                                                                            |
| Filter     | `event_type = 'purchase'` only                                                                                                                      |
| Month      | `date_trunc('month', event_timestamp)::date` (or equivalent month key)                                                                              |
| Dimensions | `brand`, `product_type` from `stg_policy` (`coalesce(product_type, 'unknown')`)                                                                     |
| Metrics    | `sale_count` = count of purchase events; `premium_amount_sum` = sum of `premium_amount` where not null (empty premium still counts in `sale_count`) |
| Definition | Sales = purchase events timed by `event_timestamp`, monetized by policy premium (no separate inception date on policy).                             |


Policies with no events (~453) and customers with no policies (~1129) do not appear in this mart.

#### 6.3.2 `mart_claims_by_region`


| Attribute | Definition                                                                 |
| --------- | -------------------------------------------------------------------------- |
| Grain     | `claim_month` × `region` (customer region via policy → customer)           |
| Filter    | `event_type = 'claim'`                                                     |
| Month     | `date_trunc('month', event_timestamp)::date`                               |
| Metric    | `claim_count` = number of claim events                                     |
| Rollup    | Overall claims-per-region = sum of monthly `claim_count` over months (A10) |


**Assumption A10 — claims grain.** Deliver **monthly** claims by region (`claim_month` × `region`), and treat overall claims-per-region as a rollup of that monthly breakout.

#### 6.3.3 `mart_monthly_retention_by_brand_type`


| Attribute     | Definition                                                                                                                                                      |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Grain         | `retention_month` × `brand` × `product_type`                                                                                                                    |
| Unit          | **Policy** (not customer): one customer with multiple policies contributes multiple times; brief says “customers” but brand×type fits policy grain better (A12) |
| Eligibility   | Policies with at least one `renewal` or `cancellation` in that calendar month                                                                                   |
| Conflict rule | If both event types occur in the same month for the same policy, take the **later** `event_timestamp`                                                           |
| Metrics       | `renewal_count`, `cancellation_count`, `retention_rate = renewal_count / (renewal_count + cancellation_count)` (A11)                                            |
| Purchase      | Prior `purchase` **not** required (many renewals exist without a purchase in the file set)                                                                      |


Dirty ages / sentinel coverages / empty premiums become **null** in stg (not imputed). Null `product_type` becomes `'unknown'` in marts so measures stay complete.

---



## 7. Testing strategy (`models.yml` / `schema.yml`)

Descriptions required for every model and column. Tests by layer:

### 7.1 `raw_` (sources)


| Focus                        | Tests                                                                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Important keys               | `not_null` on `customer_id`, `policy_id`, event `policy_id` / `event_timestamp` / `event_type`, plus `source_file`, `loaded_at` |
| Non-negative “value” columns | Soft checks on age / coverage / premium when castable; **severity severity** for known dirty rows so loads are not blocked      |




### 7.2 `stg_`


| Focus             | Tests                                                                                                                             |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| PKs               | `unique` + `not_null` on `customer_id`, `policy_id`; unique combination on event natural key                                      |
| Important columns | `not_null` on keys, `brand` (where policy parses), `event_type`, `event_timestamp`, `region` when present                         |
| Ranges            | `age` accepted range 0–120 (nulls allowed)                                                                                        |
| Domains           | `accepted_values` for `region`, `event_type`, `brand`, cleaned `product_type` (include `unknown` only at mart if coalesced there) |
| Regex             | `policy_id` matches `^(POL-)?[0-9]+$` (or equivalent) to allow both prefixed and numeric-only IDs                                 |




### 7.3 `marts_`


| Focus          | Tests                                                                                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| PKs            | `unique` + `not_null` on composite keys (month+brand+type, or month+region)                                                                                  |
| Reconciliation | Prefer **metric reconciliation** vs upstream (e.g. sum of `sale_count` equals count of purchase events in stg), not naive `equal_rowcount` after aggregation |
| Contracts      | dbt model contracts locking column names and data types on final marts                                                                                       |


---



## 8. Assumptions register (summary)

Correct design choices are folded into §§1–6 above; this table is the single checklist. Items that needed a decision or call-out are expanded below.


| ID  | Assumption                                                                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A1  | `docs/instructions.md` is the authoritative business brief (matches `prompt.md`).                                                                                                                                   |
| A2  | This decomp doc describes design only; it does not implement code by itself.                                                                                                                                        |
| A3  | Unnamed CSV index → `csv_row_index` in raw (loader in-memory mapping only); dropped in stg; never a PK. **Never edit `data/` CSVs** (see §1 hard constraint).                                                      |
| A15 | Files under `data/` are immutable source inputs; no script, agent, or manual “cleanup” may modify them.                                                                                                            |
| A16 | Raw DDL (`0_initialize/init.sql`) is applied manually before load; not via `docker-entrypoint-initdb.d`.                                                                                                          |
| A4  | Same entity, **different** `source_file` names → **append**. Same `source_file` re-loaded → **delete-then-insert** for that name only (idempotent). Schema shifts must fail loudly / be migrated explicitly (§5.1). |
| A5  | Same-entity additional files share raw tables; new entities need new raw/stg objects.                                                                                                                               |
| A6  | Brand / product type from parsed `policy_type` only.                                                                                                                                                                |
| A7  | Timestamps are timezone-naive.                                                                                                                                                                                      |
| A8  | Orphans are rare today; joins may drop them; monitor with tests.                                                                                                                                                    |
| A9  | Monthly sales = purchase events; `premium_amount_sum` skips null premiums; `sale_count` still includes those purchases.                                                                                             |
| A10 | Claims include a **monthly** breakout (`claim_month` × `region`); overall claims-per-region is a rollup of that.                                                                                                    |
| A11 | `retention_rate = renewal_count / (renewal_count + cancellation_count)` at month × brand × product_type, policy grain, latest renewal/cancellation in month when both occur.                                        |
| A12 | Brief “customer” retention is implemented as **policy-level** retention for brand×type.                                                                                                                             |
| A13 | Null / dirty ages and sentinel coverages / empty premiums become null in stg rather than imputed.                                                                                                                   |
| A14 | Null product types become `'unknown'` in marts so measures are complete.                                                                                                                                            |


