"""Step 4: a short written brief for one country.

Two parts, kept separate on purpose:

  country_facts()  pulls the numbers from the database into a small dictionary
  render_brief()   turns that dictionary into a paragraph using a fixed template

Because every sentence is built from the facts dictionary, nothing in the
brief can be invented. A later version can hand the same dictionary to a
language model to write a more natural paragraph, and the facts stay the
single source of truth.
"""

import sqlite3

from . import analysis, config

SOURCE_NOTE = (
    "Source: UCDP via Our World in Data (best estimates). "
    "Draft generated from data; analyst review required."
)


def country_facts(
    con: sqlite3.Connection, country: str, year: int = config.LAST_FULL_YEAR
) -> dict:
    """Collect the key numbers for one country into a dictionary."""
    rows = con.execute(
        """
        SELECT year, deaths, is_preliminary
        FROM conflict_deaths
        WHERE entity_type = 'country' AND entity = ?
        ORDER BY year
        """,
        (country,),
    ).fetchall()
    if not rows:
        raise ValueError(f"No data for country: {country}")

    full_years = {y: d for y, d, preliminary in rows if not preliminary}
    preliminary = {y: d for y, d, is_prelim in rows if is_prelim}

    deaths = full_years.get(year)
    previous = full_years.get(year - 1)
    baseline_values = [
        full_years[y] for y in range(year - config.BASELINE_YEARS, year) if y in full_years
    ]
    baseline_avg = sum(baseline_values) / len(baseline_values) if baseline_values else None
    peak_year = max(full_years, key=full_years.get) if full_years else None

    # Where does this country rank among all countries in that year?
    rank = None
    if deaths:
        rank = con.execute(
            """
            SELECT COUNT(*) + 1
            FROM conflict_deaths
            WHERE entity_type = 'country' AND year = ? AND deaths > ?
            """,
            (year, deaths),
        ).fetchone()[0]

    # Which type of violence caused the most deaths that year, and what share?
    main_type, main_type_deaths, type_total = None, None, None
    if deaths and analysis.has_type_data(con):
        types = analysis.deaths_by_type(con, country)
        types = types[types["year"] == year]
        if not types.empty:
            biggest = types.loc[types["deaths"].idxmax()]
            main_type = biggest["violence_type"]
            main_type_deaths = int(biggest["deaths"])
            type_total = int(types["deaths"].sum())

    return {
        "country": country,
        "year": year,
        "deaths": deaths,
        "previous_year_deaths": previous,
        "baseline_years": len(baseline_values),
        "baseline_avg": baseline_avg,
        "rank": rank,
        "peak_year": peak_year,
        "peak_deaths": full_years.get(peak_year),
        "total_since_start": sum(full_years.values()),
        "first_year": min(full_years) if full_years else None,
        "preliminary_year": max(preliminary) if preliminary else None,
        "preliminary_deaths": preliminary[max(preliminary)] if preliminary else None,
        "main_violence_type": main_type,
        "main_violence_type_deaths": main_type_deaths,
        "violence_type_total": type_total,
    }


def _change_phrase(current: int, previous: int | None) -> str:
    """Describe the change from the previous year in words."""
    if previous is None:
        return ""
    if previous == 0:
        return ", after none recorded the year before" if current > 0 else ""
    change = (current - previous) / previous * 100
    if abs(change) < 1:
        return ", about the same as the year before"
    direction = "up" if change > 0 else "down"
    return f", {direction} {abs(change):.0f}% on the year before ({previous:,})"


def _type_phrase(main_type: str | None, main_deaths: int | None, total: int | None) -> str:
    """Describe the main type of violence in words, e.g. 'Most of these deaths (80%) were from ...'."""
    if not main_type or not total:
        return ""
    name = main_type[0].lower() + main_type[1:]  # "Civil conflict" -> "civil conflict"
    if main_deaths == total:
        return f"All of these deaths were from {name}."
    share = main_deaths / total * 100
    if share >= 99.5:  # would round to "100%", which is not quite true
        return f"Almost all of these deaths (over 99%) were from {name}."
    if share > 50:
        return f"Most of these deaths ({share:.0f}%) were from {name}."
    return f"The largest share ({share:.0f}%) was from {name}."


def render_brief(facts: dict) -> str:
    """Write the brief from the facts, using a fixed template."""
    country, year, deaths = facts["country"], facts["year"], facts["deaths"]

    if deaths is None:
        return f"{country}: no figure is available for {year}. {SOURCE_NOTE}"

    sentences = []

    # Sentence 1: the headline figure and how it changed.
    if deaths == 0:
        sentences.append(f"{country} recorded no conflict deaths in {year}.")
    else:
        headline = f"{country} recorded {deaths:,} conflict deaths in {year}"
        headline += _change_phrase(deaths, facts["previous_year_deaths"])
        if facts["rank"]:
            headline += f", ranking {_ordinal(facts['rank'])} worldwide"
        sentences.append(headline + ".")

    # Sentence 1b: what kind of violence caused most of them.
    type_sentence = _type_phrase(
        facts["main_violence_type"], facts["main_violence_type_deaths"], facts["violence_type_total"]
    )
    if type_sentence:
        sentences.append(type_sentence)

    # Sentence 2: compared with its own recent history.
    baseline = facts["baseline_avg"]
    if deaths and baseline:
        times = deaths / baseline
        sentences.append(
            f"That is {times:.1f} times its average over the previous "
            f"{facts['baseline_years']} years ({baseline:,.0f} a year)."
        )
    elif deaths and baseline == 0:
        sentences.append(
            f"No deaths were recorded in the previous {facts['baseline_years']} years, "
            "so this is a new or re-emerging conflict."
        )

    # Sentence 3: the long view.
    if facts["peak_deaths"]:
        sentences.append(
            f"Its worst year since {facts['first_year']} was {facts['peak_year']} "
            f"({facts['peak_deaths']:,}); the total since {facts['first_year']} "
            f"is {facts['total_since_start']:,}."
        )

    # Sentence 4: preliminary figure, clearly labelled.
    if facts["preliminary_year"]:
        sentences.append(
            f"Preliminary, part-year data for {facts['preliminary_year']} shows "
            f"{facts['preliminary_deaths']:,} so far; this may be revised."
        )

    return " ".join(sentences) + " " + SOURCE_NOTE


def _ordinal(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 3 -> 3rd, 11 -> 11th."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
