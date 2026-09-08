###################
# Created : 2026-09-07 GB
# Purpose : Development test harness for the CFB bookie.
#           Reads completed match history and current normalized indexes from
#           Google Sheets, reads the upcoming match/field from MariaDB, and asks
#           OpenAI to price the current field with American moneyline odds.
# Notes   : Console output only. Does not write odds, wagers, or balances.
###################

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os

import mysql.connector
from openai import AsyncOpenAI

import sheets


MODEL = os.getenv("BOOKIE_MODEL", "gpt-5.6-sol")

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")

client = AsyncOpenAI()


# Open a MariaDB/MySQL connection using the bot's existing .env settings.
def get_db_connection():
    return mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )


# Return the next active match that has not finished yet.
# This intentionally mirrors the upcoming-match logic already used by the bot:
# an active match remains upcoming until its latest configured tee time passes.
def get_upcoming_match():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                id,
                match_date,
                location,
                tee_time_1,
                tee_time_2,
                tee_time_3,
                tee_time_4
            FROM matches
            WHERE active = TRUE
              AND TIMESTAMP(
                    match_date,
                    GREATEST(
                        COALESCE(tee_time_1, '00:00:00'),
                        COALESCE(tee_time_2, '00:00:00'),
                        COALESCE(tee_time_3, '00:00:00'),
                        COALESCE(tee_time_4, '00:00:00')
                    )
                  ) >= NOW()
            ORDER BY match_date
            LIMIT 1
            """
        )

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()


# Read the Players and Availability tables and return players currently IN.
# MAYBE/OUT players are intentionally excluded from the market for this test.
def get_current_field(match_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                p.id AS player_id,
                p.player_name,
                a.status
            FROM availability a
            INNER JOIN players p
                ON p.id = a.player_id
            WHERE a.match_id = %s
              AND p.active = TRUE
              AND a.status = 'in'
            ORDER BY p.player_name
            """,
            (match_id,),
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# Combine database field information with spreadsheet history/current indexes.
def build_bookie_data(match, field):
    completed_matches = sheets.get_completed_matches()
    current_players = sheets.get_players()

    player_data = []

    for db_player in field:
        name = db_player["player_name"]

        history = completed_matches[
            completed_matches["Player"].str.strip().str.lower()
            == name.strip().lower()
        ].sort_values("MatchID")

        player_row = current_players[
            current_players["Player Name"].str.strip().str.lower()
            == name.strip().lower()
        ]

        normalized_index = None

        if not player_row.empty:
            value = player_row.iloc[0]["Normalized CFB Index"]

            if value == value:
                normalized_index = float(value)

        appearances = []

        for _, row in history.iterrows():
            appearances.append(
                {
                    "match_id": int(row["MatchID"]),
                    "match_date": str(row["Match Date"]),
                    "player_points": int(row["Player Points"]),
                    "pre_match_index": float(row["Pre-Match Index"]),
                    "match_performance": float(row["Match Performance"]),
                    "group_winner": bool(row["Group Winner"] == 1),
                    "match_winner": bool(row["Match Winner"] == 1),
                }
            )

        player_data.append(
            {
                "player_id": db_player["player_id"],
                "player": name,
                "availability": db_player["status"].upper(),
                "normalized_cfb_index": normalized_index,
                "matches_played": len(appearances),
                "history": appearances,
            }
        )

    tee_times = [
        match["tee_time_1"],
        match["tee_time_2"],
        match["tee_time_3"],
        match["tee_time_4"],
    ]

    return {
        "upcoming_match": {
            "database_match_id": match["id"],
            "match_date": str(match["match_date"]),
            "location": match["location"],
            "tee_times": [
                str(value)
                for value in tee_times
                if value is not None
            ],
        },
        "field": player_data,
    }


# Describe the test bookie's job and provide only the data it may use.
def build_prompt(bookie_data):
    prompt = f"""
You are the CFB BOOKIE, the market maker for an imaginary CFB golf betting market.

Your job in this test is to set PRE-MATCH AMERICAN MONEYLINE ODDS for each player
currently marked IN for the upcoming match.

Use ONLY the supplied data.

WHAT YOU KNOW:
- Completed CFB match history for each player.
- Each player's current Normalized CFB Index.
- The currently announced field from the database.
- The upcoming match date/location/tee times.

HOW TO THINK:
- Higher Normalized CFB Index represents stronger current competitive strength.
- Historical Match Performance, points, group wins, match wins, and recent form
  are evidence about a player's ability to win.
- The historical sample may be absurdly small. This has never stopped us from drawing sweeping conclusions, 
  and it should not stop you. Use the available data seriously when setting odds, but do not apologize for the sample 
  size or dilute the bookie's confidence because of it. Two matches are enough for CFB Sports Network to commission a six-part 
  documentary; they are enough for you to hang a line.
- Feel free to snark or joke about the sample size in the short reason if appropriate
- Current Normalized CFB Index should be an important anchor, especially when
  historical sample sizes are small.
- Do NOT use handicap benefit credits or provisional offsets in this test.
- Do NOT invent injuries, course history, weather, player tendencies, or any
  information not supplied here.
- Price the players relative to the CURRENT FIELD, not relative to players who
  are not entered.
- Produce realistic bookmaker odds with a modest house margin rather than fair
  probabilities that sum to exactly 100%.
- Use standard American odds notation, including an explicit + sign on positive
  odds.
- Do NOT assume or infer any player's gender. Use the player's name or gender-neutral language.

OUTPUT:
First print one short sentence identifying the upcoming match.

Then print one line per player, ordered from shortest odds / favorite to longest:

PLAYER | ODDS | IMPLIED % | SHORT REASON

Keep each reason concise and tied directly to the supplied data.

End with:
BOOK PERCENTAGE: XX.X%

DATA:
{json.dumps(bookie_data, indent=2, default=str)}
""".strip()

    return prompt


async def generate_odds(bookie_data):
    prompt = build_prompt(bookie_data)

    response = await client.responses.create(
        model=MODEL,
        input=prompt,
    )

    return response.output_text


async def main():
    print("=" * 72)
    print("CFB BOOKIE TEST")
    print("=" * 72)

    print("\n[1/4] Reading upcoming match from database...")
    match = get_upcoming_match()

    if match is None:
        print("No upcoming active match found.")
        return

    print(
        f"Found match {match['id']}: "
        f"{match['match_date']} — {match['location']}"
    )

    print("\n[2/4] Reading current IN field from players/availability...")
    field = get_current_field(match["id"])

    if not field:
        print("No players are currently marked IN for this match.")
        return

    print(f"{len(field)} player(s) currently IN:")
    for player in field:
        print(f"  - {player['player_name']}")

    print("\n[3/4] Reading completed history and normalized indexes from Google Sheets...")
    bookie_data = build_bookie_data(match, field)

    for player in bookie_data["field"]:
        index_text = (
            f"{player['normalized_cfb_index']:.2f}"
            if player["normalized_cfb_index"] is not None
            else "N/A"
        )
        print(
            f"  - {player['player']}: "
            f"index={index_text}, "
            f"matches={player['matches_played']}"
        )

    print(f"\n[4/4] Asking {MODEL} to price the field...\n")

    odds = await generate_odds(bookie_data)

    print("=" * 72)
    print("TAN CITY SPORTSBOOK — TEST MARKET")
    print("=" * 72)
    print(odds)
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
