"""Shared set-up for the tests.

The tests never touch the internet. They run on tiny sample files with
fictional countries and invented numbers, so every expected answer can be
worked out by hand.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from conflict_monitor import transform

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_FILE = FIXTURES / "sample_conflict_deaths.csv"
SAMPLE_TYPE_FILE = FIXTURES / "sample_conflict_deaths_by_type.csv"
SAMPLE_REGION_FILE = FIXTURES / "sample_regions.csv"


@pytest.fixture
def raw() -> pd.DataFrame:
    """The sample file, exactly as the pipeline would read it."""
    return pd.read_csv(SAMPLE_FILE)


@pytest.fixture
def raw_by_type() -> pd.DataFrame:
    """The sample file split by type of violence. Its types add up to the totals in `raw`."""
    return pd.read_csv(SAMPLE_TYPE_FILE)


@pytest.fixture
def raw_regions() -> pd.DataFrame:
    """The sample region list: Northland and Westland in the north, Southland and Eastland in the south."""
    return pd.read_csv(SAMPLE_REGION_FILE)


@pytest.fixture
def con(raw, raw_by_type, raw_regions, tmp_path):
    """A temporary database built from all three sample files."""
    db_path = tmp_path / "test.db"
    transform.load_to_sqlite(transform.clean(raw), db_path)
    transform.load_to_sqlite(transform.clean_by_type(raw_by_type), db_path, table=transform.TYPE_TABLE)
    regions = transform.clean_regions(raw_regions, extra={})
    transform.load_to_sqlite(regions, db_path, table=transform.REGION_TABLE)
    connection = sqlite3.connect(db_path)
    yield connection
    connection.close()
