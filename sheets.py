###################
# Created : 2026-09-02 GB
# Purpose : Reads CFB match and player data from Google Sheets and transforms
#           it into structured data used by bot commands and AI-generated
#           previews, power rankings, player profiles, and match wrapups.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import os
import pandas as pd

from datetime import date


# Read the Google Sheets document ID from environment configuration.
SPREADSHEET_ID = os.getenv("CFB_SHEET_ID")

# Return all rows belonging to the most recently recorded match.
def get_latest_match():
    df = get_completed_matches()

    latest_match_id = df["MatchID"].max()

    return df[df["MatchID"] == latest_match_id].copy()


# Build the latest match into groups and player-level results for wrapup output.
def get_latest_match_data():
    df = get_latest_match()

    match_id = int(df["MatchID"].iloc[0])
    match_date = str(df["Match Date"].iloc[0])

    # Reconstruct the match into its group structure.
    groups = []

    for group_id, group_df in df.groupby("GroupID"):
        players = []

        for _, row in group_df.iterrows():
            players.append({
                "Player": row["Player"],
                "Points": int(row["Player Points"]),
                "Pre-Match Index": float(row["Pre-Match Index"]),
                "Match Performance": float(row["Match Performance"]),
                "Group Winner": bool(row["Group Winner"] == 1),
                "Match Winner": bool(row["Match Winner"] == 1),
            })

        groups.append({
            "Group": int(group_id),
            "Players in Group": int(group_df["Players in Group"].iloc[0]),
            "Total Points": int(group_df["Total Points"].iloc[0]),
            "Ending Hole": int(group_df["Ending Hole"].iloc[0]),
            "Players": players
        })

    return {
        "Match ID": match_id,
        "Match Date": match_date,
        "Groups": groups
    }


# Read the Matches worksheet as a pandas DataFrame.
def get_matches():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/"
        f"gviz/tq?tqx=out:csv&sheet=Matches"
    )

    df = pd.read_csv(url)

    # Drop completely empty columns
    df = df.dropna(axis=1, how="all")

    return df


# Return only matches whose result rows are complete and internally valid.
def get_completed_matches():
    df = get_matches()

    required_columns = [
        "Player Points",
        "Ending Hole",
        "Match Performance"
    ]

    complete_match_ids = []

    for match_id, match_df in df.groupby("MatchID"):
        has_complete_results = (
            match_df[required_columns].notna().all().all()
        )
        has_one_match_winner = (
            (match_df["Match Winner"] == 1).sum() == 1
        )

        if has_complete_results and has_one_match_winner:
            complete_match_ids.append(match_id)

    return df[
        df["MatchID"].isin(complete_match_ids)
    ].copy()


# Read the Players worksheet as a pandas DataFrame.
def get_players():
    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet=Players"
    )

    return pd.read_csv(url)


