#!/usr/bin/env python3
"""Load CSV files into Postgres raw_ tables per 1_load/config.yaml."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"
METADATA_COLS = {"loaded_at", "source_file"}


class SchemaShiftError(Exception):
    """Raised when CSV columns do not match the target raw table."""


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        user=os.getenv("PGUSER", "insure4all"),
        password=os.getenv("PGPASSWORD", "insure4all"),
        dbname=os.getenv("PGDATABASE", "insure4all"),
    )


def load_config(path: Path) -> dict[str, str]:
    """Return entity_name → table mapping from config.yaml."""
    with path.open() as f:
        cfg = yaml.safe_load(f) or {}
    tables = cfg.get("tables") or {}
    if not tables:
        raise ValueError(f"No tables mapping in {path}")
    return {str(k): str(v) for k, v in tables.items()}


def entity_key_from_filename(filename: str) -> str:
    """Take stem before the first '_': customer_additional.csv → customer."""
    stem = Path(filename).stem
    return stem.split("_", 1)[0]


def resolve_csv_path(file_arg: str) -> Path:
    """Resolve a CLI file arg to an absolute CSV path under the project."""
    p = Path(file_arg)
    candidates = [
        p if p.is_absolute() else (Path.cwd() / p),
        PROJECT_ROOT / p,
        DATA_DIR / p.name,
    ]
    for c in candidates:
        resolved = c.resolve()
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(f"CSV not found: {file_arg}")


def resolve_table(file_arg: str, tables: dict[str, str]) -> str:
    key = entity_key_from_filename(Path(file_arg).name)
    if key not in tables:
        known = ", ".join(sorted(tables))
        raise KeyError(
            f"No table mapping for entity '{key}' "
            f"(from filename '{Path(file_arg).name}'). Known: {known}"
        )
    return tables[key]


def _header_for_raw(name: object, position: int) -> str:
    """Map empty / pandas Unnamed first column to csv_row_index; keep other names exact.

    Source CSVs under data/ are never rewritten. Only this in-memory mapping is applied
    so an original header like `,customer_id,...` matches the raw table column.
    """
    s = str(name)
    if position == 0 and (s == "" or s.startswith("Unnamed:")):
        return "csv_row_index"
    return s


def read_csv_as_strings(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read CSV as strings. No whitespace strip; only empty first header → csv_row_index."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    if len(df.columns) == 0:
        raise ValueError(f"CSV has no header: {csv_path}")
    fieldnames = [_header_for_raw(c, i) for i, c in enumerate(df.columns)]
    if len(fieldnames) != len(set(fieldnames)):
        raise ValueError(f"Duplicate column names after header mapping: {fieldnames}")
    df.columns = fieldnames
    rows = df.to_dict(orient="records")
    return fieldnames, rows


def get_sql_columns(conn: psycopg.Connection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        cols = [r[0] for r in cur.fetchall()]
    if not cols:
        raise ValueError(f"Table not found: {table}")
    return [c for c in cols if c not in METADATA_COLS]


def assert_schema_match(csv_cols: list[str], table_cols: list[str], table: str, source: str) -> None:
    csv_set = list(csv_cols)
    tbl_set = list(table_cols)
    if csv_set != tbl_set:
        missing_in_csv = [c for c in tbl_set if c not in csv_set]
        extra_in_csv = [c for c in csv_set if c not in tbl_set]
        raise SchemaShiftError(
            f"Schema shift for {source} → {table}. "
            f"CSV columns={csv_set}; Current SQL columns={tbl_set}. "
            f"Missing in CSV={missing_in_csv}; extra in CSV={extra_in_csv}. "
            "Alter the raw table and dbt models explicitly before reloading."
        )


def load_file(conn: psycopg.Connection, csv_path: Path, table: str, loaded_at: datetime) -> int:
    source_file = csv_path.name
    fieldnames, rows = read_csv_as_strings(csv_path)
    expected = get_sql_columns(conn, table)
    assert_schema_match(fieldnames, expected, table, source_file)

    insert_cols = expected + ["loaded_at", "source_file"]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    delete_sql = f"DELETE FROM {table} WHERE source_file = %s"
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

    with conn.cursor() as cur:
        cur.execute(delete_sql, (source_file,))
        deleted = cur.rowcount
        batch = []
        for row in rows:
            values = [row.get(c, "") for c in expected]
            values.extend([loaded_at, source_file])
            batch.append(tuple(values))
        if batch:
            cur.executemany(insert_sql, batch)
        inserted = len(batch)
    conn.commit()
    print(
        f"Loaded {source_file} → {table}: deleted={deleted}, inserted={inserted}"
    )
    return inserted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Load CSVs into raw_ tables. Pass filenames; entity is the stem "
            "before the first '_', looked up in 1_load/config.yaml."
        )
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="CSV filenames or paths, e.g. customer.csv customer_additional.csv",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(os.getenv("LOAD_CONFIG", str(CONFIG_PATH)))
    tables = load_config(config_path)
    loaded_at = datetime.now().replace(microsecond=0)

    try:
        with get_connection() as conn:
            total = 0
            for file_arg in args.files:
                csv_path = resolve_csv_path(file_arg)
                table = resolve_table(file_arg, tables)
                total += load_file(conn, csv_path, table, loaded_at)
            print(f"Done. Total rows inserted: {total}")
    except SchemaShiftError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
