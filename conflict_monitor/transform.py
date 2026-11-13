"""Step 2 of the pipeline: clean the raw data, check it, and load it into SQLite.

The raw file has one row per place per year. This step:
  1. gives the columns short, stable names
  2. labels each row as a country or an aggregate (World, regions)
  3. flags preliminary years
  4. refuses to continue if the data breaks a basic rule
  5. writes the result to a database table
"""

import sqlite3
from pathlib import Path

import pandas as pd

from . import config

TABLE = "conflict_deaths"


class DataQualityError(ValueError):
    """Raised when the data breaks a rule we rely on. Better to stop than to show wrong numbers."""


def load_raw(path: Path = config.RAW_FILE) -> pd.DataFrame:
    """Read the raw CSV into a table (a pandas DataFrame)."""
    return pd.read_csv(path)


def _entity_type(code) -> str:
    """Countries have a 3-letter code (ZAF, UKR). World and regions do not."""
    if isinstance(code, str) and (len(code) == 3 or code == "OWID_KOS"):  # Kosovo's code is special
        return "country"
    return "aggregate"


def clean(raw: pd.DataFrame, last_full_year: int = config.LAST_FULL_YEAR) -> pd.DataFrame:
    """Turn the raw table into a tidy, validated one."""
    # --- 1. Check the shape we expect: Entity, Code, Year, then the numbers ---
    expected = ["Entity", "Code", "Year"]
    missing = [name for name in expected if name not in raw.columns]
    if missing:
        raise DataQualityError(
            f"Raw file is missing column(s) {missing}. Found: {list(raw.columns)}"
        )

    # The deaths column has a long descriptive name that may change between
    # releases, so we find it by position: the first numeric column after the
    # three identifiers.
    value_columns = [
        name
        for name in raw.columns
        if name not in expected and pd.api.types.is_numeric_dtype(raw[name])
    ]
    if not value_columns:
        raise DataQualityError("Raw file has no numeric column to use as deaths.")
    deaths_column = value_columns[0]

    # --- 2. Rename and keep only what we need ---
    df = raw.rename(
        columns={"Entity": "entity", "Code": "code", "Year": "year", deaths_column: "deaths"}
    )[["entity", "code", "year", "deaths"]]

    # --- 3. Tidy values ---
    df = df.dropna(subset=["deaths"]).copy()  # a missing figure is not the same as zero
    df["year"] = df["year"].astype(int)
    df["deaths"] = df["deaths"].astype(int)

    # --- 4. Data quality rules: stop if any is broken ---
    if df.empty:
        raise DataQualityError("No rows left after removing missing values.")
    if (df["deaths"] < 0).any():
        raise DataQualityError("Found negative death counts.")
    if (df["year"] < config.FIRST_YEAR).any():
        raise DataQualityError(f"Found years before {config.FIRST_YEAR}.")
    duplicates = df.duplicated(subset=["entity", "year"])
    if duplicates.any():
        examples = df.loc[duplicates, ["entity", "year"]].head(3).to_dict("records")
        raise DataQualityError(f"Same place and year appears twice, e.g. {examples}")

    # --- 5. Add the labels the analysis needs ---
    df["entity_type"] = df["code"].map(_entity_type)
    df["is_preliminary"] = (df["year"] > last_full_year).astype(int)

    return df.sort_values(["entity", "year"]).reset_index(drop=True)


def load_to_sqlite(df: pd.DataFrame, db_path: Path = config.DB_PATH) -> int:
    """Write the clean table to SQLite, replacing any previous version. Returns the row count."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        df.to_sql(TABLE, con, if_exists="replace", index=False)
        # An index makes "all years for one country" lookups fast.
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_entity_year ON {TABLE} (entity, year)")
        con.commit()
    finally:
        con.close()
    return len(df)
