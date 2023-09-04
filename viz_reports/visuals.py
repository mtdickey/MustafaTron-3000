import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression

import data_utils as du

def biggest_steals_chart(draft_df: pd.DataFrame, week_number: int,
                         n_steals_to_plot: int = 10,
                         steals_after_rd: int = 1):
    """Create a chart of the biggest steals from the draft, as defined by points above/below expected from
     a linear regression modeling fantasy points compared to position avg. as a factor of draft pick.

    Args:
        draft_df (pd.DataFrame): DataFrame of draft results from data_utils.get_draft_df
        week_number (int): Week number for the fantasy season.
        n_steals_to_plot (int, optional): Number of players to include. Defaults to 10.
        steals_after_rd (int, optional): Number of initial rounds to exclude to define a player 
            as a "steal". Defaults to 1.
    """
    ## Very basic model to determine "expected points" based on position and draft position
    reg = LinearRegression().fit(np.array(draft_df['overall_pick']).reshape(-1, 1),
                                draft_df['points_above_avg'])

    draft_df['preds'] = reg.predict(np.array(draft_df['overall_pick']).reshape(-1, 1))
    draft_df['points_above_pred'] = draft_df['points_above_avg'] - draft_df['preds']

    ## Biggest steals plot
    biggest_steals_after_rd = (draft_df[draft_df['round_num'] > steals_after_rd]
                                .nlargest(n_steals_to_plot, 'points_above_pred', keep = 'all')
                                .sort_values('points_above_pred'))
    biggest_steals_after_rd['player_name_short'] = biggest_steals_after_rd['player_name'].apply(lambda x: x[0] + '. ' + x.split(' ')[1] if not x.endswith('D/ST') else x)
    biggest_steals_after_rd['owner_name_short'] = biggest_steals_after_rd['team_owner'].apply(lambda x: x[0] + '. ' + x.split(' ')[1])
    biggest_steals_after_rd['x_label'] = biggest_steals_after_rd['player_name_short'] + '\n' + biggest_steals_after_rd['owner_name_short'] + ' Pick #' + biggest_steals_after_rd['overall_pick'].astype(str)
    plt.figure(figsize=(21,16))
    plt.style.use('fivethirtyeight')
    ax = biggest_steals_after_rd.plot(kind='barh', y = 'points_above_pred', x = 'x_label',
                                    color= '#998ec3', #'#31a354',
                                    legend = None)
    ax.set_ylabel('')
    ax.set_xlabel('', fontsize=10) # 'Points Above Expected'
    plt.yticks(fontsize=7)
    plt.xticks(fontsize=10)
    plt.title(f"Biggest Steals after Rd. {steals_after_rd}\nThrough Week {week_number}", fontsize=10)
    plt.savefig(f'viz_reports/data/plots/biggest-steals-week-{week_number}.png')


def biggest_busts_chart(draft_df: pd.DataFrame, week_number: int,
                        n_busts_to_plot: int = 10,                        
                        busts_lte_rd: int = 4):
    """Create a chart of the biggest busts from the draft, as defined by points above/below expected from
     a linear regression modeling fantasy points compared to position avg. as a factor of draft pick.

    Args:
        draft_df (pd.DataFrame): DataFrame of draft results from data_utils.get_draft_df
        week_number (int): Week number for the fantasy season
        n_busts_to_plot (int, optional): Number of players to include. Defaults to 10.
        busts_lte_rd (int, optional): Last (maximum) round that a player can be called a 
            a "bust". Defaults to 4.
    """
    ## Very basic model to determine "expected points" based on position and draft position
    reg = LinearRegression().fit(np.array(draft_df['overall_pick']).reshape(-1, 1),
                                draft_df['points_above_avg'])
    draft_df['preds'] = reg.predict(np.array(draft_df['overall_pick']).reshape(-1, 1))
    draft_df['points_above_pred'] = draft_df['points_above_avg'] - draft_df['preds']

    ## Biggest busts plot
    biggest_busts_first_rds = (draft_df[draft_df['round_num'] <= busts_lte_rd]
                            .nsmallest(n_busts_to_plot, 'points_above_pred', keep = 'all')
                            .sort_values('points_above_pred', ascending = False))
    biggest_busts_first_rds['player_name_short'] = biggest_busts_first_rds['player_name'].apply(lambda x: x[0] + '. ' + x.split(' ')[1])
    biggest_busts_first_rds['owner_name_short'] = biggest_busts_first_rds['team_owner'].apply(lambda x: x[0] + '. ' + x.split(' ')[1])
    biggest_busts_first_rds['x_label'] = biggest_busts_first_rds['player_name_short'] + '\n' + biggest_busts_first_rds['owner_name_short'] + ' Pick #' + biggest_busts_first_rds['overall_pick'].astype(str)
    plt.figure(figsize=(21,16))
    plt.style.use('fivethirtyeight')
    ax = biggest_busts_first_rds.plot(kind='barh', y = 'points_above_pred', x = 'x_label',
                                    color = '#f1a340', #'#de2d26',
                                    legend = None)
    ax.set_ylabel('')
    ax.set_xlabel('Points Above Expected', fontsize=10)
    plt.yticks(fontsize=7)
    plt.xticks(fontsize=10)
    plt.title(f"Biggest Busts of Rds. 1 - 4\nThrough Week {week_number}", fontsize=10)
    plt.savefig(f'viz_reports/data/plots/biggest-busts-week-{week_number}.png')


def total_points_left_on_bench_chart(lineup_df: pd.DataFrame, week: int):
    """Bar chart of "points left on the table" by team based on not starting 
     the right people

    Args:
        lineup_df (pd.DataFrame): DataFrame of all lineups and scores for each team/week
        week (int): Week number
    """

    ### Gather the subs that should've been made
    unique_week_team_lineup = lineup_df.groupby(['team_name', 'week']).size().reset_index().drop(columns = 0)
    sub_dfs = []
    for i, row in unique_week_team_lineup.iterrows():
        sub_lineup_df = lineup_df[(lineup_df['week'] == row['week']) & 
                                (lineup_df['team_name'] == row['team_name'])]
        sub_df = du.get_optimal_subs(sub_lineup_df)
        sub_dfs.append(sub_df)
    full_sub_df = pd.concat(sub_dfs).reset_index()
    full_sub_df['potential_extra_points'] = full_sub_df['points'] - full_sub_df['sub_for_player_points']

    ### Visualize missed opportunities by team
    subs_pts_by_team = full_sub_df.groupby('team_owner').agg({'potential_extra_points': sum,
                                        'index': len}).rename(columns = {'index': 'n_subs'}).reset_index()
    subs_pts_by_team['bar_label'] = subs_pts_by_team['team_owner'] + ' (' + subs_pts_by_team['n_subs'].astype(str)  + ')'

    ax = (subs_pts_by_team.sort_values(by='potential_extra_points').plot(x = 'bar_label', y = 'potential_extra_points',
                                                        title = f'Extra Points Left on Bench Through Week {week}\n(Number of substitutions in parens.)', 
                                                        color = '#f1a340',
                                                        kind = 'barh', legend = None))
    ax.title.set_size(16)
    ax.set_xlabel("")
    ax.set_ylabel("")
    plt.savefig(f'viz_reports/data/plots/total-points-on-bnch-week-{week}.png')

def if_only_wouldve_started_owner_chart(lineup_df: pd.DataFrame, week: int,
                                         n_players_per_team: int = 2):
    """Create bar chart of the top X players that each team should have started throughout the year 

    Args:
        lineup_df (pd.DataFrame): DataFrame of all lineups and scores for each team/week
        week (int): Week number
        n_players_per_team (int, optional): Number of players to plot for each team. Defaults to 2.
    """
    ### Gather the subs that should've been made
    unique_week_team_lineup = lineup_df.groupby(['team_name', 'week']).size().reset_index().drop(columns = 0)
    sub_dfs = []
    for i, row in unique_week_team_lineup.iterrows():
        sub_lineup_df = lineup_df[(lineup_df['week'] == row['week']) & 
                                (lineup_df['team_name'] == row['team_name'])]
        sub_df = du.get_optimal_subs(sub_lineup_df)
        sub_dfs.append(sub_df)
    full_sub_df = pd.concat(sub_dfs).reset_index()
    full_sub_df['potential_extra_points'] = full_sub_df['points'] - full_sub_df['sub_for_player_points']

    ### Create a grouped bar chart...  (or attempt)
    potential_points_by_team_and_player = (full_sub_df
                                        .groupby(['team_owner', 'player_name'])
                                        .agg({'potential_extra_points': sum}))

    top_n_subs_by_owner = (potential_points_by_team_and_player['potential_extra_points']
                        .groupby('team_owner', group_keys=False).nlargest(n_players_per_team).reset_index())

    top_n_subs_by_owner['owner_first_name'] = top_n_subs_by_owner['team_owner'].apply(lambda x: x.split(' ')[0] if x.split(' ')[0] != "Matthew" else
                                                                                                                f"Matt {x.split(' ')[1][0]}.")
    top_n_subs_by_owner['bar_label'] = top_n_subs_by_owner['owner_first_name'] + " would've started " + top_n_subs_by_owner['player_name']

    ax = top_n_subs_by_owner.sort_values(by = 'potential_extra_points').plot(y = 'potential_extra_points', x = 'bar_label',
                                                                            legend = None, kind = 'barh',
                                                                            color = '#f1a340',
                                                                            title = 'If only...')
    ax.set_xlabel("Potential extra points gained")
    ax.set_ylabel("")
    plt.savefig(f'viz_reports/data/plots/if-only-wouldve-started-owner-{week}.png')


def if_only_wouldve_started_chart(lineup_df: pd.DataFrame, week: int, top_n: int = 10):
    """Create bar chart of top X players that should have been started by a particular team through a given week of the season.

    Args:
        lineup_df (pd.DataFrame): DataFrame of all lineups and scores for each team/week
        week (int): Week number
        top_n (int, optional): Number of players to include in plot. Defaults to 10.
        """
    ### Gather the subs that should've been made
    unique_week_team_lineup = lineup_df.groupby(['team_name', 'week']).size().reset_index().drop(columns = 0)
    sub_dfs = []
    for i, row in unique_week_team_lineup.iterrows():
        sub_lineup_df = lineup_df[(lineup_df['week'] == row['week']) & 
                                (lineup_df['team_name'] == row['team_name'])]
        sub_df = du.get_optimal_subs(sub_lineup_df)
        sub_dfs.append(sub_df)
    full_sub_df = pd.concat(sub_dfs).reset_index()
    full_sub_df['potential_extra_points'] = full_sub_df['points'] - full_sub_df['sub_for_player_points']

    ### Top owner/player subs (and how many times)
    potential_points_by_team_and_player = (full_sub_df
                                        .groupby(['team_owner', 'player_name'])
                                        .agg({'potential_extra_points': sum,
                                                'index': len})
                                        .sort_values('potential_extra_points', ascending = False)
                                        .head(top_n).rename(columns = {'index': 'n_subs'}).reset_index())

    potential_points_by_team_and_player['owner_first_name'] = potential_points_by_team_and_player['team_owner'].apply(lambda x: x.split(' ')[0] if x.split(' ')[0] != "Matthew" else
                                                                                                                f"Matt {x.split(' ')[1][0]}.")
    potential_points_by_team_and_player['bar_label'] = (potential_points_by_team_and_player['owner_first_name'] + 
                                                        " would've started " + potential_points_by_team_and_player['player_name'] + 
                                                        ' (' + potential_points_by_team_and_player['n_subs'].astype(str) + ')')

    ax = (potential_points_by_team_and_player.sort_values(by = 'potential_extra_points')
        .plot(y = 'potential_extra_points', x = 'bar_label', legend = None, 
                color = '#f1a340',
                kind = 'barh', title = 'If only...'))
    ax.set_xlabel("Potential extra points gained")
    ax.set_ylabel("")
    plt.savefig(f'viz_reports/data/plots/if-only-wouldve-started-{week}.png')


def record_vs_league_chart(weekly_scores_df, week, heatmap_color = 'Greens'):
    """Make a heatmap of team's records against the entire league week to week (and overall) 

    Args:
        weekly_scores_df (pd.DataFrame): DataFrame of records/scores by week by team
        week (int): Week number
        heatmap_color (str): Color scale to use for heatmap
    """

    ## Create a DataFrame with the overall record across all weeks.
    overall_records = (weekly_scores_df.groupby('team').agg({'wins_in_week': np.sum,
                                                            'losses_in_week': np.sum,
                                                            'win_flg': np.sum})
                    .rename(columns = {'win_flg': 'actual_wins'})
                    .reset_index())
    
    ## Add columns for plot 
    overall_records['record_for_week'] = overall_records['wins_in_week'].astype(int).astype(str) + '-' + overall_records['losses_in_week'].astype(int).astype(str)
    overall_records['win_pct_week'] = overall_records['wins_in_week']/(overall_records['wins_in_week'] + overall_records['losses_in_week']*1.00)
    overall_records['actual_win_pct'] = overall_records['actual_wins']/(week*1.0)
    overall_records['actual_losses'] = (week*1.0)-overall_records['actual_wins']
    overall_records['win_pct_over_expected'] = overall_records['actual_win_pct'] - overall_records['win_pct_week']
    overall_records['week'] = 'Overall'
    overall_records['team_label'] = (overall_records['team'] + ' (' +
                                    overall_records['actual_wins'].astype(str) + '-' + 
                                    overall_records['actual_losses'].astype(str) +
                                    ')' )

    ## Restructure data for heatmap
    weekly_and_overall_records_df = (pd.concat([weekly_scores_df, overall_records])
                                    .reset_index(drop = True))
    weekly_and_overall_records_df['label'] = weekly_and_overall_records_df.apply(lambda x:
                                            x['result'] if x['week'] != 'Overall'
                                            else x['record_for_week'], axis = 1)

    heatmap_df = weekly_and_overall_records_df.pivot("team", "week", "win_pct_week")
    labels_df  = weekly_and_overall_records_df.pivot("team", "week", "label")

    ## Change index (sort by team with best overall pct first)
    sort_order = list(overall_records.sort_values('win_pct_week', ascending = False)['team'])
    heatmap_df.index = pd.CategoricalIndex(heatmap_df.index, categories= sort_order)
    heatmap_df.sort_index(level=0, inplace=True)
    labels_df.index = pd.CategoricalIndex(labels_df.index, categories= sort_order)
    labels_df.sort_index(level=0, inplace=True)

    ## Plot Heatmap
    fig, ax = plt.subplots()
    sns.set(font_scale=1.1)
    ax = sns.heatmap(heatmap_df, annot = labels_df, cmap=heatmap_color, fmt = '', annot_kws={"fontsize":8.5})
    ax.set_title('Records vs. Entire League by Week')
    plt.ylabel('')
    plt.savefig(f'viz_reports/data/plots/record-vs-league-week-{week}.png')


## Barplot of records above and below expected based on records vs. entire league 
def luckiest_records_chart(weekly_scores_df, week):
    """Create a barchart showing the team's records compare with what is expected from their
     winning percentage against the entire league each week

    Args:
        weekly_scores_df (pd.DataFrame): DataFrame of records/scores by week by team
        week (int): Week number
    """

    ## Create a DataFrame with the overall record across all weeks.
    overall_records = (weekly_scores_df.groupby('team').agg({'wins_in_week': np.sum,
                                                            'losses_in_week': np.sum,
                                                            'win_flg': np.sum})
                    .rename(columns = {'win_flg': 'actual_wins'})
                    .reset_index())
    
    ## Add columns for plot 
    overall_records['record_for_week'] = overall_records['wins_in_week'].astype(int).astype(str) + '-' + overall_records['losses_in_week'].astype(int).astype(str)
    overall_records['win_pct_week'] = overall_records['wins_in_week']/(overall_records['wins_in_week'] + overall_records['losses_in_week']*1.00)
    overall_records['actual_win_pct'] = overall_records['actual_wins']/(week*1.0)
    overall_records['actual_losses'] = (week*1.0)-overall_records['actual_wins']
    overall_records['win_pct_over_expected'] = overall_records['actual_win_pct'] - overall_records['win_pct_week']
    overall_records['week'] = 'Overall'
    overall_records['team_label'] = (overall_records['team'] + ' (' +
                                    overall_records['actual_wins'].astype(str) + '-' + 
                                    overall_records['actual_losses'].astype(str) +
                                    ')' )
    
    ### Get the luckiest records
    luckiest_records = overall_records.sort_values('win_pct_over_expected',
                                                ascending = False).copy()
    luckiest_records['color'] = luckiest_records['win_pct_over_expected'].apply(lambda x: 'Red' if x < 0 else 'Green')
    fig, ax = plt.subplots()
    palette = {'Red': '#f1a340',#'tab:red', 
            'Green': '#998ec3'#'tab:green'
            }
    sns.set_style('darkgrid')
    ax = sns.barplot(data = luckiest_records, y = "team", x = "win_pct_over_expected",
                    hue = "color", palette = palette)
    ax.legend_.remove()
    ax.set_title(f'Luckiest Records in the League Through Week {week}', fontsize = 14)
    plt.ylabel('')
    plt.xlabel('Actual Win Pct. Minus Overall Win Pct. vs. Entire League')
    plt.savefig(f'viz_reports/data/plots/luckiest-records-week-{week}.png')