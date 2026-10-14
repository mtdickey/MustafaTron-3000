"""Pickup counts and winning FAAB bids; losing bids are not retained by ESPN's cache."""

from collections import defaultdict
from statistics import mean

from mustafatron import contract as c
from mustafatron.espn.player_data import WEEKLY_SINCE
from mustafatron.model import League


def waiver_book(league: League) -> c.WaiversFile:
    detail = sorted(y for y in league.seasons if y >= WEEKLY_SINCE)
    faab = sorted(y for y, s in league.seasons.items() if s.settings.uses_faab)
    rows = []
    purchases = []
    bids = defaultdict(list)
    managers = defaultdict(list)
    for year, season in sorted(league.seasons.items()):
        for team in season.teams:
            moves = [t for t in season.transactions if t.manager_id == team.manager_id and t.players_in]
            waivers = [t for t in moves if t.type == "WAIVER"]
            row = c.WaiverSeasonOut(
                season=year,
                manager=team.manager_id,
                acquisitions=team.acquisitions,
                waiver_wins=len(waivers) if year in detail else None,
                free_agents=sum(len(t.players_in) for t in moves if t.type == "FREEAGENT")
                if year in detail
                else None,
            )
            rows.append(row)
            managers[team.manager_id].append(row)
            if year not in faab:
                continue
            for t in waivers:
                bids[year].append((team.manager_id, t.bid))
                purchases.append(
                    c.WaiverPurchaseOut(
                        season=year,
                        period=t.scoring_period,
                        date=t.date.date().isoformat() if t.date else None,
                        manager=t.manager_id,
                        players=[
                            season.players[p].name if p in season.players else f"Player #{p}"
                            for p in t.players_in
                        ],
                        bid=t.bid,
                        budget_pct=round(100 * t.bid / season.settings.acquisition_budget, 2)
                        if season.settings.acquisition_budget
                        else None,
                    )
                )
    totals = []
    for manager, seasons in managers.items():
        won = [bid for year in faab for owner, bid in bids[year] if owner == manager]
        premiums = []
        for year in faab:
            others = [bid for owner, bid in bids[year] if owner != manager]
            if others:
                baseline = mean(others)
                premiums.extend(bid - baseline for owner, bid in bids[year] if owner == manager)
        total = sum(s.acquisitions for s in seasons)
        totals.append(
            c.WaiverManagerOut(
                manager=manager,
                seasons=len(seasons),
                acquisitions=total,
                per_season=round(total / len(seasons), 2),
                waiver_wins=sum(s.waiver_wins or 0 for s in seasons),
                detail_seasons=sum(s.waiver_wins is not None for s in seasons),
                waivers_per_season=round(
                    sum(s.waiver_wins or 0 for s in seasons)
                    / sum(s.waiver_wins is not None for s in seasons),
                    2,
                )
                if any(s.waiver_wins is not None for s in seasons)
                else None,
                free_agents=sum(s.free_agents or 0 for s in seasons),
                faab_wins=len(won),
                spent=sum(won),
                average_bid=round(mean(won), 2) if won else None,
                premium=round(mean(premiums), 2) if premiums else None,
            )
        )
    return c.WaiversFile(
        detail_seasons=detail,
        faab_seasons=faab,
        managers=sorted(totals, key=lambda t: (-t.acquisitions, t.manager)),
        seasons=rows,
        expensive=sorted(purchases, key=lambda p: (-p.bid, p.season, p.date or "", p.manager))[:25],
    )
