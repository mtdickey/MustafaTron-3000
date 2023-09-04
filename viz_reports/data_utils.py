import numpy as np
import pandas as pd
from espn_api.football import League, Player

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

    draft_df['Player_obj'] = draft_df.apply(lambda x: get_player_obj(x['player_id'], x['player_name']), axis = 1)
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
    ### TODO: Simplify and/or break-up the function into parts
    
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
    sub_df = pd.DataFrame()
    
    ## Get the top QB
    top_qb = lineup_df[lineup_df['position'] == 'QB'].sort_values('points', ascending = False).head(1).reset_index().drop(columns = 'index')
    if top_qb['player_id'][0] not in starters_set:
        current_starting_qb = starter_df[starter_df['position'] == 'QB'].reset_index()
        top_qb['sub_for_player_name'] = current_starting_qb['player_name'][0]
        top_qb['sub_for_player_id'] = current_starting_qb['player_id'][0]
        top_qb['sub_for_player_points'] = current_starting_qb['points'][0]
        top_qb['new_slot_position'] = 'QB'
        sub_df = sub_df.append(top_qb)
    
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
    if len(sub_df) > 0:
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
        sub_df = sub_df.append(top_rb1)
    
    ### 2nd highest scorer at RB
    if len(sub_df) > 0:
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
            rb_not_yet_subbed = rb_removed_lineup_df[~rb_removed_lineup_df['player_id'].isin(sub_df)]
            wr_not_yet_subbed = wr_removed_lineup_df[~wr_removed_lineup_df['player_id'].isin(sub_df)]
            te_not_yet_subbed = te_removed_lineup_df[~te_removed_lineup_df['player_id'].isin(sub_df)]
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
        sub_df = sub_df.append(top_rb2)

    ## For WRs
    ### Top scorer
    if len(sub_df) > 0:
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
        sub_df = sub_df.append(top_wr1)
    ### 2nd highest scorer at WR
    if len(sub_df) > 0:
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
        sub_df = sub_df.append(top_wr2)
    
    ## For TE
    if len(sub_df) > 0:
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
        sub_df = sub_df.append(top_te)
    
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
        sub_df = sub_df.append(top_flx)
    
    
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
            sub_df = sub_df.append(top_d)
    
    ## Get the top K:
    top_k = lineup_df[lineup_df['position'] == 'K'].sort_values('points', ascending = False).head(1).reset_index().drop(columns = 'index')
    if top_k['player_id'][0] not in starters_set:
        current_starting_k = starter_df[starter_df['position'] == 'K'].reset_index()
        top_k['sub_for_player_name'] = current_starting_k['player_name'][0]
        top_k['sub_for_player_id'] = current_starting_k['player_id'][0]
        top_k['sub_for_player_points'] = current_starting_k['points'][0]
        sub_df = sub_df.append(top_k)
    
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