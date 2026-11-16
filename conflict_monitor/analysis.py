"""Step 3: questions we ask of the data, written as SQL.

Every function takes an open database connection and returns a table
(a pandas DataFrame). Keeping the questions here, away from the dashboard,
means they can be tested on their own and reused by other tools.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from . import config


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    """Open the database. Run the pipeline first if the file does not exist."""
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"No database at {db_path}. Run `python run_pipeline.py` first."
        )
    return sqlite3.connect(db_path)


def global_trend(con: sqlite3.Connection) -> pd.DataFrame:
    """Total deaths per year, added up across all countries."""
    query = """
        SELECT year,
               SUM(deaths)         AS deaths,
               MAX(is_preliminary) AS is_preliminary
        FROM conflict_deaths
        WHERE entity_type = 'country'
        GROUP BY year
        ORDER BY year
    """
    return pd.read_sql_query(query, con)


# Added to a WHERE clause to keep only places in one region. When :region is
# empty (None) it keeps every place, so "no region chosen" means "all regions".
IN_REGION = "(:region IS NULL OR entity IN (SELECT entity FROM country_regions WHERE region = :region))"


def has_table(con: sqlite3.Connection, table: str) -> bool:
    """True if the database has this table. Older databases may lack newer tables."""
    query = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return con.execute(query, (table,)).fetchone() is not None


def list_regions(con: sqlite3.Connection) -> list[str]:
    """UCDP's regions, such as "Africa (UCDP)", in alphabetical order."""
    query = "SELECT DISTINCT region FROM country_regions ORDER BY region"
    return pd.read_sql_query(query, con)["region"].tolist()


def list_countries(con: sqlite3.Connection, region: str | None = None) -> list[str]:
    """Every country that has recorded at least one death, in alphabetical order."""
    query = f"""
        SELECT entity
        FROM conflict_deaths
        WHERE entity_type = 'country' AND {IN_REGION}
        GROUP BY entity
        HAVING SUM(deaths) > 0
        ORDER BY entity
    """
    return pd.read_sql_query(query, con, params={"region": region})["entity"].tolist()


def top_countries(
    con: sqlite3.Connection, year: int, n: int = 10, region: str | None = None
) -> pd.DataFrame:
    """The n countries with the most deaths in one year, optionally within one region."""
    query = f"""
        SELECT entity AS country, deaths
        FROM conflict_deaths
        WHERE entity_type = 'country' AND year = :year AND deaths > 0 AND {IN_REGION}
        ORDER BY deaths DESC, entity
        LIMIT :n
    """
    return pd.read_sql_query(query, con, params={"year": year, "n": n, "region": region})


def country_trend(con: sqlite3.Connection, country: str) -> pd.DataFrame:
    """Deaths per year for one country."""
    query = """
        SELECT year, deaths, is_preliminary
        FROM conflict_deaths
        WHERE entity_type = 'country' AND entity = :country
        ORDER BY year
    """
    return pd.read_sql_query(query, con, params={"country": country})


def escalation_watchlist(
    con: sqlite3.Connection,
    year: int = config.LAST_FULL_YEAR,
    baseline_years: int = config.BASELINE_YEARS,
    ratio: float = config.WATCHLIST_RATIO,
    min_deaths: int = config.WATCHLIST_MIN_DEATHS,
    region: str | None = None,
) -> pd.DataFrame:
    """Countries where deaths in `year` are well above their own recent average.

    Optionally only countries in one region.

    The baseline is the average of the `baseline_years` years before `year`.
    A country is listed when deaths are at least `min_deaths` and at least
    `ratio` times its baseline. A baseline of zero means a new or re-emerging
    conflict, shown with an empty `times_baseline`.

    This is a simple, explainable flag for an analyst to look into. It is not
    a forecast.
    """
    query = f"""
        WITH latest AS (
            SELECT entity, deaths
            FROM conflict_deaths
            WHERE entity_type = 'country' AND year = :year AND {IN_REGION}
        ),
        baseline AS (
            SELECT entity, AVG(deaths) AS baseline_avg
            FROM conflict_deaths
            WHERE entity_type = 'country'
              AND year BETWEEN :baseline_start AND :baseline_end
            GROUP BY entity
        )
        SELECT latest.entity                    AS country,
               latest.deaths                    AS deaths,
               ROUND(baseline.baseline_avg, 1)  AS baseline_avg,
               CASE WHEN baseline.baseline_avg > 0
                    THEN ROUND(latest.deaths / baseline.baseline_avg, 1)
               END                              AS times_baseline
        FROM latest
        JOIN baseline ON baseline.entity = latest.entity
        WHERE latest.deaths >= :min_deaths
          AND latest.deaths >= :ratio * baseline.baseline_avg
        ORDER BY latest.deaths DESC
    """
    params = {
        "year": year,
        "baseline_start": year - baseline_years,
        "baseline_end": year - 1,
        "ratio": ratio,
        "min_deaths": min_deaths,
        "region": region,
    }
    return pd.read_sql_query(query, con, params=params)


def has_type_data(con: sqlite3.Connection) -> bool:
    """True if the database has the split by type of violence.

    A database built before this table was added will not have it until the
    pipeline is run again.
    """
    return has_table(con, "conflict_deaths_by_type")


def deaths_by_type(con: sqlite3.Connection, country: str | None = None) -> pd.DataFrame:
    """Deaths per year, split by type of violence.

    For one country, or for all countries added up if no country is given.
    Preliminary years are left out, and so are types with no deaths that year.
    """
    query = """
        SELECT year, violence_type, SUM(deaths) AS deaths
        FROM conflict_deaths_by_type
        WHERE entity_type = 'country'
          AND is_preliminary = 0
          AND (:country IS NULL OR entity = :country)
        GROUP BY year, violence_type
        HAVING SUM(deaths) > 0
        ORDER BY year, violence_type
    """
    return pd.read_sql_query(query, con, params={"country": country})


def top_countries_by_type(
    con: sqlite3.Connection, year: int, n: int = 10, region: str | None = None
) -> pd.DataFrame:
    """The same n countries as top_countries(), with each one's deaths split by type of violence.

    One row per country and type. `total` is the country's total that year, used
    to keep the countries in the same order as the top_countries() chart.
    """
    query = f"""
        WITH top AS (
            SELECT entity, deaths AS total
            FROM conflict_deaths
            WHERE entity_type = 'country' AND year = :year AND deaths > 0 AND {IN_REGION}
            ORDER BY deaths DESC, entity
            LIMIT :n
        )
        SELECT top.entity        AS country,
               by_type.violence_type,
               by_type.deaths,
               top.total
        FROM top
        JOIN conflict_deaths_by_type AS by_type
          ON by_type.entity = top.entity AND by_type.year = :year
        WHERE by_type.deaths > 0
        ORDER BY top.total DESC, top.entity, by_type.violence_type
    """
    return pd.read_sql_query(query, con, params={"year": year, "n": n, "region": region})


def region_check(con: sqlite3.Connection) -> pd.DataFrame:
    """Compare our country totals per region with UCDP's own region figure, year by year.

    Small differences are expected: UCDP files a few conflicts under a
    neighbouring region (for example near the border of Europe and Asia),
    while this project places deaths by the country where they happened.
    """
    query = """
        WITH ours AS (
            SELECT regions.region, deaths.year, SUM(deaths.deaths) AS sum_of_countries
            FROM conflict_deaths AS deaths
            JOIN country_regions AS regions ON regions.entity = deaths.entity
            WHERE deaths.entity_type = 'country'
            GROUP BY regions.region, deaths.year
        )
        SELECT ours.region,
               ours.year,
               ours.sum_of_countries,
               ucdp.deaths                           AS region_figure,
               ours.sum_of_countries - ucdp.deaths   AS difference
        FROM ours
        JOIN conflict_deaths AS ucdp ON ucdp.entity = ours.region AND ucdp.year = ours.year
        ORDER BY ours.region, ours.year
    """
    return pd.read_sql_query(query, con)


def type_check(con: sqlite3.Connection) -> pd.DataFrame:
    """Compare the types added together with the total, for every place and year in both tables.

    Both files are built from the same UCDP events, so `difference` should be 0
    everywhere. An empty result means the two tables have no place and year in
    common, which is itself a sign that something is wrong.
    """
    query = """
        WITH by_type AS (
            SELECT entity, year, SUM(deaths) AS sum_of_types
            FROM conflict_deaths_by_type
            GROUP BY entity, year
        )
        SELECT totals.entity,
               totals.year,
               totals.deaths                          AS total,
               by_type.sum_of_types,
               by_type.sum_of_types - totals.deaths   AS difference
        FROM conflict_deaths AS totals
        JOIN by_type ON by_type.entity = totals.entity AND by_type.year = totals.year
        ORDER BY totals.entity, totals.year
    """
    return pd.read_sql_query(query, con)


def reconciliation(con: sqlite3.Connection) -> pd.DataFrame:
    """Compare our country totals with the source's own World figure, year by year.

    Returns an empty table if the source file has no World row. Small gaps
    are possible (for example deaths not assigned to a country); large ones
    mean something is wrong with the data or with our country/aggregate labels.
    """
    query = """
        WITH ours AS (
            SELECT year, SUM(deaths) AS sum_of_countries
            FROM conflict_deaths
            WHERE entity_type = 'country'
            GROUP BY year
        ),
        world AS (
            SELECT year, deaths AS world_figure
            FROM conflict_deaths
            WHERE entity = 'World'
        )
        SELECT ours.year,
               ours.sum_of_countries,
               world.world_figure,
               ours.sum_of_countries - world.world_figure AS difference
        FROM ours
        JOIN world ON world.year = ours.year
        ORDER BY ours.year
    """
    return pd.read_sql_query(query, con)
