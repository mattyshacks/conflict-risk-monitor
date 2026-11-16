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
    assert types["World"] == "aggregate"
    assert types["Northern Region (UCDP)"] == "aggregate"


def test_clean_counts_places_without_a_standard_code(raw):
    """Places such as Abyei (a disputed area) have no 3-letter code but are still places.

    Treating them as totals would drop their deaths from every chart and ranking.
    """
    extra = pd.DataFrame(
        [["Disputed Area", None, 2025, 5], ["Old Federation", "OWID_OFD", 2025, 0]],
        columns=raw.columns,
    )
    clean = transform.clean(pd.concat([raw, extra], ignore_index=True))
    types = clean.groupby("entity")["entity_type"].first()
    assert types["Disputed Area"] == "country"
    assert types["Old Federation"] == "country"


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


def test_clean_by_type_gives_one_row_per_type(raw_by_type):
    clean = transform.clean_by_type(raw_by_type)
    assert list(clean.columns) == [
        "entity", "code", "year", "violence_type", "deaths", "entity_type", "is_preliminary",
    ]
    assert len(clean) == len(raw_by_type) * 5  # five types for every place and year
    assert set(clean["violence_type"]) == {
        "Fighting between states", "Civil conflict", "Fighting between armed groups",
        "Violence against civilians", "Colonial or extrasystemic conflict",
    }


def test_clean_by_type_rejects_file_missing_a_type(raw_by_type):
    with pytest.raises(DataQualityError, match="missing column"):
        transform.clean_by_type(raw_by_type.drop(columns=["Interstate"]))


def test_clean_by_type_rejects_negative_deaths(raw_by_type):
    raw_by_type.loc[0, "Intrastate"] = -5
    with pytest.raises(DataQualityError, match="negative"):
        transform.clean_by_type(raw_by_type)


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
