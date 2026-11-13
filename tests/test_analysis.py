"""Tests for the SQL questions and the written brief.

Sample data, for reference (deaths per year):

    Country     2018-2024   2025   2026 (preliminary)
    Northland   1000        1100   400
    Southland   100         500    200
    Eastland    0           300    150
    Westland    10          40     5
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
