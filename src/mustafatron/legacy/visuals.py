import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
from espn_api.football import League

from mustafatron.identity import load_managers
from mustafatron.rules import load_rules
from mustafatron.legacy import data_utils as du


def short_name(team_owner: str) -> str:
    """Chart label for an ESPN owner name ("Matthew Albert" -> "Matt A."), from data/manual/managers.yml."""
    return load_managers().by_name(team_owner.split(', ')[0]).short_name

def biggest_steals_chart(draft_df: pd.DataFrame, week_number: int,
                         n_steals_to_plot: int = 10,
                         steals_after_rd: int = load_rules().draft_review.steals_after_round,
                         bar_color = '#31a354'): # '#998ec3' - purple
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
                                    color= bar_color,
                                    legend = None)
    ax.set_ylabel('')
    ax.set_xlabel('', fontsize=10) # 'Points Above Expected'
    plt.yticks(fontsize=7)
    plt.xticks(fontsize=10)
    plt.title(f"Biggest Steals after Rd. {steals_after_rd}\nThrough Week {week_number}", fontsize=10)
    plt.savefig(f'output/plots/biggest-steals-week-{week_number}.png', dpi=300, bbox_inches='tight')


def biggest_busts_chart(draft_df: pd.DataFrame, week_number: int,
                        n_busts_to_plot: int = 10,                        
                        busts_lte_rd: int = load_rules().draft_review.busts_through_round,
                        bar_color = '#de2d26'): # '#f1a340' - orange
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
                                    color = bar_color,
                                    legend = None)
    ax.set_ylabel('')
    ax.set_xlabel('', fontsize=10) # 'Points Above Expected'
    plt.yticks(fontsize=7)
    plt.xticks(fontsize=10)
    plt.title(f"Biggest Busts of Rds. 1 - {busts_lte_rd}\nThrough Week {week_number}", fontsize=10)
    plt.savefig(f'output/plots/biggest-busts-week-{week_number}.png', dpi=300, bbox_inches='tight')


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

    heatmap_df = weekly_and_overall_records_df.pivot(index = ["team"], columns = "week", values="win_pct_week")
    labels_df  = weekly_and_overall_records_df.pivot(index = ["team"], columns = "week", values="label")

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
    ax.set_title('All-Play Records by Week')
    plt.ylabel('')
    plt.savefig(f'output/plots/record-vs-league-week-{week}.png', dpi=300, bbox_inches='tight')


## Barplot of records above and below expected based on records vs. entire league 
def luckiest_records_chart(weekly_scores_df, week,
                           lucky_color = 'tab:green', # '#998ec3' - purple
                           unlucky_color = 'tab:red'): # '#f1a340' - orange
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
    palette = {'Red': unlucky_color, 
            'Green': lucky_color
            }
    sns.set_style('darkgrid')
    ax = sns.barplot(data = luckiest_records, y = "team", x = "win_pct_over_expected",
                    hue = "color", palette = palette)
    ax.legend_.remove()
    ax.set_title(f'Luckiest Records in the League Through Week {week}', fontsize = 14)
    plt.ylabel('')
    plt.xlabel('Actual Win Pct. Minus All-Play Win Pct.')
    plt.savefig(f'output/plots/luckiest-records-week-{week}.png', dpi=300, bbox_inches='tight')


def number_trades_acquisition_chart(league, acquisition_type):
    """Gather data on number of trades per team, make a chart of it, and save it.

    Args:
        league (League): ESPN fantasy league
        acquisition_type (str): either "trades" or "acquisitions"
    """
    teams = []
    owners = []
    trades = []
    acquisitions = []
    for team in league.teams:
        teams.append(team.team_name)
        owners.append(team.owner)
        trades.append(team.trades)
        acquisitions.append(team.acquisitions)

    trades_df = pd.DataFrame({'team': teams, 'owner': owners, 'trades': trades, 'acquisitions': acquisitions})
    trades_df.sort_values(acquisition_type, ascending=True).plot(kind='barh', x = 'owner', y = acquisition_type,
                                                     title=f'Number of {acquisition_type.title()} by Owner', legend = False)
    plt.xlabel('')
    plt.ylabel('')
    plt.savefig(f'output/plots/number-of-{acquisition_type}.png', dpi=300, bbox_inches='tight')


def best_worst_trade_chart(trade_eval_df, best_or_worst):
    """plot the best or worst trades based on the evaluations done in data_utils.

    Args:
        trade_eval_df (_type_): DataFrame from du.get_trade_evaluations_df
        best_or_worst (str): either "best" or "worst"
    """
    trade_eval_df['label'] = trade_eval_df.apply(lambda x:
        f"{x['team'].owner}\ntrade {', '.join([p.name for p in x['players_lost']])}\nfor {', '.join([p.name for p in x['players_added']])}"
        ,axis = 1)
    if best_or_worst == 'best':
        trade_eval_df.sort_values('point_diff',ascending=False).head().sort_values('point_diff').plot(kind='barh',
            x='label', y='point_diff', title='Best Trades of the Year', legend=False)
    elif best_or_worst == 'worst':
        trade_eval_df.sort_values('point_diff').head().sort_values('point_diff', ascending=False).plot(kind='barh',
            x='label', y='point_diff', title='Worst Trades of the Year', legend=False)
    plt.ylabel('')
    plt.xlabel('ROS Value for Roster')
    plt.savefig(f'output/plots/{best_or_worst}-trades.png', dpi=300, bbox_inches='tight')
