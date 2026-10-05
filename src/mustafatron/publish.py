"""Publish the site's JSON: the entity model → the files in ``mustafatron.contract`` → ``web/public/data/``.

    uv run mustafatron publish                 # all seasons, the current one live from ESPN
    uv run mustafatron publish --offline       # finished seasons only, from data/raw/ (no cookies)
    uv run mustafatron publish --offline --check   # what CI runs: build, validate, schema up to date

The output is generated, never committed (``web/public/data/`` is gitignored); CI builds it.
"""

import json
import shutil
import tempfile
from pathlib import Path

from mustafatron import contract as c
from mustafatron.espn.cache import SeasonCache
from mustafatron.model import Game, League, Season
from mustafatron.rules import LeagueRules, load_rules
from mustafatron.stats.allplay import Luck, career_luck, luckiest_seasons, season_luck
from mustafatron.stats.awards import award_history
from mustafatron.stats.coaching import CoachingLine, coaching_book
from mustafatron.stats.draft import DraftClass, PickValue, draft_book
from mustafatron.stats.h2h import Meeting, all_pairs, notable_flags, rivalries
from mustafatron.stats.lineup import TeamWeek
from mustafatron.stats.narrative import Recap, headlines, recap
from mustafatron.stats.profiles import best_and_worst_weeks, career_all_play
from mustafatron.stats.records import records_book
from mustafatron.stats.seasons import all_play, superlatives, week_scores
from mustafatron.stats.standings import all_time_standings, championship_ledger
from mustafatron.stats.trades import Trade, trade_book
from mustafatron.stats.weekly import (
    Form,
    MissedStart,
    Preview,
    ReportWeek,
    all_play_through,
    coaching_through,
    draft_through,
    games_in,
    preview_week,
    previews,
    report_weeks,
    standings_through,
    week_label,
)
from mustafatron.transform import load_league

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "web" / "public" / "data"
SCHEMA_DIR = REPO / "schema"


def game_row(g: Game) -> c.GameRow:
    return (
        g.season,
        g.week,
        c.TIERS.index(g.tier),
        g.home_id,
        g.away_id,
        g.home_score,
        g.away_score,
        g.winner_id,
    )


def _meeting(m: Meeting) -> c.MeetingOut:
    return c.MeetingOut(season=m.season, week=m.week, score=m.score, opponent_score=m.opponent_score)


def _week_status(season: Season) -> tuple[int | None, int | None]:
    """(last week with every game final, first week with a game still to play)."""
    weeks = sorted({g.week for g in season.games})
    done = [w for w in weeks if all(g.final for g in season.games if g.week == w)]
    todo = [w for w in weeks if w not in done]
    return (max(done) if done else None), (min(todo) if todo else None)


def build(league: League, rules: LeagueRules) -> dict[str, c.ContractFile]:
    """Every published file, keyed by its path under the output directory."""
    seasons = sorted(league.seasons)
    current = league.seasons[seasons[-1]]
    last_done, upcoming_week = _week_status(current)
    out: dict[str, c.ContractFile] = {}

    out["meta.json"] = c.Meta(
        league_name=current.settings.name,
        seasons=seasons,
        current_season=current.season,
        current_season_finished=current.finished,
        last_completed_week=last_done,
        upcoming_week=upcoming_week,
    )

    played: dict[str, list[int]] = {}
    for s in league.seasons.values():
        for t in s.teams:
            played.setdefault(t.manager_id, []).append(s.season)
    out["managers.json"] = c.ManagersFile(
        managers=[
            c.ManagerOut(
                id=m.id,
                name=m.name,
                short_name=m.short_name,
                first_season=m.first_season,
                last_season=m.last_season,
                seasons=played[m.id],
            )
            for m in league.managers_with_games()
        ]
    )

    out["games.json"] = c.GamesFile(
        games=[game_row(g) for g in league.games],
        upcoming=[(g.season, g.week, g.home_id, g.away_id) for g in current.games if g.week == upcoming_week],
    )

    pairs = all_pairs(league.games)
    out["h2h.json"] = c.H2HFile(
        pairs=[
            c.PairOut(
                a=p.a,
                b=p.b,
                games=p.games,
                wins=p.wins,
                losses=p.losses,
                ties=p.ties,
                points_for=p.points_for,
                points_against=p.points_against,
                playoff_wins=p.playoff_wins,
                playoff_losses=p.playoff_losses,
                results=p.results,
                win_pct=round(p.win_pct, 4),
                avg_score=p.avg_score,
                avg_opponent_score=p.avg_opponent_score,
                avg_margin=p.avg_margin,
                last_five=p.last(5),
                current_streak=c.StreakOut(holder=p.current_streak.holder, length=p.current_streak.length),
                longest_streak_a=p.longest_streak(p.a),
                longest_streak_b=p.longest_streak(p.b),
                last_meeting=_meeting(p.meetings[-1]),
                closest=_meeting(p.closest),
                blowout=_meeting(p.blowout),
                rivalry=p.games >= rules.rivalry.min_matchups,
                flags=[
                    c.FlagOut(kind=f.kind, holder=f.holder, wins=f.wins, losses=f.losses)  # type: ignore[arg-type]
                    for f in notable_flags(p, rules.rivalry)
                ],
            )
            for p in pairs.values()
        ],
        most_competitive=[(p.a, p.b) for p in rivalries(pairs, rules.rivalry)],
    )

    out["standings.json"] = c.StandingsFile(
        standings=[
            c.CareerOut(
                manager=s.manager_id,
                seasons=s.seasons,
                finished_seasons=s.finished_seasons,
                wins=s.wins,
                losses=s.losses,
                ties=s.ties,
                win_pct=round(s.win_pct, 4),
                points_for=s.points_for,
                points_against=s.points_against,
                avg_margin=round(s.avg_margin, 2),
                playoff_appearances=s.playoff_appearances,
                playoff_wins=s.playoff_wins,
                playoff_losses=s.playoff_losses,
                playoff_points_for=s.playoff_points_for,
                playoff_points_against=s.playoff_points_against,
                championships=s.championships,
                runner_ups=s.runner_ups,
                third_places=s.third_places,
                last_places=s.last_places,
                best_finish=s.best_finish,
                worst_finish=s.worst_finish,
                avg_finish=s.avg_finish,
                net_payout=s.net_payout,
                roi=round(s.roi, 4),
            )
            for s in all_time_standings(league, rules)
        ],
        ledger=[c.LedgerOut(**vars(e)) for e in championship_ledger(league)],
    )

    book = records_book(league)
    out["records.json"] = c.RecordsFile(
        game_records={
            k: [
                c.GameMarkOut(
                    season=m.season,
                    week=m.week,
                    manager=m.manager_id,
                    opponent=m.opponent_id,
                    score=m.score,
                    opponent_score=m.opponent_score,
                    playoff=m.playoff,
                )
                for m in v
            ]
            for k, v in book.game.items()
        },
        matchup_records={
            k: [
                c.MatchupMarkOut(
                    season=m.season,
                    week=m.week,
                    home=m.home_id,
                    away=m.away_id,
                    home_score=m.home_score,
                    away_score=m.away_score,
                    total=m.total,
                    playoff=m.playoff,
                )
                for m in v
            ]
            for k, v in book.matchup.items()
        },
        season_records={
            k: [
                c.SeasonMarkOut(
                    season=m.season,
                    manager=m.manager_id,
                    value=m.value,
                    wins=m.wins,
                    losses=m.losses,
                    ties=m.ties,
                    points_for=m.points_for,
                )
                for m in v
            ]
            for k, v in book.season.items()
        },
        streak_records={
            k: [
                c.StreakMarkOut(
                    manager=m.manager_id,
                    length=m.length,
                    start_season=m.start_season,
                    start_week=m.start_week,
                    end_season=m.end_season,
                    end_week=m.end_week,
                    active=m.active,
                )
                for m in v
            ]
            for k, v in book.streak.items()
        },
        week_records={
            k: [c.WeekMarkOut(season=m.season, period=m.period, total=m.total, teams=m.teams) for m in v]
            for k, v in book.week.items()
        },
        extremes_records={
            k: [
                c.ExtremeMarkOut(season=m.season, manager=m.manager_id, count=m.count, weeks=m.weeks)
                for m in v
            ]
            for k, v in book.extremes.items()
        },
    )

    lucky, unlucky = luckiest_seasons(league)
    out["luck.json"] = c.LuckFile(
        careers=[c.CareerLuckOut(**_luck(x), seasons=x.seasons) for x in career_luck(league)],
        seasons=[_season_luck(x) for x in season_luck(league)],
        luckiest=[_season_luck(x) for x in lucky],
        unluckiest=[_season_luck(x) for x in unlucky],
    )

    book = coaching_book(league)
    out["coaching.json"] = c.CoachingFile(
        first_season=book.first_season,
        careers=[c.CareerCoachingOut(**_coaching(x), seasons=x.seasons) for x in book.careers],
        seasons=[c.SeasonCoachingOut(**_coaching(x), season=x.season) for x in book.seasons],
        worst_weeks=[_coaching_week(league, w) for w in book.worst_weeks],
        best_weeks=[_coaching_week(league, w) for w in book.best_weeks],
        if_only=[
            c.IfOnlyOut(
                season=x.game.season,
                week=x.game.week,
                tier=x.game.tier,
                manager=x.manager_id,
                opponent=x.game.opponent_of(x.manager_id),
                score=x.score,
                opponent_score=x.opponent_score,
                optimal=x.optimal,
                left_on_bench=x.left_on_bench,
                weeks=[_coaching_week(league, w) for w in x.weeks],
            )
            for x in book.if_only
        ],
    )

    drafts = draft_book(league, rules.draft_review)
    out["draft.json"] = c.DraftFile(
        first_season=drafts.first_season,
        early_rounds=drafts.early_rounds,
        steals_after_round=rules.draft_review.steals_after_round,
        busts_through_round=rules.draft_review.busts_through_round,
        drafters=[
            c.DrafterOut(
                manager=d.manager_id,
                seasons=d.seasons,
                picks=d.picks,
                value=d.value,
                per_pick=round(d.per_pick, 2),
                early_picks=d.early_picks,
                early_per_pick=round(d.early_per_pick, 2),
                late_picks=d.late_picks,
                late_per_pick=round(d.late_per_pick, 2),
            )
            for d in drafts.drafters
        ],
        steals=[_pick(p) for p in drafts.steals],
        busts=[_pick(p) for p in drafts.busts],
        best_drafts=[_draft_class(d) for d in drafts.best_drafts],
        worst_drafts=[_draft_class(d) for d in drafts.worst_drafts],
        rounds=[
            c.RoundOut(
                round=r.round, picks=r.picks, avg_points=r.avg_points, by_manager=r.avg_value_by_manager
            )
            for r in drafts.rounds
        ],
    )

    tb = trade_book(league)
    out["trades.json"] = c.TradesFile(
        first_season=tb.first_season,
        trades=[_trade(league, t) for t in tb.trades],
        best=[c.TradeSideRefOut(trade=t.id, manager=side.manager_id) for t, side in tb.best],
        worst=[c.TradeSideRefOut(trade=t.id, manager=side.manager_id) for t, side in tb.worst],
        lopsided=[t.id for t in tb.lopsided],
        counts=[
            c.TradeCountOut(
                season=x.season, manager=x.manager_id, trades=x.trades, acquisitions=x.acquisitions
            )
            for x in tb.counts
        ],
    )

    out["awards.json"] = c.AwardsFile(
        awards=[
            c.AwardOut(
                id=a.id,
                name=a.name,
                description=a.description,
                status=a.status,  # type: ignore[arg-type]
                since=a.since,
                winners=[
                    c.AwardWinnerOut(
                        season=r.season,
                        source=r.source,
                        manager=r.winner.manager_id if r.winner else None,
                        value=r.winner.value if r.winner else None,
                        detail=r.winner.detail if r.winner else "",
                    )
                    for r in award_history(league, a)
                ],
            )
            for a in rules.awards
        ]
    )

    out["profiles.json"] = c.ProfilesFile(
        profiles=[_profile(league, m.id) for m in league.managers_with_games()]
    )

    for s in league.seasons.values():
        out[f"seasons/{s.season}.json"] = c.SeasonFile(
            season=s.season,
            finished=s.finished,
            champion=s.champion_id if s.finished else None,
            settings=c.SeasonSettingsOut(
                team_count=s.settings.team_count,
                regular_season_weeks=s.settings.regular_season_matchups,
                final_week=s.settings.final_matchup_period,
                playoff_team_count=s.settings.playoff_team_count,
                points_per_reception=s.settings.points_per_reception,
            ),
            teams=[
                c.TeamOut(
                    manager=t.manager_id,
                    team_id=t.team_id,
                    name=t.name,
                    abbrev=t.abbrev,
                    wins=t.wins,
                    losses=t.losses,
                    ties=t.ties,
                    points_for=t.points_for,
                    points_against=t.points_against,
                    playoff_seed=t.playoff_seed,
                    final_rank=t.final_rank,
                    acquisitions=t.acquisitions,
                    trades=t.trades,
                    co_managers=list(t.co_manager_ids),
                )
                for t in s.teams
            ],
            games=[game_row(g) for g in s.games],
            **_season_detail(s),
        )

    reports = [w for s in league.seasons.values() for w in report_weeks(s)]
    in_progress = [w for w in reports if w.season == current.season and not current.finished]
    out["weeks.json"] = c.WeeksFile(
        weeks=[_week_ref(w) for w in reports],
        current=_week_ref(in_progress[-1]) if in_progress else None,
    )
    for w in reports:
        out[f"weeks/{w.season}/{w.week}.json"] = week_file(league, w, rules)
    return out


def _week_ref(w: ReportWeek) -> c.WeekRefOut:
    return c.WeekRefOut(season=w.season, week=w.week, label=w.label, playoff=w.playoff)


def week_file(league: League, w: ReportWeek, rules: LeagueRules) -> c.WeekFile:
    s = league.seasons[w.season]
    return c.WeekFile(
        season=w.season,
        week=w.week,
        label=w.label,
        playoff=w.playoff,
        periods=list(w.periods),
        games=[game_row(g) for g in games_in(s, w.week)],
        recaps=[_recap(recap(league.games, g, rules.rivalry, w.label)) for g in games_in(s, w.week)],
        headlines=[h.text for h in headlines(games_in(s, w.week))],
        standings=[
            c.StandingLineOut(
                manager=x.manager_id,
                wins=x.wins,
                losses=x.losses,
                ties=x.ties,
                points_for=x.points_for,
                points_against=x.points_against,
            )
            for x in standings_through(s, w.week)
        ],
        all_play=_all_play_grid(s, w.week),
        coaching=_week_coaching(league, s, w.week),
        draft=_week_draft(s, w.week, rules),
        preview_week=(nxt := preview_week(s, w.week)),
        preview_label=week_label(s.settings, nxt) if nxt else None,
        previews=[_preview(x) for x in previews(league, s, w.week, rules.rivalry)],
    )


def _form(f: Form) -> c.FormOut:
    return c.FormOut(
        manager=f.manager_id,
        rank=f.rank,
        wins=f.line.wins,
        losses=f.line.losses,
        ties=f.line.ties,
        points_for=f.line.points_for,
        last=f.last,
        all_play_pct=round(f.all_play.win_pct, 4),
    )


def _preview(p: Preview) -> c.PreviewOut:
    s = p.series
    met = bool(s.meetings)
    return c.PreviewOut(
        home=p.game.home_id,
        away=p.game.away_id,
        tier=p.game.tier,
        games=s.games,
        wins=s.wins,
        losses=s.losses,
        ties=s.ties,
        streak=c.StreakOut(holder=s.current_streak.holder, length=s.current_streak.length),
        last_meeting=_meeting(s.meetings[-1]) if met else None,
        closest=_meeting(s.closest) if met else None,
        blowout=_meeting(s.blowout) if met else None,
        flags=[c.FlagOut(kind=f.kind, holder=f.holder, wins=f.wins, losses=f.losses) for f in p.flags],  # type: ignore[arg-type]
        home_form=_form(p.home),
        away_form=_form(p.away),
    )


def _recap(r: Recap) -> c.RecapOut:
    streak = r.after.current_streak
    return c.RecapOut(
        home=r.game.home_id,
        away=r.game.away_id,
        text=r.text,
        first_meeting=r.first_meeting,
        manager=r.after.a,
        wins=r.after.wins,
        losses=r.after.losses,
        ties=r.after.ties,
        streak=c.StreakOut(holder=streak.holder, length=streak.length),
        flags=[c.FlagOut(kind=f.kind, holder=f.holder, wins=f.wins, losses=f.losses) for f in r.flags],  # type: ignore[arg-type]
    )


def _week_draft(s: Season, week: int, rules: LeagueRules) -> c.WeekDraftOut | None:
    d = draft_through(s, week, rules.draft_review)
    if d is None:
        return None
    return c.WeekDraftOut(
        steals_after_round=rules.draft_review.steals_after_round,
        busts_through_round=rules.draft_review.busts_through_round,
        intercept=round(d.line.intercept, 4),
        slope=round(d.line.slope, 4),
        picks=[_pick(p) for p in sorted(d.line.picks, key=lambda p: p.overall_pick)],
        steals=[_pick(p) for p in d.steals],
        busts=[_pick(p) for p in d.busts],
    )


def _week_coaching(league: League, s: Season, week: int) -> c.WeekCoachingOut | None:
    book = coaching_through(s, week)
    if book is None:
        return None

    def ref(pid: int | None, w: TeamWeek) -> c.PlayerPointsOut | None:
        return None if pid is None else _player_points(league, s.season, pid, w.points[pid])

    def miss(x: MissedStart) -> c.MissedStartOut:
        p = s.players.get(x.player_id)
        return c.MissedStartOut(
            manager=x.manager_id,
            player=p.name if p else str(x.player_id),
            position=p.position if p else "?",
            weeks=x.weeks,
            gain=x.gain,
        )

    return c.WeekCoachingOut(
        bench=[
            c.BenchLineOut(
                manager=b.manager_id,
                weeks=len(b.weeks),
                left_on_bench=b.left_on_bench,
                substitutions=b.substitutions,
                perfect_weeks=b.perfect_weeks,
                detail=[
                    c.BenchWeekOut(
                        period=w.period,
                        actual=w.actual,
                        optimal=w.optimal,
                        left_on_bench=w.left_on_bench,
                        swaps=[
                            c.SwapOut(
                                player_in=ref(x.player_in, w), player_out=ref(x.player_out, w), gain=x.gain
                            )
                            for x in w.swaps
                        ],
                    )
                    for w in sorted(b.weeks, key=lambda w: (-w.left_on_bench, w.period))
                    if not w.perfect
                ],
            )
            for b in book.bench
        ],
        if_only=[miss(x) for x in book.if_only],
        by_manager={m: [miss(x) for x in xs] for m, xs in book.by_manager.items()},
    )


def _all_play_grid(s: Season, week: int) -> c.AllPlayGridOut:
    periods, rows = all_play_through(s, week)
    return c.AllPlayGridOut(
        periods=periods,
        rows=[
            c.AllPlayRowOut(
                **_luck(r.luck),
                cells=[
                    c.AllPlayCellOut(
                        points=x.points,
                        opponent=x.opponent_id,
                        opponent_points=x.opponent_points,
                        result=x.result,  # type: ignore[arg-type]
                        rank=x.rank,
                        wins=x.all_play.wins,
                        losses=x.all_play.losses,
                        ties=x.all_play.ties,
                    )
                    if (x := r.cells.get(p))
                    else None
                    for p in periods
                ],
            )
            for r in rows
        ],
    )


def _pick(p: PickValue) -> c.PickValueOut:
    return c.PickValueOut(
        season=p.season,
        round=p.round,
        round_pick=p.round_pick,
        overall_pick=p.overall_pick,
        manager=p.manager_id,
        player=p.player,
        position=p.position,
        points=p.points,
        points_above_avg=p.points_above_avg,
        expected=p.expected,
        value=p.value,
    )


def _trade(league: League, t: Trade) -> c.TradeOut:
    players = league.seasons[t.season].players

    def refs(ids: tuple[int, ...]) -> list[c.PlayerRefOut]:
        return [
            c.PlayerRefOut(name=players[p].name, position=players[p].position)
            if p in players
            else c.PlayerRefOut(name=str(p), position="?")
            for p in ids
        ]

    return c.TradeOut(
        id=t.id,
        season=t.season,
        period=t.period,
        date=t.date,
        sides=[
            c.TradeSideOut(
                manager=s.manager_id,
                received=refs(s.players_in),
                sent=refs(s.players_out),
                value=s.value,
                weeks=s.weeks,
            )
            for s in t.sides
        ],
        winner=t.winner.manager_id,
        margin=t.margin,
    )


def _draft_class(d: DraftClass) -> c.DraftClassOut:
    return c.DraftClassOut(
        season=d.season, manager=d.manager_id, picks=d.picks, value=d.value, best=_pick(d.best)
    )


def _coaching(x: CoachingLine) -> dict:
    return dict(
        manager=x.manager_id,
        weeks=x.weeks,
        actual=x.actual,
        optimal=x.optimal,
        left_on_bench=x.left_on_bench,
        per_week=round(x.per_week, 2),
        efficiency=round(x.efficiency, 4),
        perfect_weeks=x.perfect_weeks,
        substitutions=x.substitutions,
    )


def _player_points(league: League, season: int, player_id: int, points: float) -> c.PlayerPointsOut:
    p = league.seasons[season].players.get(player_id)
    return c.PlayerPointsOut(
        name=p.name if p else str(player_id), position=p.position if p else "?", points=points
    )


def _coaching_week(league: League, w: TeamWeek) -> c.CoachingWeekOut:
    return c.CoachingWeekOut(
        season=w.season,
        period=w.period,
        manager=w.manager_id,
        actual=w.actual,
        optimal=w.optimal,
        left_on_bench=w.left_on_bench,
        substitutions=w.substitutions,
        should_have_started=[_player_points(league, w.season, p, w.points[p]) for p in w.should_have_started],
        should_have_sat=[_player_points(league, w.season, p, w.points[p]) for p in w.should_have_sat],
    )


def _luck(x: Luck) -> dict:
    return dict(
        manager=x.manager_id,
        wins=x.wins,
        losses=x.losses,
        ties=x.ties,
        win_pct=round(x.win_pct, 4),
        all_play_wins=x.all_play.wins,
        all_play_losses=x.all_play.losses,
        all_play_ties=x.all_play.ties,
        all_play_pct=round(x.all_play.win_pct, 4),
        luck=round(x.luck, 4),
        luck_wins=round(x.luck_wins, 2),
    )


def _season_luck(x) -> c.SeasonLuckOut:
    return c.SeasonLuckOut(**_luck(x), season=x.season, finished=x.finished, final_rank=x.final_rank)


def _profile(league: League, manager_id: str) -> c.ProfileOut:
    best, worst = best_and_worst_weeks(league, manager_id)
    ap = career_all_play(league, manager_id)

    def week(w) -> c.WeekLineOut:
        return c.WeekLineOut(
            season=w.season, period=w.period, points=w.points, opponent=w.opponent_id, result=w.result
        )

    return c.ProfileOut(
        manager=manager_id,
        all_play_wins=ap.wins,
        all_play_losses=ap.losses,
        all_play_ties=ap.ties,
        best_weeks=[week(w) for w in best],
        worst_weeks=[week(w) for w in worst],
    )


def _season_detail(s: Season) -> dict:
    """The week-by-week grid, all-play records and superlatives for a SeasonFile."""
    weeks = week_scores(s)
    periods = sorted({w.period for w in weeks})
    cell = {(w.manager_id, w.period): w for w in weeks}
    ap = all_play(s)
    first_playoff = s.settings.regular_season_matchups + 1
    return dict(
        periods=periods,
        playoff_start_period=(
            s.settings.scoring_periods(first_playoff)[0]
            if first_playoff in s.settings.matchup_periods
            else None
        ),
        weekly=[
            c.WeeklyOut(
                manager=t.manager_id,
                scores=[
                    cell[(t.manager_id, p)].points if (t.manager_id, p) in cell else None for p in periods
                ],
                results="".join(
                    (cell[(t.manager_id, p)].result if (t.manager_id, p) in cell else "") or "-"
                    for p in periods
                ),
                all_play_wins=ap[t.manager_id].wins,
                all_play_losses=ap[t.manager_id].losses,
                all_play_ties=ap[t.manager_id].ties,
            )
            for t in s.teams
        ],
        superlatives=[
            c.SuperlativeOut(key=x.key, manager=x.manager_id, value=x.value, period=x.period)  # type: ignore[arg-type]
            for x in superlatives(s)
        ],
    )


def write(files: dict[str, c.ContractFile], out_dir: Path) -> None:
    """Replace ``out_dir`` with exactly these files (compact JSON, one per path)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for relpath, model in files.items():
        path = out_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json() + "\n", encoding="utf-8")


def validate(out_dir: Path) -> list[str]:
    """Problems found re-reading published files through the contract (empty if all is well)."""
    errors = []
    found = sorted(p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*.json"))
    for name in c.FILES:
        if name not in found:
            errors.append(f"{name}: missing")
    for relpath in found:
        try:
            text = (out_dir / relpath).read_text(encoding="utf-8")
            c.model_for(relpath).model_validate_json(text, strict=True)
        except (KeyError, ValueError) as e:
            errors.append(f"{relpath}: {e}")
    return errors


def schemas() -> dict[str, dict]:
    """JSON Schema for every published file, keyed by schema file name."""
    out = {f"{Path(name).stem}.schema.json": model.model_json_schema() for name, model in c.FILES.items()}
    out["season.schema.json"] = c.SEASON_FILE.model_json_schema()
    out["week.schema.json"] = c.WEEK_FILE.model_json_schema()
    return out


def _dump_schema(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_schemas(schema_dir: Path = SCHEMA_DIR) -> None:
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas().items():
        (schema_dir / name).write_text(_dump_schema(schema), encoding="utf-8", newline="\n")


def stale_schemas(schema_dir: Path = SCHEMA_DIR) -> list[str]:
    """Committed schema files that don't match the contract models."""
    stale = []
    for name, schema in schemas().items():
        path = schema_dir / name
        if not path.exists() or path.read_text(encoding="utf-8").replace("\r\n", "\n") != _dump_schema(
            schema
        ):
            stale.append(name)
    return stale


def publish(out_dir: Path = OUT_DIR, *, offline: bool = False) -> dict[str, c.ContractFile]:
    cache = SeasonCache()
    seasons = None
    if offline:  # only what is committed and finished; needs no ESPN cookies
        seasons = sorted(
            int(p.name) for p in cache.raw_dir.iterdir() if p.is_dir() and cache.is_frozen(int(p.name))
        )
    league = load_league(seasons, cache=cache, player_data=True)
    files = build(league, load_rules())
    write(files, out_dir)
    return files


def check(*, offline: bool = True) -> list[str]:
    """Build into a temp dir and report contract violations and stale schemas (what CI runs)."""
    with tempfile.TemporaryDirectory() as tmp:
        publish(Path(tmp), offline=offline)
        errors = validate(Path(tmp))
    errors += [f"schema/{n} is stale: run `uv run mustafatron schema`" for n in stale_schemas()]
    return errors
