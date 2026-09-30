###################################################
# (RE)ASSIGNS chartLineColor TO EVERY TEAM IN EVERY
# team_data DOCUMENT, FROM EACH TEAM'S OWN LOGO
#
# update_mongodb.py does this itself whenever it adds a team to a season, so this is only needed
# for seasons farmed before it did - or after changing the color-picking rules in
# app/lib/chart_line_color.py, since it recomputes every season from scratch rather than skipping
# teams that already have a color. That makes a re-run always safe, and it's cheap: ~165 unique
# logos, each measured once.
#
# Run from the repo root as a module so `from app.constants ...` resolves:
#     python -m app.scripts.backfill_chart_line_color                      # every season
#     python -m app.scripts.backfill_chart_line_color 19891990             # just one season
#     python -m app.scripts.backfill_chart_line_color 19891990 --dry-run   # print, write nothing
###################################################

import argparse

from dotenv import load_dotenv

load_dotenv()

from app.constants import mongo_db_constants as mongo
from app.lib.chart_line_color import recolor_season


def parse_args():
    parser = argparse.ArgumentParser(description="Assign each team's chart line color from its logo.")
    parser.add_argument(
        "season_id",
        type=int,
        nargs="?",
        default=None,
        help="Restrict the run to a single seasonId (e.g. 19891990). If omitted, every season.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the colors without writing them.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    collection_team_data = mongo.client[mongo.DB_NAME_NHL_STATS][mongo.COLLECTION_TEAM_DATA]

    if args.season_id is not None:
        season_ids = [args.season_id]
    else:
        season_ids = sorted(collection_team_data.distinct("seasonId"))

    team_count = 0
    for season_id in season_ids:
        colors = recolor_season(collection_team_data, season_id, dry_run=args.dry_run)
        team_count += len(colors)
        print(f"{season_id}: " + " ".join(f"{abbrev}={color}" for abbrev, color in sorted(colors.items())))

    verb = "Would color" if args.dry_run else "Colored"
    print(f"\n{verb} {team_count} team(s) across {len(season_ids)} season(s).")


if __name__ == "__main__":
    main()
