"""The weekly narrative: results retold against the series as it stood before the game."""

import pytest

from mustafatron.model import Game
from mustafatron.rules import load_rules
from mustafatron.stats.h2h import pair_record
from mustafatron.stats.narrative import TOKEN, headlines, recap
from mustafatron.stats.weekly import games_in, week_label
from mustafatron.transform import load_league

RULES = load_rules().rivalry


def g(season, week, home, away, hs, as_, tier="NONE"):
    winner = home if hs > as_ else away if as_ > hs else None
    return Game(season, week, tier, home, away, hs, as_, final=True, winner_id=winner)


@pytest.fixture(scope="module")
def league():
    return load_league(range(2015, 2026))


def test_the_game_never_counts_in_its_own_entering_record():
    # The scratch script's `before` line: history *before* the game, the streak *after* it.
    games = [g(2020, 1, "a", "b", 100, 90), g(2020, 2, "a", "b", 80, 95), g(2020, 3, "a", "b", 70, 110)]
    r = recap(games, games[1], RULES)
    assert (r.before.a, r.before.wins, r.before.losses) == ("b", 0, 1)  # b lost week 1
    assert (r.after.a, r.after.wins, r.after.losses) == ("b", 1, 1)
    assert r.text.startswith("@[b] beat @[a] 95.00–80.00.")
    assert "That evens the series at 1–1." in r.text
    assert "week 3" not in r.text and r.after.games == 2  # nothing from a later week


def test_first_meetings_streaks_and_snapped_streaks():
    games = [g(2019 + i, 1, "a", "b", 100, 90) for i in range(4)] + [g(2023, 1, "a", "b", 90, 120)]
    first = recap(games, games[0], RULES)
    assert first.first_meeting and "It was their first meeting." in first.text
    fourth = recap(games, games[3], RULES)
    assert "@[a] has won 4 straight against @[b], the longest run either way" in fourth.text
    assert [f.kind for f in fourth.flags] == ["streak", "lopsided"]
    snapped = recap(games, games[4], RULES)
    assert "@[a] still leads the series 4–1." in snapped.text
    assert "That snapped @[a]'s 4-game winning streak in the series." in snapped.text


def test_verbs_follow_the_margin():
    assert " edged " in recap([x := g(2020, 1, "a", "b", 100, 98.5)], x, RULES).text
    assert " crushed " in recap([x := g(2020, 1, "a", "b", 150, 100)], x, RULES).text
    assert " beat " in recap([x := g(2020, 1, "a", "b", 110, 100)], x, RULES).text


def test_every_week_on_record_can_be_told(league):
    for s in league.seasons.values():
        for week in sorted(s.settings.matchup_periods):
            for game in games_in(s, week):
                r = recap(league.games, game, RULES, week_label(s.settings, week))
                assert set(TOKEN.findall(r.text)) == {game.home_id, game.away_id}
                full = pair_record(league.games, r.after.a, r.after.b)
                assert r.before.games + 1 == r.after.games <= full.games


def test_the_2021_title_game(league):
    s = league.seasons[2021]
    final = next(x for x in games_in(s, 16) if x.is_championship_bracket)
    r = recap(league.games, final, RULES, "Championship")
    assert r.text.startswith("@[grudee] won the title, beating @[richardson] 188.40–157.46.")
    assert "Their third playoff meeting; @[grudee] won both before." in r.text


def test_the_tie_espn_broke(league):
    tied = next(x for x in league.seasons[2017].games if x.final and x.margin == 0)
    r = recap(league.games, tied, RULES, "Championship")
    assert "on ESPN's tiebreaker after a 154.00–154.00 tie" in r.text


def test_headlines(league):
    week = games_in(league.seasons[2022], 12)
    keys = [h.key for h in headlines(week)]
    assert keys == ["high_score", "low_score", "closest", "blowout"]
    assert headlines(week)[0].text == "High score: @[joyce], 133.52."
