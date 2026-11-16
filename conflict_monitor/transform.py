"""Step 2 of the pipeline: clean the raw data, check it, and load it into SQLite.

The raw file has one row per place per year. This step:
  1. gives the columns short, stable names
  2. labels each row as a country or an aggregate (World, regions)
  3. flags preliminary years
  4. refuses to continue if the data breaks a basic rule
  5. writes the result to a database table

It does this for two files: the totals (table conflict_deaths) and the same
deaths split by type of violence (table conflict_deaths_by_type). A third,
small file says which region each country is in (table country_regions).
"""

import sqlite3
from pathlib import Path

import pandas as pd

from . import config

TABLE = "conflict_deaths"
TYPE_TABLE = "conflict_deaths_by_type"
REGION_TABLE = "country_regions"


class DataQualityError(ValueError):
    """Raised when the data breaks a rule we rely on. Better to stop than to show wrong numbers."""


def load_raw(path: Path = config.RAW_FILE) -> pd.DataFrame:
    """Read the raw CSV into a table (a pandas DataFrame)."""
    return pd.read_csv(path)


def _entity_type(entity: str) -> str:
    """Totals ("aggregate") are World and UCDP's regions, such as "Africa (UCDP)".

    Every other row is a place. The name is used rather than the code because
    some places have no standard 3-letter code: Abyei, a disputed area between
    Sudan and South Sudan, has none, and Kosovo's is OWID_KOS.
    """
    if entity == "World" or entity.endswith("(UCDP)"):
        return "aggregate"
    return "country"


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

    # --- 3 to 5. Tidy, check the rules, add labels ---
    return _tidy_check_and_label(df, ["entity", "year"], last_full_year)


def clean_by_type(raw: pd.DataFrame, last_full_year: int = config.LAST_FULL_YEAR) -> pd.DataFrame:
    """Turn the raw by-type table into a tidy, validated one: one row per place, year and type."""
    # --- 1. Check the shape we expect: Entity, Code, Year and one column per type ---
    expected = ["Entity", "Code", "Year", *config.VIOLENCE_TYPES]
    missing = [name for name in expected if name not in raw.columns]
    if missing:
        raise DataQualityError(
            f"Raw file is missing column(s) {missing}. Found: {list(raw.columns)}"
        )

    # --- 2. One row per type instead of one column per type ---
    # This is called "long" format. It makes adding up and charting by type simple.
    df = raw.rename(columns={"Entity": "entity", "Code": "code", "Year": "year"}).melt(
        id_vars=["entity", "code", "year"],
        value_vars=list(config.VIOLENCE_TYPES),
        var_name="violence_type",
        value_name="deaths",
    )
    df["violence_type"] = df["violence_type"].map(config.VIOLENCE_TYPES)  # plain-English names

    # --- 3 to 5. Tidy, check the rules, add labels ---
    return _tidy_check_and_label(df, ["entity", "year", "violence_type"], last_full_year)


def _tidy_check_and_label(
    df: pd.DataFrame, key_columns: list[str], last_full_year: int
) -> pd.DataFrame:
    """Shared by both tables. `key_columns` are the columns that must be unique together."""
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
    duplicates = df.duplicated(subset=key_columns)
    if duplicates.any():
        examples = df.loc[duplicates, key_columns].head(3).to_dict("records")
        raise DataQualityError(
            f"The same {' + '.join(key_columns)} appears twice, e.g. {examples}"
        )

    # --- 5. Add the labels the analysis needs ---
    df["entity_type"] = df["entity"].map(_entity_type)
    df["is_preliminary"] = (df["year"] > last_full_year).astype(int)

    return df.sort_values(key_columns).reset_index(drop=True)


def clean_regions(raw: pd.DataFrame, extra: dict[str, str] | None = None) -> pd.DataFrame:
    """Turn the raw region list into a table of (entity, region), one row per place.

    `extra` adds places the list leaves out (config.EXTRA_REGIONS by default).
    If the list already has one of them, the list's own entry is kept.
    """
    extra = config.EXTRA_REGIONS if extra is None else extra

    # --- 1. Check the shape we expect: Entity, then the region column last ---
    if "Entity" not in raw.columns or len(raw.columns) < 2:
        raise DataQualityError(f"Region file has unexpected columns: {list(raw.columns)}")
    region_column = raw.columns[-1]
    df = raw.rename(columns={"Entity": "entity", region_column: "region"})[["entity", "region"]]

    # --- 2. Rules ---
    if df["region"].isna().any():
        raise DataQualityError("Region file has places with no region.")
    if not df["region"].str.endswith("(UCDP)").all():
        raise DataQualityError("Region file has regions that are not UCDP regions.")
    duplicates = df["entity"].duplicated()
    if duplicates.any():
        examples = df.loc[duplicates, "entity"].head(3).tolist()
        raise DataQualityError(f"The same place appears twice in the region file, e.g. {examples}")

    # --- 3. Add the places placed by hand, unless the list already has them ---
    missing = {place: region for place, region in extra.items() if place not in set(df["entity"])}
    added = pd.DataFrame({"entity": list(missing), "region": list(missing.values())})
    df = pd.concat([df, added], ignore_index=True)

    return df.sort_values("entity").reset_index(drop=True)


def check_every_place_has_region(clean: pd.DataFrame, regions: pd.DataFrame) -> None:
    """Stop if any place with recorded deaths has no region.

    Otherwise its deaths would silently disappear whenever a region is chosen.
    The fix is to add the place to EXTRA_REGIONS in config.py.
    """
    places = clean.loc[(clean["entity_type"] == "country") & (clean["deaths"] > 0), "entity"]
    without_region = sorted(set(places) - set(regions["entity"]))
    if without_region:
        raise DataQualityError(
            f"Places with deaths but no region: {without_region}. "
            "Add them to EXTRA_REGIONS in config.py."
        )


def load_to_sqlite(df: pd.DataFrame, db_path: Path = config.DB_PATH, table: str = TABLE) -> int:
    """Write a clean table to SQLite, replacing any previous version. Returns the row count."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        df.to_sql(table, con, if_exists="replace", index=False)
        # An index makes "all years for one country" lookups fast.
        # The region table has no years and is small, so it needs none.
        if "year" in df.columns:
            con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table} ON {table} (entity, year)")
        con.commit()
    finally:
        con.close()
    return len(df)
