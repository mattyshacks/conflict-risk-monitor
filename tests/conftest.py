"""Shared set-up for the tests.

The tests never touch the internet. They run on a tiny sample file with
fictional countries and invented numbers, so every expected answer can be
worked out by hand.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from conflict_monitor import transform

SAMPLE_FILE = Path(__file__).parent / "fixtures" / "sample_conflict_deaths.csv"


@pytest.fixture
def raw() -> pd.DataFrame:
    """The sample file, exactly as the pipeline would read it."""
    return pd.read_csv(SAMPLE_FILE)


@pytest.fixture
def con(raw, tmp_path):
    """A temporary database built from the sample file."""
    db_path = tmp_path / "test.db"
    transform.load_to_sqlite(transform.clean(raw), db_path)
    connection = sqlite3.connect(db_path)
    yield connection
    connection.close()
