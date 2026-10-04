import numpy as np
import pandas as pd
from espn_api.football import League, Player, Team
from typing import List

from datetime import datetime, timedelta, timezone
import requests
import re

from mustafatron.league_settings import load_settings
from mustafatron.rules import load_rules
#from data.configs import keys

# https://github.com/cwendt94/espn-api/pull/487#issuecomment-1782273387
def set_league_endpoint(league: League) -> None:
    """Set the league's endpoint."""

    # Current season
    if league.year >= (datetime.today() - timedelta(weeks=12)).year:
        league.endpoint = (
            "https://fantasy.espn.com/apis/v3/games/ffl/seasons/"
            + str(league.year)
            + "/segments/0/leagues/"
            + str(league.league_id)
            + "?"
        )

    # Old season
    else:
        league.endpoint = (
            "https://fantasy.espn.com/apis/v3/games/ffl/leagueHistory/"
            + str(league.league_id)
            + "?seasonId="
            + str(league.year)
            + "&"
        )


# https://github.com/dtcarls/fantasy_football_chat_bot/blob/master/gamedaybot/espn/functionality.py
def best_flex(flexes, player_pool, num):
    """
    Given a list of flex positions, a dictionary of player pool, and a number of players to return,
    this function returns the best flex players from the player pool.

    Parameters
    ----------
    flexes : list
        a list of strings representing the flex positions
    player_pool : dict
        a dictionary with keys as position and values as a dictionary with player name as key and value as score
    num : int
        number of players to return from the player pool

    Returns
    ----------
    best : dict
        a dictionary containing the best flex players from the player pool
    player_pool : dict
        the updated player pool after removing the best flex players
    """

    pool = {}
    # iterate through each flex position
    for flex_position in flexes:
        # add players from flex position to the pool
        try:
            pool = pool | player_pool[flex_position]
        except KeyError:
            pass
    # sort the pool by score in descending order
    pool = {k: v for k, v in sorted(pool.items(), key=lambda item: item[1], reverse=True)}
    # get the top num players from the pool
    best = dict(list(pool.items())[:num])
    # remove the best flex players from the player pool
    for pos in player_pool:
        for p in best:
            if p in player_pool[pos]:
                player_pool[pos].pop(p)
    return best, player_pool


# https://github.com/dtcarls/fantasy_football_chat_bot/blob/master/gamedaybot/espn/functionality.py
def get_starter_counts(league):
    """Number of starters per lineup slot, e.g. {'QB': 1, 'RB': 2, ..., 'RB/WR/TE': 1}.

    Read from the season's ESPN mSettings rather than inferred from last week's box scores.
    """
    return load_settings(league.year).starter_slots

def optimal_lineup_score(lineup, starter_counts):
    """
    This function returns the optimal lineup score based on the provided lineup and starter counts.

    Parameters
    ----------
    lineup : list
        A list of player objects for which the optimal lineup score is being generated
    starter_counts : dict
        A dictionary containing the number of starters for each position

    Returns
    -------
    tuple
        A tuple containing the optimal lineup score, the provided lineup score, the difference between the two scores,
        and the percentage of the provided lineup's score compared to the optimal lineup's score.
    """

    best_lineup = {}
    position_players = {}

    # get all players and points
    score = 0
    score_pct = 0
    best_score = 0

    for player in lineup:
        try:
            position_players[player.position][player.name] = player.points
        except KeyError:
            position_players[player.position] = {}
            position_players[player.position][player.name] = player.points
        if player.slot_position not in ['BE', 'IR']:
            score += player.points

    # sort players by position for points
    for position in starter_counts:
        try:
            position_players[position] = {k: v for k, v in sorted(
                position_players[position].items(), key=lambda item: item[1], reverse=True)}
            best_lineup[position] = dict(list(position_players[position].items())[:starter_counts[position]])
            position_players[position] = dict(list(position_players[position].items())[starter_counts[position]:])
        except KeyError:
            best_lineup[position] = {}

    # flexes. need to figure out best in other single positions first
    for position in starter_counts:
        # flex
        if 'D/ST' not in position and '/' in position:
            flex = position.split('/')
            result = best_flex(flex, position_players, starter_counts[position])
            best_lineup[position] = result[0]
            position_players = result[1]

    # Offensive Player. need to figure out best in other positions first
    if 'OP' in starter_counts:
        flex = ['RB', 'WR', 'TE', 'QB']
        result = best_flex(flex, position_players, starter_counts['OP'])
        best_lineup['OP'] = result[0]
        position_players = result[1]

    # Defensive Player. need to figure out best in other positions first
    if 'DP' in starter_counts:
        flex = ['DT', 'DE', 'LB', 'CB', 'S']
        result = best_flex(flex, position_players, starter_counts['DP'])
        best_lineup['DP'] = result[0]
        position_players = result[1]

    for position in best_lineup:
        best_score += sum(best_lineup[position].values())

    if best_score != 0:
        score_pct = (score / best_score) * 100

    return (best_score, score, best_score - score, score_pct)

def set_owner_names(league: League):
    """This function sets the owner names for each team in the league.
    The team.owners attribute only contains the SWIDs of each owner, not their real name.

    Args:
        league (League): ESPN League object
    """
    #endpoint = "{}view=mTeam".format(league.endpoint)
    #r = requests.get(endpoint, cookies=league.cookies).json()
    #if type(r) == list:
    #    r = r[0]
#
    ## For each member in the data, create a map from SWID to their full name
    #swid_to_name = {}
    #for member in r["members"]:
    #    swid_to_name[member["id"]] = re.sub(
    #        " +", " ", member["firstName"] + " " + member["lastName"]
    #    ).title()
#
    ## Set the owner name for each team
    for team in league.teams:
        team.owner = team.owners[0]["firstName"] + " " + team.owners[0]["lastName"]

def get_player_obj(league: League, player_id: int, player_name: str) -> Player:
    """
    Helper function to get a player object from the 

    Args:
        league (League): League object from espn_api
        player_id (int): ESPN ID for player
        player_name (str): Name of player

    Returns:
        Player: espn_api Player object
    """
    try:
        player = league.player_info(playerId = player_id)
    except:
        try:
            player = league.player_info(name = player_name, playerId = player_id)
        except:
            return None
    
    return player

def get_draft_df(league: League) -> pd.DataFrame:
    """
    Get a DataFrame of each draft pick and the 

    Args:
        league (League): ESPN fantasy league obj/connection

    Returns:
        pd.DataFrame: DataFrame of draft results and avg. pts above/below avg for position
    """
    ## Using the API to get the draft
    player_ids = []
    player_names = []
    round_nums = []
    round_picks = []
    teams = []
    for pick in league.draft:
        player_ids.append(pick.playerId)
        player_names.append(pick.playerName)

        round_nums.append(pick.round_num)
        round_picks.append(pick.round_pick)
        teams.append(pick.team)
    draft_df = pd.DataFrame({'player_id': player_ids,
                            'player_name': player_names,
                            'round_num': round_nums,
                            'round_pick': round_picks,
                            'team': teams})
    draft_df['team_owner'] = draft_df['team'].apply(lambda x: ', '.join([owner['firstName'] + ' ' + owner['lastName'] for owner in x.owners]))
    draft_df['team_name'] = draft_df['team'].apply(lambda x: x.team_name)

    draft_df['Player_obj'] = draft_df.apply(lambda x: get_player_obj(league, x['player_id'], x['player_name']), axis = 1)
    draft_df['points'] = draft_df['Player_obj'].apply(lambda x: x.stats[0]['points'])
    draft_df['position'] = draft_df['Player_obj'].apply(lambda x: x.position)
    #draft_df['espn_proj_pts_thru_week'] =  draft_df['Player_obj'].apply(lambda x: x.projected_total_points*(WEEK_NUMBER/17)) 
    ## ^ This doesn't work bc the player obj has the projected pts for the *rest* of the season, not as of the beginning
    avg_pos_points = draft_df.groupby('position').agg({'points': np.mean}).sort_values('points', ascending = False).reset_index().rename(columns = {'points':'avg_pos_points'})

    draft_df = draft_df.merge(avg_pos_points, on = 'position')
    draft_df['points_above_avg'] = draft_df['points'] -  draft_df['avg_pos_points']
    draft_df['overall_pick'] = (draft_df['round_num']-1)*len(set(teams))+draft_df['round_pick']
    return draft_df

def get_weekly_scores_df(week: int, league: League) -> pd.DataFrame:
    """Go through box scores and compute the "record vs. entire league" metrics needed for the report.

    Args:
        week (int): Week number
        league (League): ESPN fantasy league obj/connection

    Returns:
        pd.DataFrame: DataFrame of scores for each week by team
    """
    weeks = range(1,week+1)
    week_list = []
    teams = []
    team_owners = []
    opponents = []
    opponent_owners = []
    scores = []
    opp_scores = []
    score_diffs = []
    results = []
    win_flgs = []
    for week in weeks:
        for score in league.scoreboard(week):
            
            ## Get team names/scores/results (W/L)
            away_team = score.away_team.team_name
            away_owner = score.away_team.owner
            away_score = score.away_score
            away_result = ('W' if away_score > score.home_score else 'L' if 
                        away_score < score.home_score else 'T')
            away_win_flg = 1 if away_result == 'W' else 0
            home_team = score.home_team.team_name
            home_owner = score.home_team.owner
            home_score = score.home_score
            home_result = ('W' if home_score > away_score else 'L' if 
                        home_score < away_score else 'T')
            home_win_flg = 1 if home_result == 'W' else 0
            
            ## Add everything to lists for away team
            teams.append(away_team)
            team_owners.append(away_owner)
            opponents.append(home_team)
            opponent_owners.append(home_owner)
            scores.append(away_score)
            opp_scores.append(home_score)
            score_diffs.append(away_score-home_score)
            results.append(away_result)
            win_flgs.append(away_win_flg)
            week_list.append(week)        
            
            ## Add everything to lists for home team
            teams.append(home_team)
            team_owners.append(home_owner)
            opponents.append(away_team)
            opponent_owners.append(away_owner)
            scores.append(home_score)
            opp_scores.append(away_score)
            score_diffs.append(home_score-away_score)
            results.append(home_result)
            win_flgs.append(home_win_flg)
            week_list.append(week)

    weekly_scores_df = pd.DataFrame({'week': week_list,
                                    'team': teams,
                                    'team_owner': team_owners,
                                    'opponent': opponents,
                                    'opponent_owners': opponent_owners,
                                    'score': scores,
                                    'opponent_score': opp_scores,
                                    'score_diff': score_diffs,
                                    'result': results,
                                    'win_flg': win_flgs})

    ## Add columns needed for plots
    weekly_scores_df['rank_in_week'] = (weekly_scores_df.groupby('week')['score']
                                        .rank("max", ascending = False))
    weekly_scores_df['wins_in_week'] = (weekly_scores_df.groupby('week')['score']
                                        .rank("max", ascending = True)) - 1
    weekly_scores_df['losses_in_week'] = (len(set(teams))-1) - weekly_scores_df['wins_in_week']
    weekly_scores_df['record_for_week'] = weekly_scores_df['wins_in_week'].astype(int).astype(str) + '-' + weekly_scores_df['losses_in_week'].astype(int).astype(str)
    weekly_scores_df['win_pct_week'] = weekly_scores_df['wins_in_week']/(weekly_scores_df['wins_in_week'] + weekly_scores_df['losses_in_week']*1.00)

    return weekly_scores_df

### Utilities for retrospective evaluation of trades at the end of the season
class ReplacementBoxPlayer():
    ## This is needed because the BoxPlayer class is not easily accessible from the Player class included in the trade
    ### But we can get all we really need (points scored by week) from the .stats attribute of the Player class
    def __init__(self, player, week):
        self.position = player.position
        self.name = player.name
        #print(player.name)
        self.points = self.get_points(player, week)
        self.slot_position = 'BE'

    def get_points(self, player, week):
        try:
            points = player.stats[week]['points']
            return points
        except:
            return 0


def get_start_week_after_trade(trade_date: float, season: int, final_week_number: int) -> int:
    """Find the first week of the season after the trade

    Week boundaries come from the season's NFL week 1 kickoff in data/manual/league_rules.yml
    (previously a hand-typed season_start_date, which disagreed with itself in 2025).

    Args:
        trade_date (float): ESPN's date of the trade, epoch milliseconds
        season (int): fantasy season
        final_week_number (int): last week number of the season

    Returns:
        int: first week number after the trade, or None if it came after the final week started
    """
    when = datetime.fromtimestamp(trade_date / 1000, tz=timezone.utc)
    return load_rules().first_week_after(season, when, final_week=final_week_number)


def get_point_diff_for_trade(league: League, team: Team, start_week: int, players_added: List[Player], players_lost: List[Player]) -> float:
    """Finds the 

    Args:
        league (League): ESPN fantasy league obj/connection
        team (Team): ESPN fantasy team object
        start_week (int): first week after the trade
        players_added (List): list of player objects that were received by the team in the trade
        players_lost (List): list of player objects that were traded away by the team in the trade

    Returns:
        float: number of points added/lost based on optimal lineups with new players vs optimal lineups with old players for ROS.
    """
    starter_counts = get_starter_counts(league)
    names_in_trade = [p.name for p in players_added] + [p.name for p in players_lost]
    total_point_diff = 0
    for week in range(start_week, load_settings(league.year).final_matchup_period + 1):
        boxes = league.box_scores(week)
        week_lineup = [box.home_lineup if team.team_name == box.home_team.team_name else box.away_lineup for box in boxes 
                       if team.team_name in [box.home_team.team_name, box.away_team.team_name]]
        if not week_lineup:  # eliminated from the playoffs: no lineup this week
            continue
        week_lineup = week_lineup[0]
        new_players = [ReplacementBoxPlayer(p, week) for p in players_added]
        old_players = [ReplacementBoxPlayer(p, week) for p in players_lost]
        lineup_with_new_players = [p for p in week_lineup if p.name not in names_in_trade] + new_players
        lineup_with_old_players = [p for p in week_lineup if p.name not in names_in_trade] + old_players
        new_optimal_score, score, new_actual_diff, new_score_pct = optimal_lineup_score(lineup_with_new_players, starter_counts)
        old_optimal_score, score, old_actual_diff, old_score_pct = optimal_lineup_score(lineup_with_old_players, starter_counts)
        point_diff = new_optimal_score - old_optimal_score
        total_point_diff += point_diff
    return total_point_diff


def get_trade_evaluations_df(league: League, final_week_number=None) -> pd.DataFrame:
    """Compiles a DataFrame of all retroactively evaluated trades for the fantasy season based on ROS value for a team's roster.

    Args:
        league (League): ESPN fantasy league obj/connection

    Returns:
        pd.DataFrame: DataFrame of all retroactively evaluated trades for the fantasy season
    """

    if final_week_number is None:
        final_week_number = load_settings(league.year).final_scoring_period
    team_list = []
    players_added_list = []
    players_lost_list = []
    week_after_trade_list = []
    point_diff_list = []
    league_trades = league.recent_activity(size=100, msg_type='TRADED')
    for trade in league_trades:
        teams = list(set([action[0] for action in trade.actions]))
        for team in teams:
            players_added = [action[2] for action in trade.actions if action[0] != team]
            players_lost  = [action[2] for action in trade.actions if action[0] == team]
            start_week = get_start_week_after_trade(trade.date, season=league.year, final_week_number=final_week_number)
            point_diff = get_point_diff_for_trade(league, team, start_week, players_added, players_lost)
            team_list.append(team)
            players_added_list.append(players_added)
            players_lost_list.append(players_lost)
            week_after_trade_list.append(start_week)
            point_diff_list.append(point_diff)
            

    trade_evaluations_df = pd.DataFrame({'team': team_list, 'players_added': players_added_list,
                                        'players_lost': players_lost_list, 'week_after_trade': week_after_trade_list
                                        ,'point_diff': point_diff_list
                                        })
    return trade_evaluations_df