import argparse
from groupy.client import Client
from espn_api.football import League

import groupme.groupme_utils as gm
from groupme.config import TOKEN, GROUP_ID

from viz_reports.data.configs import keys
import viz_reports.image_utils as reports

## Command line arguments
parser = argparse.ArgumentParser(
    description='Run MustafaTron 3000 to create and/or post weekly fantasy reports.')
parser.add_argument('-w', '--week', type=int, metavar='', required=True, help='Week number')
parser.add_argument('-m', '--mode', type=str, metavar='', required=True,
                    help='Mode (either "create", "post", or "both")')
args = parser.parse_args()

### Establish ESPN API connection
league = League(league_id=keys['league_id'], year=2022,
                espn_s2=keys['espn_s2'],
                swid=keys['swid'])

### Establish connection to GroupMe group/bot
client = Client.from_token(TOKEN)
group = client.groups.get(GROUP_ID)
bot = client.bots.list()[0]

def create_visuals(week):
    reports.save_all_visuals(league=league, week=week)

def post_weekly_reports(week):
    gm.post_all_reports(week=week)

if __name__ == "__main__":
    if args.mode == 'create':
        create_visuals(args.week)
    elif args.mode == 'post':
        post_weekly_reports(args.week)
    elif args.mode == 'both':
        create_visuals(args.week)
        post_weekly_reports(args.week)
    else:
        raise ValueError("Mode should be one of 'create', 'post', or 'both'.")