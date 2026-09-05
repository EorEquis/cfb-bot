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
    df = get_matches()

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


# Enrich the latest match with each player's prior history and match highlights.
def get_latest_match_with_history():
    df = get_matches()

    latest_match_id = df["MatchID"].max()
    # Exclude the current match so comparisons use only prior results.
    previous_df = df[df["MatchID"] < latest_match_id].copy()

    match_data = get_latest_match_data()

    for group in match_data["Groups"]:
        for player in group["Players"]:
            name = player["Player"]

            history = previous_df[
                previous_df["Player"] == name
            ].sort_values("MatchID")

            player["Previous Performance"] = None
            player["Performance Change"] = None
            player["Previous Matches"] = len(history)
            player["Previous Group Wins"] = 0
            player["Previous Match Wins"] = 0

            if not history.empty:
                previous = history.iloc[-1]

                previous_performance = float(
                    previous["Match Performance"]
                )

                player["Previous Performance"] = previous_performance

                player["Performance Change"] = round(
                    player["Match Performance"] - previous_performance,
                    2
                )

                player["Previous Group Wins"] = int(
                    (history["Group Winner"] == 1).sum()
                )

                player["Previous Match Wins"] = int(
                    (history["Match Winner"] == 1).sum()
                )

    # Flatten the grouped player list so match-wide highlights can be identified.
    all_players = [
        player
        for group in match_data["Groups"]
        for player in group["Players"]
    ]

    players_with_change = [
        player
        for player in all_players
        if player["Performance Change"] is not None
    ]

    highlights = {}

    if players_with_change:
        highlights["Biggest Improvement"] = max(
            players_with_change,
            key=lambda p: p["Performance Change"]
        )

        highlights["Biggest Decline"] = min(
            players_with_change,
            key=lambda p: p["Performance Change"]
        )

    highlights["Best Performance"] = max(
        all_players,
        key=lambda p: p["Match Performance"]
    )

    highlights["Worst Performance"] = min(
        all_players,
        key=lambda p: p["Match Performance"]
    )

    match_data["Highlights"] = highlights

    return match_data


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


# Build the statistical profile used by the /player command.
def get_player_profile(player_name):
    matches_df = get_matches()
    players_df = get_players()

    # Match player names case-insensitively to tolerate harmless spacing/case differences.
    player_rows = matches_df[
        matches_df["Player"].str.strip().str.lower()
        == player_name.strip().lower()
    ].copy()

    player_record = players_df[
        players_df["Player Name"].str.strip().str.lower()
        == player_name.strip().lower()
    ]

    current_index = None

    if not player_record.empty:
        value = player_record.iloc[0]["Normalized CFB Index"]

        if pd.notna(value):
            current_index = float(value)

    # A player can exist in the Players sheet before recording a match.
    if player_rows.empty:
        return {
            "Matches Played": 0,
            "Total Points": 0,
            "Group Wins": 0,
            "Match Wins": 0,
            "Current Index": current_index,
            "Recent Performance": None
        }

    player_rows = player_rows.sort_values(
        by=["Match Date", "MatchID"]
    )

    recent_performance = player_rows.iloc[-1]["Match Performance"]

    return {
        "Matches Played": len(player_rows),
        "Total Points": float(
            player_rows["Player Points"].fillna(0).sum()
        ),
        "Group Wins": int(
            player_rows["Group Winner"].fillna(0).sum()
        ),
        "Match Wins": int(
            player_rows["Match Winner"].fillna(0).sum()
        ),
        "Current Index": current_index,
        "Recent Performance": (
            float(recent_performance)
            if pd.notna(recent_performance)
            else None
        )
    }


# Read the Players worksheet as a pandas DataFrame.
def get_players():
    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet=Players"
    )

    return pd.read_csv(url)


# Build the compact player-history dataset supplied to the /power AI prompt.
def get_power_data(player_names):
    matches_df = get_matches()
    players_df = get_players()

    players = []

    for name in player_names:
        history = matches_df[
            matches_df["Player"] == name
        ].sort_values("MatchID")

        player_record = players_df[
            players_df["Player Name"].str.strip().str.lower()
            == name.strip().lower()
        ]

        normalized_index = None

        if not player_record.empty:
            value = player_record.iloc[0]["Normalized CFB Index"]

            if pd.notna(value):
                normalized_index = float(value)

        # Limit recent form to the last three recorded Match Performance values.
        recent_performances = (
            history["Match Performance"]
            .dropna()
            .tail(3)
            .tolist()
        )

        players.append({
            "Player": name,
            "Normalized CFB Index": normalized_index,
            "Matches Played": len(history),
            "Total Points": float(
                history["Player Points"].fillna(0).sum()
            ),
            "Group Wins": int(
                history["Group Winner"].fillna(0).sum()
            ),
            "Match Wins": int(
                history["Match Winner"].fillna(0).sum()
            ),
            "Recent Performances": [
                float(value)
                for value in recent_performances
            ]
        })

    # The most recent recorded Match Winner is the current CFB holder.
    match_winners = matches_df[
        matches_df["Match Winner"] == 1
    ].sort_values("MatchID")

    current_holder = None

    if not match_winners.empty:
        current_holder = match_winners.iloc[-1]["Player"]

    return {
        "Players": players,
        "Current CFB Holder": current_holder
    }
    
   
# Build upcoming-match context and player history for the /preview AI prompt.
def get_preview_data(
    player_availability,
    match_date,
    location,
    tee_times
):
    df = get_matches()


    # Exclude the upcoming match and any future matches from player history.
    historical_df = df[
        pd.to_datetime(
            df["Match Date"],
            errors="coerce"
        ).dt.date < match_date
    ].copy()
    
    # Give the preview model explicit timing context for how imminent the match is.
    days_until_match = (match_date - date.today()).days

    players = []

# Preserve each player's IN/MAYBE status alongside their complete match history.
    for name, status in player_availability:
        history = historical_df[
            historical_df["Player"] == name
        ].sort_values("MatchID")

        appearances = []

        for _, row in history.iterrows():
            appearances.append({
                "Match ID": int(row["MatchID"]),
                "Match Date": str(row["Match Date"]),
                "Points": int(row["Player Points"]),
                "Match Performance": float(row["Match Performance"]),
                "Group Winner": bool(row["Group Winner"] == 1),
                "Match Winner": bool(row["Match Winner"] == 1)
            })

        players.append({
            "Player": name,
            "Availability": status.upper(),
            "Matches Played": len(appearances),
            "History": appearances
        })

    # Find the current holder of the CFB / Fuck Ball
    match_winners = df[df["Match Winner"] == 1].sort_values("MatchID")

    current_holder = None

    if not match_winners.empty:
        current_holder = match_winners.iloc[-1]["Player"]

    # Convert database time values into human-readable 12-hour display strings.
    formatted_tee_times = []

    for tee_time in tee_times:
        total_seconds = int(tee_time.total_seconds())

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        period = "AM" if hours < 12 else "PM"

        display_hour = hours % 12

        if display_hour == 0:
            display_hour = 12

        formatted_tee_times.append(
            f"{display_hour}:{minutes:02d} {period}"
        )
        
    return {
        "Match Date": str(match_date),
        "Days Until Match": days_until_match,
        "Location": location,
        "Tee Times": formatted_tee_times,
        "Number of Tee Times": len(formatted_tee_times),
        "Maximum Groups": len(formatted_tee_times),
        "Maximum Players": len(formatted_tee_times) * 4,
        "Players IN": sum(
            status == "in"
            for _, status in player_availability
        ),
        "Players MAYBE": sum(
            status == "maybe"
            for _, status in player_availability
        ),
        "Field Status": (
            "Players marked IN are the current field. "
            "Players marked MAYBE are possible additions and are not currently in the field."
        ),
        "Players": players,
        "Current CFB Holder": current_holder
    }

