import numpy as np
import pandas as pd
from espn_api.football import League, Player

from datetime import datetime, timedelta

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
