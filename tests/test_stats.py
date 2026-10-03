"""Invariants of the stats layer over every finished season (no network)."""

import pytest

from mustafatron.model import Game
from mustafatron.rules import load_rules
from mustafatron.stats.h2h import all_pairs, notable_flags, pair_record, record_between, rivalries
from mustafatron.stats.records import one_week_games, records_book
from mustafatron.stats.standings import all_time_standings, championship_ledger
from mustafatron.transform import load_league

SEASONS = range(2015, 2026)
LEAGUE = load_league(SEASONS)
RULES = load_rules()
PAIRS = all_pairs(LEAGUE.games)
STANDINGS = all_time_standings(LEAGUE, RULES)


def g(season, week, home, away, hs, as_, tier="NONE"):
    winner = home if hs > as_ else away if as_ > hs else None
    return Game(season, week, tier, home, away, hs, as_, final=True, winner_id=winner)


def test_pairs_cover_every_game_once():
    assert sum(p.games for p in PAIRS.values()) == len(LEAGUE.games) == 830
    assert all(a < b for a, b in PAIRS)


def test_series_from_either_side():
    ab = record_between(PAIRS, "dickey", "grudee")
    ba = record_between(PAIRS, "grudee", "dickey")
    assert (ab.wins, ab.losses) == (ba.losses, ba.wins)
    assert ab.points_for == ba.points_against
    assert record_between(PAIRS, "ray", "hunter").games == 0  # never in the league together


def test_streaks_and_extremes():
    games = [
        g(2015, 1, "a", "b", 100, 90),
        g(2015, 2, "b", "a", 80, 120),
        g(2016, 1, "a", "b", 70, 70),
        g(2016, 2, "a", "b", 60, 95),
        g(2017, 1, "b", "a", 110, 100, tier="WINNERS_BRACKET"),
    ]
    p = pair_record(games, "a", "b")
    assert (p.wins, p.losses, p.ties, p.results) == (2, 2, 1, "WWTLL")
    assert (p.current_streak.holder, p.current_streak.length) == ("b", 2)
    assert (p.longest_streak("a"), p.longest_streak("b")) == (2, 2)
    assert (p.closest.season, p.closest.margin) == (2016, 0.0)
    assert (p.blowout.season, p.blowout.week, p.blowout.margin) == (2015, 2, 40.0)
    assert (p.playoff_wins, p.playoff_losses) == (0, 1)
    assert p.before(2016, 2).results == "WWT"
    assert p.flipped().results == "LLTWW"


def test_notable_flags():
    games = [g(2015 + i, 1, "a", "b", 100, 90) for i in range(4)]
    kinds = [(f.kind, f.holder) for f in notable_flags(pair_record(games, "a", "b"), RULES.rivalry)]
    assert kinds == [("streak", "a"), ("lopsided", "a")]
    assert notable_flags(pair_record(games[:2], "a", "b"), RULES.rivalry) == []


def test_rivalries_need_enough_meetings():
    rivals = rivalries(PAIRS, RULES.rivalry)
    assert rivals and all(p.games >= RULES.rivalry.min_matchups for p in rivals)


def test_standings_add_up():
    assert sum(s.championships for s in STANDINGS) == len(SEASONS)
    assert sum(s.runner_ups for s in STANDINGS) == sum(s.third_places for s in STANDINGS) == len(SEASONS)
    assert sum(s.playoff_appearances for s in STANDINGS) == 4 * len(SEASONS)
    assert sum(s.wins for s in STANDINGS) == sum(s.losses for s in STANDINGS)
    # Each season pays out 6.5 + 2.5 + 0 and seven buy-ins are lost: +2.0 net across the league.
    assert sum(s.net_payout for s in STANDINGS) == pytest.approx(2.0 * len(SEASONS))
    assert sum(s.seasons for s in STANDINGS) == 10 * len(SEASONS)


def test_standings_splits_and_finishes():
    assert sum(s.last_places for s in STANDINGS) == len(SEASONS)
    assert sum(s.playoff_wins for s in STANDINGS) == sum(s.playoff_losses for s in STANDINGS)
    for s in STANDINGS:
        assert s.finished_seasons == s.seasons  # 2015-2025 are all finished
        assert s.best_finish <= s.avg_finish <= s.worst_finish
        assert s.roi == pytest.approx(s.net_payout / s.seasons)
        assert s.avg_margin == pytest.approx((s.points_for - s.points_against) / s.games)
        # Every champion won its bracket games: at least two playoff wins per title.
        assert s.playoff_wins >= 2 * s.championships
        if s.playoff_appearances == 0:
            assert s.playoff_wins == s.playoff_losses == 0


def test_championship_ledger():
    ledger = championship_ledger(LEAGUE)
    assert [e.season for e in ledger] == sorted(SEASONS, reverse=True)
    for e in ledger:
        season = LEAGUE.seasons[e.season]
        assert e.champion == season.champion_id
        assert len({e.champion, e.runner_up, e.third, e.last}) == 4
        assert season.team_of(e.top_seed).playoff_seed == 1
        assert 1 <= e.champion_seed <= season.settings.playoff_team_count
    titles = {s.manager_id: s.championships for s in STANDINGS}
    assert all(titles[e.champion] >= 1 for e in ledger)


def test_playoff_appearances_match_the_bracket():
    for s in LEAGUE.seasons.values():
        seeded = {t.manager_id for t in s.teams if t.playoff_seed <= s.settings.playoff_team_count}
        bracket = {m for gm in s.games if gm.is_championship_bracket for m in (gm.home_id, gm.away_id)}
        assert seeded == bracket, s.season


def test_single_game_records_skip_two_week_matchups():
    games = one_week_games(LEAGUE)
    assert games and all(len(LEAGUE.seasons[x.season].settings.scoring_periods(x.week)) == 1 for x in games)
    book = records_book(LEAGUE, n=5)
    assert all(len(v) == 5 for v in book.values())
    top = book["highest_score"]
    assert [m.score for m in top] == sorted((m.score for m in top), reverse=True)
    assert top[0].score == max(max(x.home_score, x.away_score) for x in games)
    assert all(m.margin > 0 for m in book["narrowest_win"])
