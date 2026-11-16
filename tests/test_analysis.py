"""Tests for the SQL questions and the written brief.

Sample data, for reference (deaths per year):

    Country     2018-2024   2025   2026 (preliminary)
    Northland   1000        1100   400
    Southland   100         500    200
    Eastland    0           300    150
    Westland    10          40     5

The same deaths split by type of violence (no split for 2026, as in the real data):

    Country     2018-2024                           2025
    Northland   800 civil, 200 against civilians    900 civil, 200 against civilians
    Southland   100 between armed groups            100 between armed groups, 400 between states
    Eastland    none                                300 against civilians
    Westland    5 civil, 5 between armed groups     16 civil, 14 between armed groups,
                                                    10 against civilians
"""

from conflict_monitor import analysis, brief


def test_global_trend_adds_up_countries_only(con):
    trend = analysis.global_trend(con).set_index("year")
    # 1000 + 100 + 0 + 10. If World or the region were counted too, this would be far higher.
    assert trend.loc[2024, "deaths"] == 1110
    assert trend.loc[2025, "deaths"] == 1940


def test_global_trend_marks_preliminary_year(con):
    trend = analysis.global_trend(con).set_index("year")
    assert trend.loc[2025, "is_preliminary"] == 0
    assert trend.loc[2026, "is_preliminary"] == 1


def test_top_countries_are_ranked_highest_first(con):
    top = analysis.top_countries(con, year=2025, n=3)
    assert top["country"].tolist() == ["Northland", "Southland", "Eastland"]
    assert top["deaths"].tolist() == [1100, 500, 300]


def test_top_countries_leaves_out_zeros(con):
    top = analysis.top_countries(con, year=2024)
    assert "Eastland" not in top["country"].tolist()


def test_list_countries_excludes_aggregates(con):
    countries = analysis.list_countries(con)
    assert countries == ["Eastland", "Northland", "Southland", "Westland"]


def test_watchlist_flags_sharp_rise(con):
    watchlist = analysis.escalation_watchlist(con, year=2025).set_index("country")
    # Southland: 500 against an average of 100 is 5 times its baseline.
    assert watchlist.loc["Southland", "times_baseline"] == 5.0


def test_watchlist_flags_new_conflict(con):
    watchlist = analysis.escalation_watchlist(con, year=2025).set_index("country")
    # Eastland had no deaths before 2025, so there is no baseline to divide by.
    assert "Eastland" in watchlist.index
    assert watchlist.loc["Eastland", "baseline_avg"] == 0


def test_watchlist_ignores_steady_and_small(con):
    flagged = analysis.escalation_watchlist(con, year=2025)["country"].tolist()
    assert "Northland" not in flagged  # high but steady: 1.1 times its baseline
    assert "Westland" not in flagged   # 4 times its baseline, but only 40 deaths


def test_reconciliation_matches_world_figure(con):
    check = analysis.reconciliation(con)
    assert (check["difference"] == 0).all()


def test_deaths_by_type_worldwide_adds_up_countries_only(con):
    types = analysis.deaths_by_type(con)
    in_2025 = types[types["year"] == 2025].set_index("violence_type")["deaths"].to_dict()
    assert in_2025 == {
        "Civil conflict": 916,                 # 900 + 16
        "Fighting between armed groups": 114,  # 100 + 14
        "Fighting between states": 400,
        "Violence against civilians": 510,     # 200 + 300 + 10
    }
    # Types with no deaths are left out, and World and the region are not counted.
    assert sum(in_2025.values()) == 1940


def test_deaths_by_type_for_one_country(con):
    types = analysis.deaths_by_type(con, "Southland")
    in_2025 = types[types["year"] == 2025].set_index("violence_type")["deaths"].to_dict()
    assert in_2025 == {"Fighting between armed groups": 100, "Fighting between states": 400}


def test_top_countries_by_type_splits_the_top_countries(con):
    top = analysis.top_countries_by_type(con, year=2025, n=3)
    # Same three countries, in the same order, as test_top_countries_are_ranked_highest_first.
    assert top["country"].drop_duplicates().tolist() == ["Northland", "Southland", "Eastland"]
    assert top[["country", "violence_type", "deaths"]].values.tolist() == [
        ["Northland", "Civil conflict", 900],
        ["Northland", "Violence against civilians", 200],
        ["Southland", "Fighting between armed groups", 100],
        ["Southland", "Fighting between states", 400],
        ["Eastland", "Violence against civilians", 300],
    ]


def test_list_regions(con):
    assert analysis.list_regions(con) == ["Northern Region (UCDP)", "Southern Region (UCDP)"]


def test_top_countries_within_a_region(con):
    top = analysis.top_countries(con, year=2025, region="Northern Region (UCDP)")
    assert top.values.tolist() == [["Northland", 1100], ["Westland", 40]]


def test_list_countries_within_a_region(con):
    assert analysis.list_countries(con, region="Southern Region (UCDP)") == ["Eastland", "Southland"]


def test_watchlist_within_a_region(con):
    south = analysis.escalation_watchlist(con, year=2025, region="Southern Region (UCDP)")
    assert sorted(south["country"]) == ["Eastland", "Southland"]
    north = analysis.escalation_watchlist(con, year=2025, region="Northern Region (UCDP)")
    assert north.empty  # Northland is steady and Westland is too small


def test_top_countries_by_type_within_a_region(con):
    top = analysis.top_countries_by_type(con, year=2025, region="Southern Region (UCDP)")
    assert top["country"].drop_duplicates().tolist() == ["Southland", "Eastland"]


def test_region_check_matches_region_figure(con):
    check = analysis.region_check(con)
    # Only the northern region has its own figure in the sample: 2018 to 2026 is 9 years.
    assert check["region"].unique().tolist() == ["Northern Region (UCDP)"]
    assert len(check) == 9
    assert (check["difference"] == 0).all()


def test_type_check_finds_types_add_up(con):
    check = analysis.type_check(con)
    assert len(check) == 48  # 6 places (4 countries, the region, World) x 8 years
    assert (check["difference"] == 0).all()


def test_type_check_spots_a_gap(con):
    con.execute(
        "UPDATE conflict_deaths_by_type SET deaths = deaths + 7 "
        "WHERE entity = 'Northland' AND year = 2025 AND violence_type = 'Civil conflict'"
    )
    gaps = analysis.type_check(con).query("difference != 0")
    assert gaps[["entity", "year", "difference"]].values.tolist() == [["Northland", 2025, 7]]


def test_brief_states_the_figures(con):
    text = brief.render_brief(brief.country_facts(con, "Southland", year=2025))
    assert "500 conflict deaths in 2025" in text
    assert "up 400%" in text
    assert "5.0 times" in text
    assert "ranking 2nd" in text
    assert "analyst review required" in text


def test_brief_labels_preliminary_data(con):
    text = brief.render_brief(brief.country_facts(con, "Southland", year=2025))
    assert "Preliminary, part-year data for 2026 shows 200" in text


def test_brief_describes_new_conflict(con):
    text = brief.render_brief(brief.country_facts(con, "Eastland", year=2025))
    assert "new or re-emerging conflict" in text


def test_brief_names_the_main_type_of_violence(con):
    southland = brief.render_brief(brief.country_facts(con, "Southland", year=2025))
    assert "Most of these deaths (80%) were from fighting between states." in southland

    eastland = brief.render_brief(brief.country_facts(con, "Eastland", year=2025))
    assert "All of these deaths were from violence against civilians." in eastland

    # Westland: 16 of 40 is 40%, the largest share but not a majority.
    westland = brief.render_brief(brief.country_facts(con, "Westland", year=2025))
    assert "The largest share (40%) was from civil conflict." in westland


def test_brief_does_not_round_almost_all_up_to_100_percent():
    text = brief._type_phrase("Fighting between states", 999, 1000)
    assert text == "Almost all of these deaths (over 99%) were from fighting between states."


def test_brief_works_without_the_type_table(con):
    """A database built before the split by type existed still gets a brief."""
    con.execute("DROP TABLE conflict_deaths_by_type")
    text = brief.render_brief(brief.country_facts(con, "Southland", year=2025))
    assert "500 conflict deaths in 2025" in text
    assert "these deaths" not in text
