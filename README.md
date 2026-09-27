# Insure4All analytics pipeline

CSV → Postgres `raw_` tables → dbt `stg_` / `marts_` models for Insure4All demo analytics.

Design notes: [docs/instructions_decomp.md](docs/instructions_decomp.md).

## Prerequisites

- Docker / Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.10+ (uv can install it if needed)
- Network access to pull `postgres:16` and PyPI packages

## Quick start

```bash
# 1. Start Postgres
docker compose up -d

# 2. Create raw_* tables (manual; not auto-run on container start)
docker exec -i insure4all-postgres \
  psql -U insure4all -d insure4all < 0_initialize/init.sql

# 3. Install Python deps (loader + dbt) into .venv
uv sync

# 4. Load CSVs into raw_ tables (idempotent per source_file)
#    Entity = filename stem before first "_"; mapped via 1_load/config.yaml
uv run python 1_load/load_raw.py \
  customer.csv \
  policy.csv \
  event.csv

# 5. Transform + test
cd 2_transform
uv run dbt deps
DBT_PROFILES_DIR=. uv run dbt build
```

`0_initialize/init.sql` uses `CREATE TABLE IF NOT EXISTS`, so re-running step 2 is safe. After `docker compose down -v`, run step 2 again before loading.

## How to use

- **DB:** `postgresql://insure4all:insure4all@localhost:5433/insure4all` — set in [`docker-compose.yml`](docker-compose.yml) (server), [`2_transform/profiles.yml`](2_transform/profiles.yml) (dbt), and [`1_load/load_raw.py`](1_load/load_raw.py) defaults; override with `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE`.
- **Source CSVs:** live in `./data` (read-only; do not edit). Bare filenames in the loader resolve there; entity = stem before first `_` → `1_load/config.yaml` → `raw_*`.

## Outputs

| Mart | Question answered |
|------|-------------------|
| `marts.mart_monthly_sales_by_brand_type` | Monthly sales per brand per type |
| `marts.mart_claims_by_region` | Claims per region (monthly; roll up for overall) |
| `marts.mart_monthly_retention_by_brand_type` | Monthly retention rate per brand per product type |

## Adding another same-entity CSV

Put the file under `data/` with a name starting with the entity key (e.g. `customer_new.csv`), then:

```bash
uv run python 1_load/load_raw.py \
  customer_additional.csv \
  event_additional.csv \
  policy additional.csv
  
uv run --directory 2_transform dbt build
```

New entities need a row in [1_load/config.yaml](1_load/config.yaml) plus a matching `raw_*` table.

## Dependency management

Project deps live in [`pyproject.toml`](pyproject.toml); lockfile is [`uv.lock`](uv.lock).

```bash
uv add <package>          # add a dependency
uv remove <package>       # remove a dependency
uv sync                   # recreate/sync .venv from the lockfile
```
