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
