import numpy as np
import pandas as pd
from espn_api.football import League, Player, Team
from typing import List

import datetime
import requests
import re
from data.configs import keys

# https://github.com/cwendt94/espn-api/pull/487#issuecomment-1782273387
def set_league_endpoint(league: League) -> None:
    """Set the league's endpoint."""

    # Current season
    if league.year >= (datetime.datetime.today() - datetime.timedelta(weeks=12)).year:
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
    """
    Get the number of starters for each position

    Parameters
    ----------
    league : object
        The league object for which the starter counts are being generated

    Returns
    -------
    dict
        A dictionary containing the number of players at each position within the starting lineup.
    """

    # Get the box scores for last week
    box_scores = league.box_scores(week=league.current_week - 1)
    # Initialize a dictionary to store the home team's starters and their positions
    h_starters = {}
    # Initialize a variable to keep track of the number of home team starters
    h_starter_count = 0
    # Initialize a dictionary to store the away team's starters and their positions
    a_starters = {}
    # Initialize a variable to keep track of the number of away team starters
    a_starter_count = 0
    # Iterate through each game in the box scores
    for i in box_scores:
        # Iterate through each player in the home team's lineup
        for player in i.home_lineup:
            # Check if the player is a starter (not on the bench or injured)
            if (player.slot_position != 'BE' and player.slot_position != 'IR'):
                # Increment the number of home team starters
                h_starter_count += 1
                try:
                    # Try to increment the count for this position in the h_starters dictionary
                    h_starters[player.slot_position] = h_starters[player.slot_position] + 1
                except KeyError:
                    # If the position is not in the dictionary yet, add it and set the count to 1
                    h_starters[player.slot_position] = 1
        # in the rare case when someone has an empty slot we need to check the other team as well
        for player in i.away_lineup:
            if (player.slot_position != 'BE' and player.slot_position != 'IR'):
                a_starter_count += 1
                try:
                    a_starters[player.slot_position] = a_starters[player.slot_position] + 1
                except KeyError:
                    a_starters[player.slot_position] = 1

        # if statement for the ultra rare case of a matchup with both entire teams (or one with a bye) on the bench
        if a_starter_count!=0 and h_starter_count != 0:
            if a_starter_count > h_starter_count:
                return a_starters
            else:
                return h_starters

# https://github.com/dtcarls/fantasy_football_chat_bot/blob/master/gamedaybot/espn/functionality.py
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
    endpoint = "{}view=mTeam".format(league.endpoint)
    r = requests.get(endpoint, cookies=league.cookies).json()
    if type(r) == list:
        r = r[0]

    # For each member in the data, create a map from SWID to their full name
    swid_to_name = {}
    for member in r["members"]:
        swid_to_name[member["id"]] = re.sub(
            " +", " ", member["firstName"] + " " + member["lastName"]
        ).title()

    # Set the owner name for each team
    for team in league.teams:
        team.owner = swid_to_name[team.owners[0]]

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
    draft_df['team_owner'] = draft_df['team'].apply(lambda x: x.owner)
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

def get_optimal_subs(lineup_df: pd.DataFrame) -> pd.DataFrame:
    """
    Super messy mega-function to find substitutions that should've been made.
    
    Note: still some edge cases to work out.  Logic could be improved and made simpler.
    ### TODO: Simplify and/or break-up the function into parts --- Look into how optimal_lineup_score works
    
    Args:
    lineup_df (pd.DataFrame):  All players on a roster and with their points for the week.
    
    Returns:
        pd.DataFrame: Table containing the substitutions that should have been
                      made for an optimal lineup.

    """
    starter_df = lineup_df[~lineup_df['slot_position'].isin(['BE', 'IR'])]
    
    ## Very hacky manual fix b/c of Taysom Hill's QB position when slotted in TE
    starter_df['position'] = starter_df.apply(lambda x: 'TE' if ((x['player_name'] == 'Taysom Hill') and
                                                                (x['slot_position'] == 'TE'))
                                              else x['position'], axis = 1)
    starters_set = set(starter_df['player_id'])
    sub_dfs = []
    
    ## Get the top QB
    top_qb = lineup_df[lineup_df['position'] == 'QB'].sort_values('points', ascending = False).head(1).reset_index().drop(columns = 'index')
    if top_qb['player_id'][0] not in starters_set:
        current_starting_qb = starter_df[starter_df['position'] == 'QB'].reset_index()
        top_qb['sub_for_player_name'] = current_starting_qb['player_name'][0]
        top_qb['sub_for_player_id'] = current_starting_qb['player_id'][0]
        top_qb['sub_for_player_points'] = current_starting_qb['points'][0]
        top_qb['new_slot_position'] = 'QB'
        sub_dfs.append(top_qb)
    
    ## Get the top 2 RBs:
    top_rbs = lineup_df[lineup_df['position'] == 'RB'].sort_values('points', ascending = False).head(2).reset_index().drop(columns = 'index')   
    
    ## Get the top 2 WRs:
    top_wrs = lineup_df[lineup_df['position'] == 'WR'].sort_values('points', ascending = False).head(2).reset_index().drop(columns = 'index')
    
    ## Get the top TE:
    top_te = lineup_df[lineup_df['position'] == 'TE'].sort_values('points', ascending = False).head(1).reset_index().drop(columns = 'index')
    
    ## Get the top FLEX (Top RB/WR/TE that is not in any of the lists above)
    top_wr_rb_te_ids = list(top_wrs['player_id']) + list(top_rbs['player_id']) + list(top_te['player_id'])
    top_flx = (lineup_df[(lineup_df['position'].isin(['RB', 'WR', 'TE'])) &
                         ~(lineup_df['player_id'].isin(top_wr_rb_te_ids))].sort_values('points', ascending = False)
                       .head(1).reset_index().drop(columns = 'index'))
    top_wr_rb_te_flx_ids = top_wr_rb_te_ids + list(top_flx['player_id'])
    top_wr_rb_te_flx_df = lineup_df[lineup_df['player_id'].isin(top_wr_rb_te_flx_ids)]
    
    ## Set the "sub for" columns now that we have the top RB/WR/TEs and old/new starters
    subbed_player_candidate_df = starter_df[~(starter_df['player_id'].isin(top_wr_rb_te_flx_ids)) &
                                             (starter_df['slot_position'].isin(['RB', 'WR', 'TE', 'RB/WR/TE']))].sort_values('points').reset_index().drop(columns = 'index')
    rb_removed_lineup_df = subbed_player_candidate_df[subbed_player_candidate_df['position'] == 'RB'].sort_values('points').reset_index().drop(columns = 'index')
    wr_removed_lineup_df = subbed_player_candidate_df[subbed_player_candidate_df['position'] == 'WR'].sort_values('points').reset_index().drop(columns = 'index')
    te_removed_lineup_df = subbed_player_candidate_df[subbed_player_candidate_df['position'] == 'TE'].sort_values('points').reset_index().drop(columns = 'index')
    
    #if len(top_wr_rb_te_flx_df[top_wr_rb_te_flx_df['position'] == 'TE']) == 1:
        ## If there's only 1 TE in the top RB/WR/TE/Flex DF, don't consider TEs benched as the substitute for the benched player
    #    subbed_player_candidate_df = subbed_player_candidate_df[subbed_player_candidate_df['position'] != 'TE']
    #if len(top_wr_rb_te_flx_df[top_wr_rb_te_flx_df['position'] == 'WR']) == 2:
        ## If there's only 2 WR in the top RB/WR/TE/Flex DF, don't consider WRs benched as the substitute for the benched player
    #    subbed_player_candidate_df = subbed_player_candidate_df[subbed_player_candidate_df['position'] != 'WR']
    #if len(top_wr_rb_te_flx_df[top_wr_rb_te_flx_df['position'] == 'RB']) == 2:
        ## If there's only 2 RB in the top RB/WR/TE/Flex DF, don't consider RBs benched as the substitute for the benched player
    #    subbed_player_candidate_df = subbed_player_candidate_df[subbed_player_candidate_df['position'] != 'RB']
    #flx_removed_lineup_df = subbed_player_candidate_df[subbed_player_candidate_df['slot_position'] == 'RB/WR/TE'].sort_values('points').reset_index().drop(columns = 'index')
    old_flex_position = starter_df[starter_df['slot_position'] == 'RB/WR/TE'].reset_index()['position'][0]
    old_flex_player = starter_df[starter_df['slot_position'] == 'RB/WR/TE'].reset_index()
    
    ## For RBs
    if len(sub_dfs) > 0:
        sub_df = pd.concat(sub_dfs)
        already_subbed_player_ids = list(sub_df['player_id'])
    else:
        already_subbed_player_ids = []
    ### Top scorer
    if top_rbs['player_id'][0] not in starters_set:
        top_rb1 = pd.DataFrame(top_rbs.iloc[0]).T
        if (len(subbed_player_candidate_df) == 1):
            sub_player = (subbed_player_candidate_df['player'][0])
        elif len(rb_removed_lineup_df) > 0:
            ## If at least 1 RB was removed from the lineup, 
            #  take the one with the least points as the one we're subbing out
            sub_player = rb_removed_lineup_df['player'][0]
        else:
            ## Otherwise we must've taken a flex out to make room for another RB, so we'll use that one
            sub_player = (subbed_player_candidate_df[
                (subbed_player_candidate_df['slot_position'] == old_flex_position) & 
                (~subbed_player_candidate_df['player_id'].isin(already_subbed_player_ids))].reset_index()['player'][0])
        top_rb1['sub_for_player_name'] = sub_player.name
        top_rb1['sub_for_player_id'] = sub_player.playerId
        top_rb1['sub_for_player_points'] = sub_player.points
        top_rb1['new_slot_position'] = 'RB'
        sub_dfs.append(top_rb1)
    
    ### 2nd highest scorer at RB
    if len(sub_dfs) > 0:
        sub_df = pd.concat(sub_dfs)
        already_subbed_player_ids = list(sub_df['player_id'])
    else:
        already_subbed_player_ids = []
    if top_rbs['player_id'][1] not in starters_set:
        top_rb2 = pd.DataFrame(top_rbs.iloc[1]).T
        if (len(subbed_player_candidate_df) == 1):
            sub_player = (subbed_player_candidate_df['player'][0])
        elif (len(rb_removed_lineup_df) == 1) and (top_rbs['player_id'][0] in starters_set):
            ## If there was only 1 RB removed and we haven't already used RB1 as a sub from the bench
            sub_player = rb_removed_lineup_df['player'][0]
        elif len(rb_removed_lineup_df) >= 2:
            ## If there were 2 or more from the RB position removed, use the one with the 2nd highest points
            sub_player = rb_removed_lineup_df['player'][1]
        #elif old_flex_player['player_id'][0] not in top_wr_rb_te_flx_df['player_id']:
            ## Otherwise we must've taken a flex out to make room for another RB, so we'll use that one
        #    sub_player = (subbed_player_candidate_df[
        #        (subbed_player_candidate_df['slot_position'] == old_flex_position) & 
        #        (~subbed_player_candidate_df['player_id'].isin(already_subbed_player_ids))].reset_index()['player'][0])
        else:
            rb_not_yet_subbed = rb_removed_lineup_df[~rb_removed_lineup_df['player_id'].isin(already_subbed_player_ids)]
            wr_not_yet_subbed = wr_removed_lineup_df[~wr_removed_lineup_df['player_id'].isin(already_subbed_player_ids)]
            te_not_yet_subbed = te_removed_lineup_df[~te_removed_lineup_df['player_id'].isin(already_subbed_player_ids)]
            if len(rb_not_yet_subbed) > 0: 
                sub_player = (rb_not_yet_subbed['player'][0])
            elif len(wr_not_yet_subbed) > 0: 
                sub_player = (wr_not_yet_subbed['player'][0])
            elif len(te_not_yet_subbed) > 0: 
                sub_player = (te_not_yet_subbed['player'][0])

        top_rb2['sub_for_player_name'] = sub_player.name
        top_rb2['sub_for_player_id'] = sub_player.playerId
        top_rb2['sub_for_player_points'] = sub_player.points
        top_rb2['new_slot_position'] = 'RB'
        sub_dfs.append(top_rb2)

    ## For WRs
    ### Top scorer
    if len(sub_dfs) > 0:
        sub_df = pd.concat(sub_dfs)
        already_subbed_player_ids = list(sub_df['player_id'])
    else:
        already_subbed_player_ids = []
    if top_wrs['player_id'][0] not in starters_set:
        top_wr1 = pd.DataFrame(top_wrs.iloc[0]).T
        #print(subbed_player_candidate_df[['player_name', 'slot_position', 'position', 'points']])
        #print(len(subbed_player_candidate_df))
        if (len(subbed_player_candidate_df) == 1):
            sub_player = (subbed_player_candidate_df['player'][0])
        elif len(wr_removed_lineup_df) > 0:
            ## If at least 1 RB was removed from the lineup, 
            #  take the one with the least points as the one we're subbing out
            sub_player = wr_removed_lineup_df['player'][0]
        else:
            ## Otherwise we must've taken out a player from the flex position to make room for another WR, so we'll use that one
            sub_player = (subbed_player_candidate_df[
                (subbed_player_candidate_df['position'] == old_flex_position) & 
                (~subbed_player_candidate_df['player_id'].isin(already_subbed_player_ids))].reset_index()['player'][0])
        top_wr1['sub_for_player_name'] = sub_player.name
        top_wr1['sub_for_player_id'] = sub_player.playerId
        top_wr1['sub_for_player_points'] = sub_player.points
        top_wr1['new_slot_position'] = 'WR'
        sub_dfs.append(top_wr1)
    ### 2nd highest scorer at WR
    if len(sub_dfs) > 0:
        sub_df = pd.concat(sub_dfs)
        already_subbed_player_ids = list(sub_df['player_id'])
    else:
        already_subbed_player_ids = []
    if top_wrs['player_id'][1] not in starters_set:
        top_wr2 = pd.DataFrame(top_wrs.iloc[1]).T
        if (len(subbed_player_candidate_df) == 1):
            sub_player = (subbed_player_candidate_df['player'][0])
        elif (len(wr_removed_lineup_df) == 1) and (top_wrs['player_id'][0] in starters_set):
            ## If there was only 1 WR removed and we haven't already used WR1 as a sub from the bench
            sub_player = wr_removed_lineup_df['player'][0]
        elif len(wr_removed_lineup_df) > 1:
            ## If there were 2 or more from the WR position removed, use the one with the 2nd highest points
            sub_player = wr_removed_lineup_df['player'][1]
        else:
            ## Otherwise we must've taken out a player from the flex position to make room for another WR, so we'll use that one
            sub_player = (subbed_player_candidate_df[
                (subbed_player_candidate_df['position'] == old_flex_position) & 
                (~subbed_player_candidate_df['player_id'].isin(already_subbed_player_ids))].reset_index()['player'][0])
        top_wr2['sub_for_player_name'] = sub_player.name
        top_wr2['sub_for_player_id'] = sub_player.playerId
        top_wr2['sub_for_player_points'] = sub_player.points
        top_wr2['new_slot_position'] = 'WR'
        sub_dfs.append(top_wr2)
    
    ## For TE
    if len(sub_dfs) > 0:
        sub_df = pd.concat(sub_dfs)
        already_subbed_player_ids = list(sub_df['player_id'])
    else:
        already_subbed_player_ids = []
    if top_te['player_id'][0] not in starters_set:
        if (len(subbed_player_candidate_df) == 1):
            sub_player = (subbed_player_candidate_df['player'][0])
        elif len(te_removed_lineup_df) == 1:
            sub_player = te_removed_lineup_df['player'][0]
        elif len(top_wr_rb_te_flx_df[top_wr_rb_te_flx_df['position'] == 'TE']) == 2:
            ## Moved the starting TE to the flex and now have 2 TEs
            rb_not_yet_subbed = rb_removed_lineup_df[~rb_removed_lineup_df['player_id'].isin(sub_df)]
            wr_not_yet_subbed = wr_removed_lineup_df[~wr_removed_lineup_df['player_id'].isin(sub_df)]
            if len(rb_not_yet_subbed) > 0: 
                sub_player = (rb_not_yet_subbed['player'][0])
            elif len(wr_not_yet_subbed) > 0: 
                sub_player = (wr_not_yet_subbed['player'][0])

        else:
            # Otherwise we must've taken a flex out to make room for another TE, so we'll use that one
            sub_player = (subbed_player_candidate_df[
                (subbed_player_candidate_df['slot_position'] == old_flex_position) & 
                (~subbed_player_candidate_df['player_id'].isin(already_subbed_player_ids))].reset_index()['player'][0])
            
        top_te['sub_for_player_name'] = sub_player.name
        top_te['sub_for_player_id'] = sub_player.playerId
        top_te['sub_for_player_points'] = sub_player.points
        top_te['new_slot_position'] = 'TE'
        sub_dfs.append(top_te)
    
    ## For Flex (RB/WR/TE)
    if top_flx['player_id'][0] not in starters_set:
        ## The player we took out for the new flex player is tricky... here's the logic in plain English
        """
        Scenarios:
         1. If we had 3 RBs in before and now only 2, then we choose the RB removed with the most points
             (this scenario may break if we subbed 2 RBs out and added 1 off the bench,
              in this case we should take the one subbed out with the most points)
         2. Same for WRs
         3. If we had 2 TEs before and now only have 1, then we choose the TE removed
         4. If we have equal number before and after AND only 1 player was removed, 
             we must have replaced the flex with the same position.
         5. OR we substituted 2 or 3 of the same position for each other, in which case we take 
             the one with the most points scored as our sub (because we took the lowest points
                                                             for RB1, 2nd for RB2, etc.)
        We can simplify the last 2 scenarios by just applying the most points case
        """
        
        if (len(subbed_player_candidate_df) == 1):
            sub_player = (subbed_player_candidate_df['player'][0])
        elif ((len(starter_df[starter_df['position'] == 'RB']) == 3) and
           (len(top_wr_rb_te_flx_df[top_wr_rb_te_flx_df['position'] == 'RB']) == 2)):
            sub_player = (rb_removed_lineup_df['player'][len(rb_removed_lineup_df)-1])
        elif ((len(starter_df[starter_df['position'] == 'WR']) == 3) and
           (len(top_wr_rb_te_flx_df[top_wr_rb_te_flx_df['position'] == 'WR']) == 2)):
            sub_player = (wr_removed_lineup_df['player'][len(wr_removed_lineup_df)-1])
        elif ((len(starter_df[starter_df['position'] == 'TE']) == 2) and
           (len(top_wr_rb_te_flx_df[top_wr_rb_te_flx_df['position'] == 'TE']) == 1)):
            sub_player = (te_removed_lineup_df['player'][len(te_removed_lineup_df)-1])
        
        ## Can we replace all of the above with just this??
        elif old_flex_position == 'WR':
            sub_player = (wr_removed_lineup_df['player'][len(wr_removed_lineup_df)-1])
        elif old_flex_position == 'RB':
            sub_player = (rb_removed_lineup_df['player'][len(rb_removed_lineup_df)-1])
        elif old_flex_position == 'TE':
            sub_player = (te_removed_lineup_df['player'][len(te_removed_lineup_df)-1])
        
        top_flx['sub_for_player_name'] = sub_player.name
        top_flx['sub_for_player_id'] = sub_player.playerId
        top_flx['sub_for_player_points'] = sub_player.points
        top_flx['new_slot_position'] = 'RB/WR/TE'
        sub_dfs.append(top_flx)
    
    
    ## Get the top D/ST:
    top_d = lineup_df[lineup_df['position'] == 'D/ST'].sort_values('points', ascending = False).head(1).reset_index().drop(columns = 'index')
    if len(top_d) > 0:
        if top_d['player_id'][0] not in starters_set:
            current_starting_d = starter_df[starter_df['position'] == 'D/ST'].reset_index()
            if len(current_starting_d) > 0:
                top_d['sub_for_player_name'] = current_starting_d['player_name'][0]
                top_d['sub_for_player_id'] = current_starting_d['player_id'][0]
                top_d['sub_for_player_points'] = current_starting_d['points'][0]
            else: 
                top_d['sub_for_player_name'] = 'No Defense'
                top_d['sub_for_player_id'] = None
                top_d['sub_for_player_points'] = 0          
            sub_dfs.append(top_d)
    
    ## Get the top K:
    top_k = lineup_df[lineup_df['position'] == 'K'].sort_values('points', ascending = False).head(1).reset_index().drop(columns = 'index')
    if top_k['player_id'][0] not in starters_set:
        current_starting_k = starter_df[starter_df['position'] == 'K'].reset_index()
        top_k['sub_for_player_name'] = current_starting_k['player_name'][0]
        top_k['sub_for_player_id'] = current_starting_k['player_id'][0]
        top_k['sub_for_player_points'] = current_starting_k['points'][0]
        sub_dfs.append(top_k)
    
    if len(sub_dfs) > 0:
        sub_df = pd.concat(sub_dfs).reset_index(drop=True)
    else:
        sub_df = pd.DataFrame()

    return sub_df

def get_scoring_df(week: int, league: League) -> pd.DataFrame:
    """Get a DataFrame of all box scores in the league through the given week

    Args:
        week (int): week number
        league (League): ESPN fantasy league obj/connection

    Returns:
        pd.DataFrame: DataFrame of all box scores (points by player not on bench)
    """
    weeks = range(1,week+1)
    teams = []
    players = []
    scores = []
    week_list = []
    for week in weeks:
        for box in league.box_scores(week):
            for player in box.home_lineup:
                if player.slot_position != 'BE':
                    players.append(player)
                    scores.append(player.points)
                    teams.append(box.home_team)
                    week_list.append(week)
            for player in box.away_lineup:
                if player.slot_position != 'BE':
                    players.append(player)
                    scores.append(player.points)
                    teams.append(box.away_team)
                    week_list.append(week)
    scoring_df = pd.DataFrame({'team': teams,
                            'player': players,
                            'points': scores,
                            'week': week_list})
    scoring_df['player_id'] = scoring_df['player'].apply(lambda x: x.playerId)
    scoring_df['player_name'] = scoring_df['player'].apply(lambda x: x.name)
    scoring_df['team_name'] = scoring_df['team'].apply(lambda x: x.team_name)
    scoring_df['team_owner'] = scoring_df['team'].apply(lambda x: x.owner)
    scoring_df['team_name_owner'] = scoring_df['team_name'] + ' (' + scoring_df['team_owner'] + ')'

    return scoring_df

def get_lineup_df(week: int, league: League) -> pd.DataFrame:
    """Get a DataFrame of all box scores in the league through the given week

    Args:
        week (int): week number
        league (League): ESPN fantasy league obj/connection

    Returns:
        pd.DataFrame: DataFrame of all lineups each week
    """

    weeks = range(1,week+1)
    teams = []
    players = []
    slot_positions = []
    positions = []
    scores = []
    week_list = []
    for week in weeks:
        for box in league.box_scores(week):
            for player in box.home_lineup:
                players.append(player)
                scores.append(player.points)
                positions.append(player.position)
                slot_positions.append(player.slot_position)
                teams.append(box.home_team)
                week_list.append(week)
            for player in box.away_lineup:
                players.append(player)
                scores.append(player.points)
                positions.append(player.position)
                slot_positions.append(player.slot_position)
                teams.append(box.away_team)
                week_list.append(week)
    lineup_df = pd.DataFrame({'team': teams,
                            'player': players,
                            'position': positions,
                            'slot_position': slot_positions,
                            'points': scores,
                            'week': week_list})
    lineup_df['player_id']   = lineup_df['player'].apply(lambda x: x.playerId)
    lineup_df['player_name'] = lineup_df['player'].apply(lambda x: x.name)
    lineup_df['team_name']   = lineup_df['team'].apply(lambda x: x.team_name)
    lineup_df['team_owner']  = lineup_df['team'].apply(lambda x: x.owner)
    lineup_df['team_name_owner'] = lineup_df['team_name'] + ' (' + lineup_df['team_owner'] + ')'

    return lineup_df

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
    scores = []
    results = []
    win_flgs = []
    for week in weeks:
        for score in league.scoreboard(week):
            
            ## Get team names/scores/results (W/L)
            away_team = score.away_team.team_name
            away_score = score.away_score
            away_result = ('W' if away_score > score.home_score else 'L' if 
                        away_score < score.home_score else 'T')
            away_win_flg = 1 if away_result == 'W' else 0
            home_team = score.home_team.team_name
            home_score = score.home_score
            home_result = ('W' if home_score > away_score else 'L' if 
                        home_score < away_score else 'T')
            home_win_flg = 1 if home_result == 'W' else 0
            
            ## Add everything to lists for away team
            teams.append(away_team)
            scores.append(away_score)
            results.append(away_result)
            win_flgs.append(away_win_flg)
            week_list.append(week)        
            
            ## Add everything to lists for home team
            teams.append(home_team)
            scores.append(home_score)
            results.append(home_result)
            win_flgs.append(home_win_flg)
            week_list.append(week)

    weekly_scores_df = pd.DataFrame({'week': week_list,
                                    'team': teams,
                                    'score': scores,
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


def get_start_week_after_trade(trade_date: float, season_start_date: datetime.datetime, final_week_number: int) -> int:
    """Find the first week of the season after the trade

    Args:
        trade_date (float): ESPN's date of the trade, epoch milliseconds
        season_start_date (datetime.datetime): date that the season started
        final_week_number (int): last week number of the season

    Returns:
        int: first week number after the trade
    """
    weeks = []
    dates = []
    week = 1
    date = season_start_date
    for i in range(1, final_week_number+1):
        weeks.append(week)
        dates.append(date)
        date = date + datetime.timedelta(days=7)
        week+=1
    dates_df = pd.DataFrame({'week': weeks, 'date':dates})
    sub_dates_df = dates_df[dates_df['date'] > datetime.fromtimestamp(trade_date/1000)]
    min_week_after_trade = list(sub_dates_df[sub_dates_df['date'] == sub_dates_df['date'].min()]['week'])[0]
    return min_week_after_trade


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
    for week in range(start_week, 18): ## Hard coded last week of season
        boxes = league.box_scores(week)
        week_lineup = [box.home_lineup if team.team_name == box.home_team.team_name else box.away_lineup for box in boxes 
                       if team.team_name in [box.home_team.team_name, box.away_team.team_name]]
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


def get_trade_evalutions_df(league: League, season_start_date, final_week_number=17) -> pd.DataFrame:
    """Compiles a DataFrame of all retroactively evaluated trades for the fantasy season based on ROS value for a team's roster.

    Args:
        league (League): ESPN fantasy league obj/connection

    Returns:
        pd.DataFrame: DataFrame of all retroactively evaluated trades for the fantasy season
    """

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
            start_week = get_start_week_after_trade(trade.date, season_start_date=season_start_date, final_week_number=final_week_number)
            point_diff = get_point_diff_for_trade(team, start_week, players_added, players_lost)
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