from datetime import UTC, datetime, timedelta, timezone

import pytest

from mustafatron.rules import LeagueRules, load_rules

RULES = load_rules()
ET = timezone(timedelta(hours=-4))  # EDT, for readable September dates


def test_payouts():
    p = RULES.payouts(2025)
    assert [p.for_rank(r) for r in (1, 2, 3, 4, 10)] == [6.5, 2.5, 0.0, -1.0, -1.0]


def test_keeper_eligibility_starts_with_espn_keepers():
    assert RULES.keeper_eligible_after_round(2023) is None
    assert RULES.keeper_eligible_after_round(2024) == RULES.keeper_eligible_after_round(2026) == 3


def test_thresholds():
    assert RULES.history_start == 2015
    assert RULES.rivalry.min_matchups == 5
    assert (RULES.rivalry.streak, RULES.rivalry.lopsided_pct) == (3, 0.70)
    assert (RULES.draft_review.steals_after_round, RULES.draft_review.busts_through_round) == (1, 4)


@pytest.mark.parametrize("season", range(2015, 2027))
def test_every_season_has_a_week_one_kickoff_and_payouts(season):
    kickoff = RULES.week1_kickoff(season).astimezone(ET)
    assert kickoff.tzinfo is not None
    assert kickoff.month == 9 and kickoff.weekday() in (2, 3)  # Wednesday or Thursday night
    assert 19 <= kickoff.hour <= 21
    RULES.payouts(season)


@pytest.mark.parametrize(
    ("when", "week"),
    [
        (datetime(2025, 9, 1, 12, tzinfo=ET), 1),  # preseason
        (datetime(2025, 9, 4, 20, tzinfo=ET), 1),  # just before the opener
        (datetime(2025, 9, 5, 12, tzinfo=ET), 2),  # after it: week 1 has started (Sept 7 said week 1)
        (datetime(2025, 9, 9, 12, tzinfo=ET), 2),
        (datetime(2025, 9, 11, 12, tzinfo=ET), 2),  # Thursday before kickoff (midnight Sept 11 said week 3)
        (datetime(2025, 9, 11, 21, tzinfo=ET), 3),
        (datetime(2025, 12, 30, 12, tzinfo=ET), None),  # after week 17 started
    ],
)
def test_first_week_after_resolves_the_2025_start_date_discrepancy(when, week):
    assert RULES.first_week_after(2025, when) == week


def test_first_week_after_needs_an_aware_datetime():
    with pytest.raises(ValueError):
        RULES.first_week_after(2025, datetime(2025, 9, 9))


def test_season_keyed_rules_pick_the_latest_applicable_entry():
    rules = LeagueRules(
        {
            "history_start": 2015,
            "rivalry": vars(RULES.rivalry),
            "draft_review": vars(RULES.draft_review),
            "nfl_week1_kickoff": {2020: datetime(2020, 9, 11, tzinfo=UTC)},
            "payouts": [
                {"since": 2020, "value": {"by_rank": {1: 8}, "otherwise": -1}},
                {"since": 2015, "value": {"by_rank": {1: 6.5}, "otherwise": -1}},
            ],
            "keepers": [],
        }
    )
    assert rules.payouts(2019).for_rank(1) == 6.5
    assert rules.payouts(2020).for_rank(1) == 8.0
    with pytest.raises(KeyError):
        rules.payouts(2014)
    with pytest.raises(KeyError, match="nfl_week1_kickoff"):
        rules.week1_kickoff(2030)
