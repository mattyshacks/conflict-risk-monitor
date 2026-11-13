"""Settings for the whole project, kept in one place.

If a path, URL or threshold needs to change, it changes here and nowhere else.
"""

from pathlib import Path

# Folders -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_FILE = RAW_DIR / "deaths_in_armed_conflicts_by_country.csv"
RAW_METADATA_FILE = RAW_DIR / "download_metadata.json"
DB_PATH = ROOT / "data" / "conflict.db"

# Data source ---------------------------------------------------------------
# Our World in Data publishes UCDP (Uppsala Conflict Data Program) figures as
# a plain CSV: one row per country per year.
SOURCE_PAGE = "https://ourworldindata.org/grapher/deaths-in-armed-conflicts-by-country"
DATA_URL = (
    "https://ourworldindata.org/grapher/deaths-in-armed-conflicts-by-country.csv"
    "?v=1&csvType=full&useColumnShortNames=false"
)

# Data rules ----------------------------------------------------------------
FIRST_YEAR = 1989
# The last year with complete, final figures. Anything later is preliminary
# (part of a year only), so it is flagged and left out of comparisons.
LAST_FULL_YEAR = 2025

# Watchlist defaults ----------------------------------------------------------
# A country is flagged when deaths in the chosen year are at least
# WATCHLIST_RATIO times its average over the previous BASELINE_YEARS years,
# and at least WATCHLIST_MIN_DEATHS (so tiny numbers don't trigger it).
BASELINE_YEARS = 5
WATCHLIST_RATIO = 2.0
WATCHLIST_MIN_DEATHS = 100
