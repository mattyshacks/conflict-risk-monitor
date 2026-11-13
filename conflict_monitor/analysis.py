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


def list_countries(con: sqlite3.Connection) -> list[str]:
    """Every country that has recorded at least one death, in alphabetical order."""
    query = """
        SELECT entity
        FROM conflict_deaths
        WHERE entity_type = 'country'
        GROUP BY entity
        HAVING SUM(deaths) > 0
        ORDER BY entity
    """
    return pd.read_sql_query(query, con)["entity"].tolist()


def top_countries(con: sqlite3.Connection, year: int, n: int = 10) -> pd.DataFrame:
    """The n countries with the most deaths in one year."""
    query = """
        SELECT entity AS country, deaths
        FROM conflict_deaths
        WHERE entity_type = 'country' AND year = :year AND deaths > 0
        ORDER BY deaths DESC, entity
        LIMIT :n
    """
    return pd.read_sql_query(query, con, params={"year": year, "n": n})


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
) -> pd.DataFrame:
    """Countries where deaths in `year` are well above their own recent average.

    The baseline is the average of the `baseline_years` years before `year`.
    A country is listed when deaths are at least `min_deaths` and at least
    `ratio` times its baseline. A baseline of zero means a new or re-emerging
    conflict, shown with an empty `times_baseline`.

    This is a simple, explainable flag for an analyst to look into. It is not
    a forecast.
    """
    query = """
        WITH latest AS (
            SELECT entity, deaths
            FROM conflict_deaths
            WHERE entity_type = 'country' AND year = :year
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
    }
    return pd.read_sql_query(query, con, params=params)


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
