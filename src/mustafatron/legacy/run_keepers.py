#%%
import os
from datetime import datetime

import pandas as pd

from espn_api.football import League
from mustafatron.config import get_settings
from mustafatron.legacy import data_utils as du

#%%

settings = get_settings()
cookies = settings.espn_cookies()
league = League(league_id=settings.league_id, year=2025,
                espn_s2=cookies['espn_s2'],
                swid=cookies['swid'])


team_owners = []
player_ids = []
player_names = []
for team in league.teams:
    for player in team.roster:
        owner = ', '.join([owner['firstName'] + ' ' + owner['lastName'] for owner in team.owners])
        team_owners.append(owner)
        player_names.append(player.name)
        player_ids.append(player.playerId)
rosters_df = pd.DataFrame({'team_owner': team_owners, 'player_id': player_ids, 'player_name': player_names})

#%%
draft_df = du.get_draft_df(league)


# %%
keepers = rosters_df[['player_id', 'player_name', 'team_owner']].merge(draft_df[
    draft_df['round_num'] > 3][['player_id', 'round_num', 'round_pick', 'team_name']], on = 'player_id')

# %%
os.makedirs('output/keepers', exist_ok=True)
keepers.to_csv(f"output/keepers/keepers-{datetime.now().strftime('%Y-%m-%d')}.csv", index=False)
# %%
