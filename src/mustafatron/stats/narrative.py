"""The weekly narrative: each result retold in rivalry context, ported from ``scratch_h2h.py``.

The scratch script's best idea, and the line that makes it read like a broadcast rather than a stat
dump, is computing the series as it stood *before* the game, then the streak *after* it::

    before = [g for g in games if not (g['season'] == season and g['week'] >= last_week)]

Here that is ``PairRecord.before(season, week)`` and ``PairRecord.through(season, week)``: both cut
on (season, week), so a later week can never leak in, and replaying a week of 2018 in 2030 tells it
the way it read at the time. Counting the game in its own "entering" record by accident is the easy
mistake, and ``tests/test_narrative.py`` guards against it.

Prose comes out as plain sentences with managers as ``@[id]`` tokens, which the site turns into
linked names. The notable-flag thresholds (a streak of 3, a .700 series, dead even) are the
``rivalry`` rules in ``data/manual/league_rules.yml``, the same ones the rivalry pages use.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from mustafatron.model import CHAMPIONSHIP_BRACKET, REGULAR_SEASON, Game
from mustafatron.rules import RivalryRules
from mustafatron.stats.h2h import Flag, PairRecord, notable_flags, pair_record

TOKEN = re.compile(r"@\[([^\]]+)\]")
CLOSE = 3.0  # points: "edged"
ROUT = 40.0  # points: "crushed"


def mention(manager_id: str) -> str:
    return f"@[{manager_id}]"


def _score(x: float, y: float) -> str:
    return f"{x:.2f}–{y:.2f}"


def _record(rec: PairRecord) -> str:
    return f"{rec.wins}–{rec.losses}" + (f"–{rec.ties}" if rec.ties else "")


@dataclass(frozen=True)
class Recap:
    """One game of the week, from the winner's side (the home team's on a tie)."""

    game: Game
    before: PairRecord  # the series entering the game
    after: PairRecord  # the series leaving it
    flags: list[Flag]  # notable flags on the series after the game
    text: str

    @property
    def first_meeting(self) -> bool:
        return self.before.games == 0


def recap(games: Iterable[Game], game: Game, rules: RivalryRules, label: str = "") -> Recap:
    """Retell ``game`` against the series history. ``label`` names a playoff round ("Semifinals")."""
    me = game.winner_id or game.home_id
    them = game.opponent_of(me)
    series = pair_record(games, me, them)
    before = series.before(game.season, game.week)
    after = series.through(game.season, game.week)
    win, lose = mention(me), mention(them)
    score = _score(game.score_of(me), game.score_of(them))

    # The result
    if game.is_tie:
        lines = [f"{win} and {lose} tied {score}{_stage(game, label)}."]
    elif game.is_championship_bracket and label == "Championship":
        lines = [f"{win} won the title, beating {lose} {score}."]
    elif game.margin == 0:  # a tied score ESPN broke (2017's 154-154 playoff game)
        lines = [f"{win} beat {lose} on ESPN's tiebreaker after a {score} tie{_stage(game, label)}."]
    else:
        verb = "edged" if game.margin < CLOSE else "crushed" if game.margin >= ROUT else "beat"
        lines = [f"{win} {verb} {lose} {score}{_stage(game, label)}."]

    # The series: entering the game, and where it stands now
    if before.games == 0:
        lines.append("It was their first meeting.")
    elif before.wins == before.losses:
        lines.append(
            f"The series stays even at {_record(after)}."
            if game.is_tie
            else f"The series was even at {_record(before)} going in; {win} now leads {_record(after)}."
        )
    elif before.wins > before.losses:
        lines.append(f"{win} now leads the series {_record(after)}.")
    elif after.wins == after.losses:
        lines.append(f"That evens the series at {_record(after)}.")
    else:
        lines.append(f"{lose} still leads the series {_record(after.flipped())}.")

    # The streak, after the game
    now, was = after.current_streak, before.current_streak
    if now.holder == me and now.length >= 2:
        record_run = now.length >= rules.streak and now.length > before.longest_streak(me)
        record_run = record_run and after.longest_streak(me) > after.longest_streak(them)
        lines.append(
            f"{win} has won {now.length} straight against {lose}"
            + (", the longest run either way in this series." if record_run else ".")
        )
    elif now.holder == me and was.holder == them and was.length >= 2:
        lines.append(f"That snapped {lose}'s {was.length}-game winning streak in the series.")

    # Playoff history
    if game.is_championship_bracket and before.games:
        met = sum(m.playoff for m in before.meetings)
        if met:
            won = sum(m.playoff and m.result == "W" for m in before.meetings)
            lines.append(f"Their {_nth(met + 1)} playoff meeting; {_split(win, lose, won, met)}.")
        else:
            lines.append("Their first meeting in the playoffs.")

    return Recap(game, before, after, notable_flags(after, rules), " ".join(lines))


def _stage(game: Game, label: str) -> str:
    if game.tier == REGULAR_SEASON:
        return ""
    if game.tier == CHAMPIONSHIP_BRACKET:
        return f" in the {label.lower()}" if label else " in the playoffs"
    if game.tier == "WINNERS_CONSOLATION_LADDER":
        return " in the 3rd place game"
    return " in the consolation bracket"


def _split(win: str, lose: str, won: int, of: int) -> str:
    """Who won the earlier meetings: "@[a] won both", "@[b] won all 3", "they split 2"."""
    every = "both" if of == 2 else f"all {of}" if of > 2 else "it"
    if won == of:
        return f"{win} won {every} before"
    if won == 0:
        return f"{lose} won {every} before"
    return f"they had split {won}–{of - won} before" if won * 2 == of else f"{win} had won {won} of {of}"


def _nth(n: int) -> str:
    return {2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(n, f"{n}th")


@dataclass(frozen=True)
class Headline:
    key: str  # high_score, low_score, closest, blowout
    text: str


def headlines(week_games: list[Game]) -> list[Headline]:
    """The week at a glance: its high and low scores, closest game and biggest blowout."""
    games = [g for g in week_games if g.final]
    if not games:
        return []
    sides = [(g.score_of(m), m) for g in games for m in (g.home_id, g.away_id)]
    hi, lo = max(sides), min(sides)
    close = min(games, key=lambda g: (g.margin, g.home_id))
    blow = max(games, key=lambda g: (g.margin, g.home_id))

    def pair(g: Game) -> str:
        w = g.winner_id or g.home_id
        o = g.opponent_of(w)
        return f"{mention(w)} over {mention(o)}, {_score(g.score_of(w), g.score_of(o))}"

    out = [
        Headline("high_score", f"High score: {mention(hi[1])}, {hi[0]:.2f}."),
        Headline("low_score", f"Low score: {mention(lo[1])}, {lo[0]:.2f}."),
    ]
    if len(games) > 1:
        by = "on ESPN's tiebreaker" if close.margin == 0 else f"by {close.margin:.2f}"
        out.append(Headline("closest", f"Closest game: {pair(close)}, {by}."))
        out.append(Headline("blowout", f"Biggest blowout: {pair(blow)}, by {blow.margin:.2f}."))
    return out
