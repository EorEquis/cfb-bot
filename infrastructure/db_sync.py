###################
# Created : 2026-09-12 GB
# Purpose : Mirrors authoritative calculated CFB data from Google Sheets
#           into the local MySQL database.
# Notes   : The spreadsheet remains the calculation authority.
###################

import os

import infrastructure.sheets as sheets
import mysql.connector
import pandas as pd

from db._db import execute_query

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")

SPREADSHEET_ID = os.getenv("CFB_SHEET_ID")


def _clean_number(value):
    if pd.isna(value):
        return None

    return float(value)


def _clean_int(value):
    if pd.isna(value):
        return None

    return int(value)


def _read_benefits():
    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet=Benefits"
    )

    df = pd.read_csv(url)

    return df.dropna(
        subset=["Benefit"]
    ).copy()


class MatchIDMismatchError(ValueError):
    pass


def sync_db():
    matches_df = sheets.get_matches()
    players_df = sheets.get_players()
    benefits_df = _read_benefits()

    connection = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )

    cursor = None

    try:
        connection.start_transaction()
        cursor = connection.cursor()

        # ---------- Load database lookup values ----------

        valid_player_ids = {
            row["id"]
            for row in execute_query(
                """
                SELECT id
                FROM players
                """
            )
        }

        match_rows = execute_query(
            """
            SELECT
                id,
                match_date
            FROM matches
            """
        )

        valid_match_ids = {
            row["id"]
            for row in match_rows
        }

        match_ids_by_date = {
            row["match_date"]: row["id"]
            for row in match_rows
        }

        # ---------- Validate spreadsheet match IDs ----------

        spreadsheet_matches = (
            matches_df[["MatchID", "Match Date"]]
            .dropna(subset=["MatchID", "Match Date"])
            .drop_duplicates()
        )

        for _, row in spreadsheet_matches.iterrows():
            match_id = int(row["MatchID"])
            match_date = pd.to_datetime(
                row["Match Date"]
            ).date()

            database_match_id = match_ids_by_date.get(
                match_date
            )

            if (
                database_match_id is not None
                and match_id != database_match_id
            ):
                raise MatchIDMismatchError(
                    f"Spreadsheet MatchID mismatch for {match_date}: "
                    f"spreadsheet={match_id}, "
                    f"database={database_match_id}"
                )
                
        # ---------- Build spreadsheet player mapping ----------

        player_ids_by_name = {}

        for _, row in players_df.iterrows():
            player_id = _clean_int(
                row["Player ID"]
            )

            if player_id is None:
                continue

            player_name = str(
                row["Player Name"]
            ).strip()

            if player_id not in valid_player_ids:
                raise ValueError(
                    f"Spreadsheet Player ID {player_id} "
                    f"does not exist in database"
                )

            player_key = player_name.lower()

            if player_key in player_ids_by_name:
                raise ValueError(
                    f"Duplicate player name in Players worksheet: "
                    f"{player_name}"
                )

            player_ids_by_name[player_key] = player_id

        # ---------- Players ----------

        for _, row in players_df.iterrows():
            player_id = _clean_int(
                row["Player ID"]
            )

            if player_id is None:
                continue

            if player_id not in valid_player_ids:
                raise ValueError(
                    f"Spreadsheet Player ID {player_id} "
                    f"does not exist in database"
                )

            normalized_index = _clean_number(
                row["Normalized CFB Index"]
            )

            cursor.execute(
                """
                UPDATE players
                SET normalized_cfb_index = %s
                WHERE id = %s
                """,
                (
                    normalized_index,
                    player_id
                )
            )

        # ---------- Match groups ----------

        for (match_id, group_id), group_df in matches_df.groupby(
            ["MatchID", "GroupID"]
        ):
            match_id = int(match_id)
            group_id = int(group_id)

            if match_id not in valid_match_ids:
                raise ValueError(
                    f"Spreadsheet MatchID {match_id} "
                    f"does not exist in database"
                )

            players_in_group = _clean_int(
                group_df["Players in Group"].iloc[0]
            )

            total_points = _clean_int(
                group_df["Total Points"].iloc[0]
            )

            ending_hole = _clean_int(
                group_df["Ending Hole"].iloc[0]
            )

            cursor.execute(
                """
                INSERT INTO match_groups
                    (
                        match_id,
                        group_id,
                        players_in_group,
                        total_points,
                        ending_hole
                    )
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    players_in_group = VALUES(players_in_group),
                    total_points = VALUES(total_points),
                    ending_hole = VALUES(ending_hole)
                """,
                (
                    match_id,
                    group_id,
                    players_in_group,
                    total_points,
                    ending_hole
                )
            )

        # ---------- Match results ----------

        for _, row in matches_df.iterrows():
            match_id = _clean_int(
                row["MatchID"]
            )

            group_id = _clean_int(
                row["GroupID"]
            )

            if match_id is None or group_id is None:
                continue

            if match_id not in valid_match_ids:
                raise ValueError(
                    f"Spreadsheet MatchID {match_id} "
                    f"does not exist in database"
                )

            if pd.isna(row["Player"]):
                continue

            player_name = str(
                row["Player"]
            ).strip()

            player_id = player_ids_by_name.get(
                player_name.lower()
            )

            if player_id is None:
                raise ValueError(
                    f"Match player not found in Players worksheet: "
                    f"{player_name}"
                )

            player_points = _clean_int(
                row["Player Points"]
            )

            pre_match_index = _clean_number(
                row["Pre-Match Index"]
            )

            match_performance = _clean_number(
                row["Match Performance"]
            )

            net_handicap_credits = _clean_number(
                row["Net Handicap Credits"]
            )

            group_winner = (
                1
                if row["Group Winner"] == 1
                else 0
            )

            match_winner = (
                1
                if row["Match Winner"] == 1
                else 0
            )

            cursor.execute(
                """
                INSERT INTO match_results
                    (
                        match_id,
                        group_id,
                        player_id,
                        player_points,
                        group_winner,
                        match_winner,
                        pre_match_index,
                        match_performance,
                        net_handicap_credits
                    )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    group_id = VALUES(group_id),
                    player_points = VALUES(player_points),
                    group_winner = VALUES(group_winner),
                    match_winner = VALUES(match_winner),
                    pre_match_index = VALUES(pre_match_index),
                    match_performance = VALUES(match_performance),
                    net_handicap_credits = VALUES(net_handicap_credits)
                """,
                (
                    match_id,
                    group_id,
                    player_id,
                    player_points,
                    group_winner,
                    match_winner,
                    pre_match_index,
                    match_performance,
                    net_handicap_credits
                )
            )

        # ---------- Benefits ----------

        for _, row in benefits_df.iterrows():
            benefit_name = str(
                row["Benefit"]
            ).strip()

            description = str(
                row["Description"]
            ).strip()

            handicap_credits = _clean_number(
                row["Handicap Credits"]
            )

            cursor.execute(
                """
                INSERT INTO benefits
                    (
                        benefit_name,
                        description,
                        handicap_credits,
                        active
                    )
                VALUES (%s, %s, %s, TRUE)
                ON DUPLICATE KEY UPDATE
                    description = VALUES(description),
                    handicap_credits = VALUES(handicap_credits),
                    active = TRUE
                """,
                (
                    benefit_name,
                    description,
                    handicap_credits
                )
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()


if __name__ == "__main__":
    sync_db()
    print("CFB database sync complete.")