"""Scratch: all-time head-to-head records + rivalry notes for the default league.

Usage:  python scratch_h2h.py [--season 2026] [--week 4] [--start 2015] [--no-playoffs]

--week is the upcoming week; the week just played is --week - 1.
Raw ESPN API calls (requests only). Managers are keyed by pseudonymized owner SWID
(see mustafatron.pseudonymize), so team renames don't matter. Seasons load through
mustafatron.espn.cache: finished ones from data/raw/, only the season in progress from ESPN.
"""
import argparse
import json
from collections import defaultdict

from mustafatron.espn import SeasonNotFoundError
from mustafatron.espn.cache import SeasonCache
from mustafatron.rules import load_rules

CACHE = SeasonCache()
RULES = load_rules()


def fetch_season(year, current_year):
    """Return dict(members, teams, schedule): from data/raw/ if finished, else live from ESPN."""
    try:
        return CACHE.load(year)
    except SeasonNotFoundError:
        return None


def clean(s):
    return ' '.join(s.split()).title()


def build_games(start, current_year, include_playoffs):
    """Flat list of completed games between manager SWIDs + upcoming games + names."""
    names, games, upcoming = {}, [], defaultdict(list)
    seasons = []
    for year in range(start, current_year + 1):
        d = fetch_season(year, current_year)
        if not d or not d['schedule']:
            print(f'  {year}: no data (league may not exist / no access)')
            continue
        seasons.append(year)
        swid_name = {m['id']: clean(f"{m.get('firstName', '')} {m.get('lastName', '')}") for m in d['members']}
        team_owner = {}
        for t in d['teams']:
            owner = t.get('primaryOwner') or (t.get('owners') or [None])[0]
            team_owner[t['id']] = owner
            names[owner] = swid_name.get(owner, owner)
        for m in d['schedule']:
            if 'away' not in m:  # bye
                continue
            is_playoff = m.get('playoffTierType', 'NONE') != 'NONE'
            h, a = m['home'], m['away']
            ho, ao = team_owner.get(h['teamId']), team_owner.get(a['teamId'])
            g = dict(season=year, week=m['matchupPeriodId'], playoff=is_playoff, a=ho, b=ao,
                     pa=h.get('totalPoints', 0), pb=a.get('totalPoints', 0), winner=m.get('winner'))
            if g['winner'] in ('HOME', 'AWAY', 'TIE') and (g['pa'] or g['pb']):
                if include_playoffs or not is_playoff:
                    games.append(g)
            else:
                upcoming[(year, g['week'])].append(g)
    print(f'Loaded seasons: {seasons}')
    games.sort(key=lambda g: (g['season'], g['week']))
    return names, games, upcoming


def pair_games(games, x, y):
    """Games between x and y oriented from x's perspective: (season, week, x_pts, y_pts, playoff)."""
    out = []
    for g in games:
        if (g['a'], g['b']) == (x, y):
            out.append((g['season'], g['week'], g['pa'], g['pb'], g['playoff']))
        elif (g['a'], g['b']) == (y, x):
            out.append((g['season'], g['week'], g['pb'], g['pa'], g['playoff']))
    return out


def result(xp, yp):
    return 'W' if xp > yp else 'L' if xp < yp else 'T'


def streaks(results):
    """(current streak as (char, n), longest win streak for x, longest win streak for y)."""
    cur, n = (results[-1], 0) if results else ('-', 0)
    for r in reversed(results):
        if r == cur:
            n += 1
        else:
            break
    def longest(ch):
        best = run = 0
        for r in results:
            run = run + 1 if r == ch else 0
            best = max(best, run)
        return best
    return (cur, n), longest('W'), longest('L')


def describe_pair(names, games, x, y, label_week=None):
    gs = pair_games(games, x, y)
    nx, ny = names[x], names[y]
    if not gs:
        return [f'{nx} vs {ny}: no prior meetings on record.']
    res = [result(a, b) for _, _, a, b, _ in gs]
    w, l, t = res.count('W'), res.count('L'), res.count('T')
    pf, pa = sum(g[2] for g in gs), sum(g[3] for g in gs)
    (cch, cn), x_best, y_best = streaks(res)
    cur_owner = nx if cch == 'W' else ny if cch == 'L' else 'Ties'
    margins = [(abs(a - b), s, wk, a, b) for s, wk, a, b, _ in gs]
    close, blow = min(margins), max(margins)
    lines = [f'{nx} vs {ny}: {w}-{l}' + (f'-{t}' if t else '') + f' all-time in {len(gs)} meetings '
             f'(avg score {pf / len(gs):.1f}-{pa / len(gs):.1f}, avg margin {(pf - pa) / len(gs):+.1f} for {nx})']
    lines.append(f'   current streak: {cur_owner} {cn} straight' if cch != 'T' else '   last meeting was a tie')
    lines.append(f'   longest streaks: {nx} {x_best}, {ny} {y_best}')
    lines.append(f'   last 5 (oldest→newest, from {nx}): ' + ' '.join(res[-5:]))
    s, wk, a, b, _ = gs[-1][0], gs[-1][1], gs[-1][2], gs[-1][3], 0
    lines.append(f'   last meeting: {s} wk{wk}, {a:.1f}-{b:.1f}')
    lines.append(f'   closest: {close[0]:.2f} pts ({close[1]} wk{close[2]}); biggest blowout: {blow[0]:.1f} pts ({blow[1]} wk{blow[2]})')
    po = [g for g in gs if g[4]]
    if po:
        pr = [result(g[2], g[3]) for g in po]
        lines.append(f'   playoff meetings: {nx} {pr.count("W")}-{pr.count("L")}')
    return lines


def notable_flags(names, games, x, y):
    """Short list of 'headline' items for a pair; empty if nothing notable."""
    gs = pair_games(games, x, y)
    r = RULES.rivalry
    if len(gs) < r.notable_min_games:
        return []
    res = [result(a, b) for _, _, a, b, _ in gs]
    (cch, cn), _, _ = streaks(res)
    w, l = res.count('W'), res.count('L')
    flags = []
    if cch != 'T' and cn >= r.streak:
        flags.append(f'{names[x] if cch == "W" else names[y]} has won {cn} straight')
    if max(w, l) / len(gs) >= r.lopsided_pct:
        flags.append(f'lopsided series ({max(w, l)}-{min(w, l)})')
    if abs(w - l) <= r.dead_even_max_diff and len(gs) >= r.dead_even_min_games:
        flags.append('dead-even rivalry')
    return flags


def print_table(names, games):
    ids = sorted(names, key=lambda k: names[k])
    # only managers who actually played games
    active = [i for i in ids if any(g['a'] == i or g['b'] == i for g in games)]
    short = {i: names[i].split()[0][:9] + (names[i].split()[-1][0] if len(names[i].split()) > 1 else '') for i in active}
    print('\n=== All-time H2H matrix (row manager\'s record vs column manager) ===')
    print(' ' * 12 + ''.join(f'{short[c]:>11}' for c in active))
    for r in active:
        row = f'{short[r]:<12}'
        for c in active:
            if r == c:
                row += f'{"--":>11}'
                continue
            res = [result(a, b) for _, _, a, b, _ in pair_games(games, r, c)]
            row += f'{(f"{res.count(chr(87))}-{res.count(chr(76))}" + (f"-{res.count(chr(84))}" if "T" in res else "")) if res else ".":>11}'
        print(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--week', type=int, default=4, help='upcoming week; last week = week-1')
    ap.add_argument('--start', type=int, default=RULES.history_start)
    ap.add_argument('--no-playoffs', action='store_true')
    ap.add_argument('--export', help='write raw games as JSON to this path and exit')
    args = ap.parse_args()

    names, games, upcoming = build_games(args.start, args.season, not args.no_playoffs)
    print(f'{len(games)} completed games, {len(names)} managers')
    if args.export:
        up = upcoming.get((args.season, args.week), [])
        payload = dict(
            managers={i: names[i] for i in names if any(g['a'] == i or g['b'] == i for g in games)},
            games=[[g['season'], g['week'], int(g['playoff']), g['a'], g['b'], g['pa'], g['pb']] for g in games],
            upcoming=[[g['a'], g['b']] for g in up], upcoming_week=args.week, season=args.season)
        with open(args.export, 'w') as f:
            json.dump(payload, f)
        print(f'exported to {args.export}')
        return
    print_table(names, games)

    last_week = args.week - 1
    # History *before* last week, so streaks/"entering" context is separate from the result itself
    played = [g for g in games if g['season'] == args.season and g['week'] == last_week]
    before = [g for g in games if not (g['season'] == args.season and g['week'] >= last_week)]

    print(f'\n=== Week {last_week}, {args.season}: results in H2H context ===')
    for g in played:
        x, y = g['a'], g['b']
        print(f'\n{names[x]} {g["pa"]:.1f} - {g["pb"]:.1f} {names[y]}')
        print('  BEFORE this game:')
        for ln in describe_pair(names, before, x, y):
            print('  ' + ln)
        after_res = [result(a, b) for _, _, a, b, _ in pair_games(games, x, y)]
        (cch, cn), *_ = streaks(after_res)
        who = names[x] if cch == 'W' else names[y] if cch == 'L' else 'nobody'
        print(f'  AFTER: {who} now on a {cn}-game streak in the series' if cch != 'T' else '  AFTER: tie')
        for f in notable_flags(names, before, x, y):
            print(f'  ** {f}')

    print(f'\n=== Week {args.week}, {args.season}: upcoming matchups ===')
    up = upcoming.get((args.season, args.week), [])
    if not up:
        print('  (no scheduled games found)')
    for g in up:
        print()
        for ln in describe_pair(names, games, g['a'], g['b']):
            print(ln)
        for f in notable_flags(names, games, g['a'], g['b']):
            print(f'   ** {f}')


if __name__ == '__main__':
    main()
