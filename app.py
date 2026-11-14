"""The dashboard. Start it with:  streamlit run app.py

It only reads from the database built by run_pipeline.py. All the questions
it asks live in conflict_monitor/analysis.py, so this file is just layout.
"""

import json

import altair as alt
import pandas as pd
import streamlit as st

from conflict_monitor import analysis, brief, config

BLUE = "#2a78d6"  # the one colour used for data
GREY = "#8a8a86"  # used for preliminary figures and guide lines
# One colour per type of violence, in the order of config.VIOLENCE_TYPES.
# Each type always keeps its colour, whichever country is shown. Dark mode uses
# the same hues adjusted for a dark background; both sets were checked for
# colour-blind readers with the palette validator.
#   states: aqua, civil: orange, armed groups: blue, civilians: red, colonial: violet
TYPE_COLOURS_LIGHT = ["#1baf7a", "#eb6834", "#2a78d6", "#e34948", "#6250d6"]
TYPE_COLOURS_DARK = ["#199e70", "#d95926", "#3987e5", "#e66767", "#9085e9"]


def trend_chart(df: pd.DataFrame) -> alt.Chart:
    """Line chart of deaths per year. Preliminary years are shown as a hollow grey dot."""
    full = df[df["is_preliminary"] == 0]
    preliminary = df[df["is_preliminary"] == 1].assign(note="Preliminary, part-year")

    # Years run from the first to the last in the data, not from zero.
    x = alt.X(
        "year:Q",
        scale=alt.Scale(domain=[int(df["year"].min()) - 0.5, int(df["year"].max()) + 0.5]),
        axis=alt.Axis(format="d", title=None, grid=False, tickMinStep=1),
    )
    # Write small numbers in full (1,200) and large ones compactly (120k).
    number_format = "~s" if df["deaths"].max() >= 10_000 else ","
    y = alt.Y("deaths:Q", axis=alt.Axis(
        title=None, format=number_format, tickMinStep=1,
        labelExpr="datum.value == 0 ? '0' : datum.label"))
    tooltip = [alt.Tooltip("year:Q", title="Year", format="d"),
               alt.Tooltip("deaths:Q", title="Deaths", format=",")]

    # Hovering anywhere picks the nearest year and shows its value.
    hover = alt.selection_point(fields=["year"], nearest=True, on="pointerover", empty=False)

    line = alt.Chart(full).mark_line(color=BLUE, strokeWidth=2).encode(x=x, y=y)
    hover_dot = (
        alt.Chart(full)
        .mark_point(color=BLUE, filled=True, size=80)
        .encode(x=x, y=y, tooltip=tooltip,
                opacity=alt.condition(hover, alt.value(1), alt.value(0)))
        .add_params(hover)
    )
    hover_rule = (
        alt.Chart(full)
        .mark_rule(color=GREY, strokeWidth=1)
        .encode(x=x, opacity=alt.condition(hover, alt.value(0.5), alt.value(0)))
    )
    preliminary_dot = (
        alt.Chart(preliminary)
        .mark_point(color=GREY, filled=False, size=80, strokeWidth=2)
        .encode(x=x, y=y, tooltip=tooltip + [alt.Tooltip("note:N", title="Note")])
    )
    return (hover_rule + line + hover_dot + preliminary_dot).properties(height=300)


def ranked_bars(df: pd.DataFrame) -> alt.Chart:
    """Horizontal bars, largest first, with the value written at the end of each bar."""
    longest = df["deaths"].max()
    x = alt.X("deaths:Q", axis=None, scale=alt.Scale(domain=[0, longest * 1.18]))
    y = alt.Y("country:N", sort="-x", axis=alt.Axis(title=None, labelLimit=220, ticks=False))
    tooltip = [alt.Tooltip("country:N", title="Country"),
               alt.Tooltip("deaths:Q", title="Deaths", format=",")]

    bars = alt.Chart(df).mark_bar(color=BLUE, size=18, cornerRadiusEnd=4).encode(
        x=x, y=y, tooltip=tooltip)
    values = alt.Chart(df).mark_text(align="left", dx=6).encode(
        x=x, y=y, text=alt.Text("deaths:Q", format=","))
    return (bars + values).properties(height=alt.Step(30))


def type_colour(df: pd.DataFrame) -> alt.Color:
    """Colour by type of violence. Shared by every type chart so the colours always match."""
    all_types = list(config.VIOLENCE_TYPES.values())
    # Only list the types that appear, but keep each type's own colour.
    shown = [name for name in all_types if name in set(df["violence_type"])]
    palette = TYPE_COLOURS_DARK if st.context.theme.type == "dark" else TYPE_COLOURS_LIGHT
    colours = [palette[all_types.index(name)] for name in shown]
    return alt.Color("violence_type:N", title=None,
                     scale=alt.Scale(domain=shown, range=colours),
                     legend=alt.Legend(orient="top", direction="horizontal", labelLimit=260))


def stack_order(df: pd.DataFrame) -> pd.DataFrame:
    """Add a column that stacks the types in the same order in every chart."""
    all_types = list(config.VIOLENCE_TYPES.values())
    return df.assign(stack_order=df["violence_type"].map(all_types.index))


def type_chart(df: pd.DataFrame, years: list[int]) -> alt.Chart:
    """Stacked bars: one bar per year, split into the types of violence."""
    df = stack_order(df)

    # Every year gets a slot, so a year with no deaths shows as a gap, not as missing.
    x = alt.X("year:O", scale=alt.Scale(domain=years), axis=alt.Axis(
        title=None, labelAngle=0, labelExpr="datum.value % 5 == 0 ? datum.label : ''"))
    number_format = "~s" if df.groupby("year")["deaths"].sum().max() >= 10_000 else ","
    y = alt.Y("deaths:Q", stack=True, axis=alt.Axis(
        title=None, format=number_format, tickMinStep=1,
        labelExpr="datum.value == 0 ? '0' : datum.label"))
    tooltip = [alt.Tooltip("year:O", title="Year"),
               alt.Tooltip("violence_type:N", title="Type"),
               alt.Tooltip("deaths:Q", title="Deaths", format=",")]

    return alt.Chart(df).mark_bar().encode(
        x=x, y=y, color=type_colour(df), order=alt.Order("stack_order:Q"), tooltip=tooltip,
    ).properties(height=300)


def top_countries_type_chart(df: pd.DataFrame) -> alt.Chart:
    """Horizontal stacked bars: one bar per country, largest first, split into types.

    The country's total is written at the end of each bar, as in ranked_bars().
    """
    df = stack_order(df)
    countries = df["country"].drop_duplicates().tolist()  # already largest first
    totals = df[["country", "total"]].drop_duplicates()
    longest = totals["total"].max()

    x = alt.X("deaths:Q", stack=True, axis=None, scale=alt.Scale(domain=[0, longest * 1.18]))
    y = alt.Y("country:N", sort=countries, axis=alt.Axis(title=None, labelLimit=220, ticks=False))
    tooltip = [alt.Tooltip("country:N", title="Country"),
               alt.Tooltip("violence_type:N", title="Type"),
               alt.Tooltip("deaths:Q", title="Deaths", format=","),
               alt.Tooltip("total:Q", title="Country total", format=",")]

    bars = alt.Chart(df).mark_bar(size=18).encode(
        x=x, y=y, color=type_colour(df), order=alt.Order("stack_order:Q"), tooltip=tooltip)
    values = alt.Chart(totals).mark_text(align="left", dx=6).encode(
        x=alt.X("total:Q", scale=alt.Scale(domain=[0, longest * 1.18])), y=y,
        text=alt.Text("total:Q", format=","))
    return (bars + values).properties(height=alt.Step(30))


def top_countries_type_table(df: pd.DataFrame) -> pd.DataFrame:
    """The same numbers as the top-countries type chart, one row per country."""
    shown = [name for name in config.VIOLENCE_TYPES.values() if name in set(df["violence_type"])]
    order = df["country"].drop_duplicates().tolist()
    table = df.pivot(index="country", columns="violence_type", values="deaths")
    table = table.reindex(index=order, columns=shown).fillna(0).astype(int)
    table["Total"] = table.sum(axis=1)
    return table.reset_index()


def type_table(df: pd.DataFrame) -> pd.DataFrame:
    """The same numbers as the type chart, one row per year and one column per type."""
    shown = [name for name in config.VIOLENCE_TYPES.values() if name in set(df["violence_type"])]
    table = df.pivot(index="year", columns="violence_type", values="deaths")
    return table.reindex(columns=shown).fillna(0).astype(int).reset_index()


# --- Page ---------------------------------------------------------------------

st.set_page_config(page_title="Conflict Risk Monitor", layout="wide")
st.title("Conflict Risk Monitor")

try:
    con = analysis.connect()
except FileNotFoundError as error:
    st.error(str(error))
    st.stop()

trend = analysis.global_trend(con)
full_years = trend.loc[trend["is_preliminary"] == 0, "year"].tolist()
latest_full_year = max(full_years)

retrieved = "unknown date"
if config.RAW_METADATA_FILE.exists():
    retrieved = json.loads(config.RAW_METADATA_FILE.read_text())["retrieved_at_utc"][:10]
st.caption(
    f"Deaths of combatants and civilians from fighting in armed conflicts, by the country "
    f"where they occurred. Source: UCDP via [Our World in Data]({config.SOURCE_PAGE}), "
    f"retrieved {retrieved}."
)

# Filters, in one row above everything they control.
filter_year, filter_ratio, filter_min = st.columns(3)
year = filter_year.selectbox("Year", sorted(full_years, reverse=True), index=0)
ratio = filter_ratio.slider(
    "Watchlist: times above own 5-year average", 1.5, 10.0, config.WATCHLIST_RATIO, 0.5)
min_deaths = filter_min.slider(
    "Watchlist: minimum deaths in the year", 25, 1000, config.WATCHLIST_MIN_DEATHS, 25)

top = analysis.top_countries(con, year, n=10)
watchlist = analysis.escalation_watchlist(con, year, ratio=ratio, min_deaths=min_deaths)

# Headline numbers.
deaths_by_year = trend.set_index("year")["deaths"]
this_year = int(deaths_by_year[year])
previous_year = int(deaths_by_year[year - 1]) if (year - 1) in deaths_by_year.index else None

tile_total, tile_change, tile_watch = st.columns(3)
tile_total.metric(f"Deaths worldwide, {year}", f"{this_year:,}")
if previous_year:
    change = (this_year - previous_year) / previous_year * 100
    tile_change.metric(f"Change on {year - 1}", f"{change:+.0f}%")
tile_watch.metric("Countries on the watchlist", len(watchlist))

# Global trend.
st.subheader(f"Deaths worldwide per year, {min(full_years)} to {latest_full_year}")
st.altair_chart(trend_chart(trend), width="stretch")
if (trend["is_preliminary"] == 1).any():
    st.caption("The hollow grey dot is preliminary data covering only part of a year. "
               "It is not comparable with full years.")

# Global split by type of violence.
has_types = analysis.has_type_data(con)
TYPE_NOTE = (
    f"Source: UCDP via [Our World in Data]({config.TYPE_SOURCE_PAGE}). "
    "The split by type is not yet published for the preliminary year. "
    "What each type means is explained under *About the data and its limits* at the bottom."
)
if has_types:
    world_types = analysis.deaths_by_type(con)
    st.subheader(f"Deaths worldwide by type of violence, "
                 f"{world_types['year'].min()} to {world_types['year'].max()}")
    st.altair_chart(type_chart(world_types, full_years), width="stretch")
    st.caption(TYPE_NOTE)
    with st.expander("Show the numbers by type as a table"):
        st.dataframe(type_table(world_types), hide_index=True)
else:
    st.warning("The split by type of violence has not been loaded yet. "
               "Run `python run_pipeline.py` to add it.")

# Top countries and watchlist, side by side.
left, right = st.columns(2)
with left:
    st.subheader(f"Ten countries with the most deaths, {year}")
    if top.empty:
        st.write("No deaths recorded for this year.")
    else:
        st.altair_chart(ranked_bars(top), width="stretch")
with right:
    st.subheader(f"Escalation watchlist, {year}")
    st.caption(
        f"Countries with at least {min_deaths} deaths and at least {ratio:g} times their own "
        f"average for {year - config.BASELINE_YEARS} to {year - 1}. "
        "A flag for an analyst to look into, not a forecast."
    )
    if watchlist.empty:
        st.write("No countries meet these thresholds.")
    else:
        # No baseline means no deaths in the previous five years: show "new", not a blank.
        watchlist["times_baseline"] = watchlist["times_baseline"].map(
            lambda value: "new" if pd.isna(value) else f"{value:.1f}")
        st.dataframe(
            watchlist,
            hide_index=True,
            column_config={
                "country": "Country",
                "deaths": st.column_config.NumberColumn(f"Deaths {year}", format="localized"),
                "baseline_avg": st.column_config.NumberColumn("5-year average", format="localized"),
                "times_baseline": st.column_config.TextColumn(
                    "Times average", help='"new" means no deaths in the previous five years.'),
            },
        )

# The same top ten countries, split by type of violence.
if has_types and not top.empty:
    top_by_type = analysis.top_countries_by_type(con, year, n=10)
    st.subheader(f"Ten countries with the most deaths, by type of violence, {year}")
    st.altair_chart(top_countries_type_chart(top_by_type), width="stretch")
    st.caption(f"The same countries as the chart above. The number is each country's total for "
               f"{year}; hover over a segment for its figure. " + TYPE_NOTE)
    with st.expander("Show the numbers by type as a table"):
        st.dataframe(top_countries_type_table(top_by_type), hide_index=True)

# One country in detail.
st.subheader("Country brief")
countries = analysis.list_countries(con)
# Start on the country with the most deaths in the latest full year.
latest_top = analysis.top_countries(con, latest_full_year, n=1)
default_country = latest_top["country"].iloc[0] if not latest_top.empty else countries[0]
country = st.selectbox("Country", countries, index=countries.index(default_country))

st.info(brief.render_brief(brief.country_facts(con, country, year)))
country_data = analysis.country_trend(con, country)
st.altair_chart(trend_chart(country_data), width="stretch")
with st.expander("Show the numbers as a table"):
    st.dataframe(country_data, hide_index=True)

if has_types:
    country_types = analysis.deaths_by_type(con, country)
    st.markdown(f"**Deaths in {country} by type of violence**")
    if country_types.empty:
        st.write("No deaths recorded by type for this country.")
    else:
        st.altair_chart(type_chart(country_types, full_years), width="stretch")
        st.caption(TYPE_NOTE)
        with st.expander("Show the numbers by type as a table"):
            st.dataframe(type_table(country_types), hide_index=True)

with st.expander("About the data and its limits"):
    st.markdown(
        """
- **What is counted.** Deaths of combatants and civilians caused directly by fighting.
  Deaths from disease or hunger caused by a conflict are not included, so real tolls are higher.
- **Where.** Deaths are assigned to the country where they happened, not the nationality of the dead.
- **Which estimate.** These are UCDP's "best" estimates. UCDP also publishes low and high estimates.
- **Threshold.** UCDP counts a conflict once it causes at least 25 deaths in a year.
- **Preliminary years.** The most recent year is part-year and may be revised. It is flagged and
  left out of comparisons.
- **The watchlist** compares a country with its own recent past. It describes what has
  happened; it does not predict what will.
- **Types of violence** (UCDP's categories):
  - *Fighting between states*: two or more governments fighting each other (interstate).
  - *Civil conflict*: a government against a rebel or other armed group (intrastate).
    Foreign states may support either side.
  - *Fighting between armed groups*: armed groups fighting each other, with no government
    as a side (non-state).
  - *Violence against civilians*: a government or armed group using armed force against
    unarmed civilians (one-sided violence).
  - *Colonial or extrasystemic conflict*: a state fighting a group outside its own territory.
    None has been recorded since 1989.
- **Type tells you what kind of violence, not why it started.** The causes of a conflict
  need other sources and an analyst's judgement.
        """
    )

con.close()
