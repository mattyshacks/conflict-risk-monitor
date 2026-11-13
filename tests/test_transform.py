"""Tests for the cleaning and checking step."""

import sqlite3

import pandas as pd
import pytest

from conflict_monitor import transform
from conflict_monitor.transform import DataQualityError


def test_clean_gives_short_column_names(raw):
    clean = transform.clean(raw)
    assert list(clean.columns) == [
        "entity", "code", "year", "deaths", "entity_type", "is_preliminary",
    ]


def test_clean_separates_countries_from_aggregates(raw):
    clean = transform.clean(raw)
    types = clean.groupby("entity")["entity_type"].first()
    assert types["Northland"] == "country"
    assert types["World"] == "aggregate"            # has a code, but not a country code
    assert types["Northern Region"] == "aggregate"  # has no code at all


def test_clean_flags_preliminary_years(raw):
    clean = transform.clean(raw, last_full_year=2025)
    flagged_years = clean.loc[clean["is_preliminary"] == 1, "year"].unique().tolist()
    assert flagged_years == [2026]


def test_clean_drops_rows_with_no_figure(raw):
    raw.loc[0, raw.columns[3]] = None
    clean = transform.clean(raw)
    assert len(clean) == len(raw) - 1


def test_clean_rejects_negative_deaths(raw):
    raw.loc[0, raw.columns[3]] = -5
    with pytest.raises(DataQualityError, match="negative"):
        transform.clean(raw)


def test_clean_rejects_duplicate_rows(raw):
    doubled = pd.concat([raw, raw.head(1)], ignore_index=True)
    with pytest.raises(DataQualityError, match="twice"):
        transform.clean(doubled)


def test_clean_rejects_file_with_wrong_columns(raw):
    with pytest.raises(DataQualityError, match="missing column"):
        transform.clean(raw.rename(columns={"Entity": "Place"}))


def test_load_to_sqlite_writes_every_row(raw, tmp_path):
    clean = transform.clean(raw)
    db_path = tmp_path / "test.db"

    rows = transform.load_to_sqlite(clean, db_path)

    connection = sqlite3.connect(db_path)
    in_database = connection.execute("SELECT COUNT(*) FROM conflict_deaths").fetchone()[0]
    connection.close()
    assert rows == in_database == len(clean)


def test_load_to_sqlite_can_be_run_twice(raw, tmp_path):
    """Re-running the pipeline replaces the table rather than doubling it."""
    clean = transform.clean(raw)
    db_path = tmp_path / "test.db"
    transform.load_to_sqlite(clean, db_path)
    rows = transform.load_to_sqlite(clean, db_path)
    assert rows == len(clean)
