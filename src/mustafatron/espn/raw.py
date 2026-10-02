"""The parts of ESPN's v3 responses this project reads, as ``TypedDict``s.

These document the raw JSON (as fetched, or as committed under ``data/raw/``) so call sites get
key names checked and completed instead of guessing. They describe only the fields we use; ESPN
sends many more, and older seasons omit some of these, hence ``total=False``. Nothing here
validates at runtime: turning raw JSON into trustworthy objects is the job of
``mustafatron.model``.
"""

from typing import Literal, NotRequired, TypedDict

Winner = Literal["HOME", "AWAY", "TIE", "UNDECIDED"]
PlayoffTier = Literal["NONE", "WINNERS_BRACKET", "WINNERS_CONSOLATION_LADDER", "LOSERS_CONSOLATION_LADDER"]


class RawMember(TypedDict, total=False):
    id: str  # SWID as fetched; m_xxxxxxxxxxxxxxxx once pseudonymized
    displayName: str
    firstName: str
    lastName: str


class RawRecordLine(TypedDict, total=False):
    wins: int
    losses: int
    ties: int
    pointsFor: float
    pointsAgainst: float
    percentage: float
    gamesBack: float
    streakLength: int
    streakType: str


class RawRecord(TypedDict, total=False):
    overall: RawRecordLine
    home: RawRecordLine
    away: RawRecordLine
    division: RawRecordLine


class RawTransactionCounter(TypedDict, total=False):
    acquisitions: int
    drops: int
    trades: int
    moveToActive: int
    moveToIR: int
    acquisitionBudgetSpent: int


class RawTeam(TypedDict, total=False):
    id: int
    name: str
    # Some ESPN responses split the team name instead of sending ``name``.
    location: str
    nickname: str
    abbrev: str
    primaryOwner: str
    owners: list[str]
    record: RawRecord
    points: float  # season total including playoffs
    playoffSeed: int
    rankFinal: int  # always 0 for this league; see rankCalculatedFinal
    rankCalculatedFinal: int
    transactionCounter: RawTransactionCounter


class RawMatchupSide(TypedDict, total=False):
    teamId: int
    totalPoints: float
    pointsByScoringPeriod: dict[str, float]


class RawMatchup(TypedDict):
    id: int
    matchupPeriodId: int
    home: RawMatchupSide
    away: NotRequired[RawMatchupSide]  # absent on a bye
    winner: Winner
    playoffTierType: PlayoffTier


class RawSeason(TypedDict, total=False):
    """One season as returned by the league endpoint, already unwrapped from ``leagueHistory``'s list."""

    id: int
    seasonId: int
    scoringPeriodId: int
    members: list[RawMember]
    teams: list[RawTeam]
    schedule: list[RawMatchup]
    settings: dict
    status: dict
    draftDetail: dict
