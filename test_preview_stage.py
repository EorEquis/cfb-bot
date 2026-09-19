###################
# Created : 2026-09-17 GB
# Purpose : Tests staged generation of the CFB Sports Network pre-match preview.
#           Generates preview text and stores it without sending to Discord.
# Notes   : Development test harness for staged preview generation.
#           Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 8
#           OpenAI model/version: GPT-5.6 Sol
###################

import asyncio
import mysql.connector
import os

from datetime import datetime
from dotenv import load_dotenv


load_dotenv()

from preview import generate_preview



MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_PORT = int(os.getenv("MYSQL_PORT"))
MYSQL_USER = os.getenv("MYSQL_USER")



def get_db_connection():
    return mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )


def load_preview_context():
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT
                m.id,
                m.match_date,
                m.location,
                m.tee_time_1,
                m.tee_time_2,
                m.tee_time_3,
                m.tee_time_4,
                m.special_rule
            FROM matches m
            WHERE m.active = TRUE
            AND TIMESTAMP(
                m.match_date,
                GREATEST(
                    COALESCE(m.tee_time_1, '00:00:00'),
                    COALESCE(m.tee_time_2, '00:00:00'),
                    COALESCE(m.tee_time_3, '00:00:00'),
                    COALESCE(m.tee_time_4, '00:00:00')
                )
            ) >= NOW()
            ORDER BY m.match_date
            LIMIT 1
            """
        )

        match = cursor.fetchone()

        if match is None:
            return None

        match_id = match[0]

        cursor.execute(
            """
            SELECT
                p.player_name,
                CASE
                    WHEN a.status = 'in' THEN 'in'
                    WHEN a.status = 'maybe' THEN 'maybe'
                    ELSE 'unknown'
                END AS status
            FROM players p
            LEFT JOIN availability a
                ON a.player_id = p.id
                AND a.match_id = %s
            WHERE p.active = TRUE
            AND (
                a.status IN ('in', 'maybe')
                OR a.status IS NULL
            )
            ORDER BY
                CASE
                    WHEN a.status = 'in' THEN 1
                    WHEN a.status = 'maybe' THEN 2
                    ELSE 3
                END,
                p.player_name
            """,
            (match_id,),
        )

        player_availability = cursor.fetchall()
        player_names = [row[0] for row in player_availability]

        player_notes = {}

        if player_names:
            cursor.execute(
                """
                SELECT
                    player_name,
                    notes
                FROM players
                WHERE active = TRUE
                AND player_name IN ({})
                AND notes IS NOT NULL
                AND TRIM(notes) <> ''
                """.format(
                    ",".join(["%s"] * len(player_names))
                ),
                tuple(player_names),
            )

            player_notes = {
                player_name: notes
                for player_name, notes in cursor.fetchall()
            }

        cursor.execute(
            """
            SELECT
                gambler_id,
                starting_balance,
                current_balance
            FROM gamblers
            WHERE is_david = TRUE
            LIMIT 1
            """
        )

        david = cursor.fetchone()
        david_gambling = None

        if david is not None:
            david_gambler_id, starting_balance, current_balance = david

            cursor.execute(
                """
                SELECT
                    p.player_name,
                    mp.odds_american
                FROM market_prices mp
                JOIN players p
                    ON mp.player_id = p.id
                WHERE mp.match_id = %s
                AND mp.effective_at = (
                    SELECT MAX(effective_at)
                    FROM market_prices
                    WHERE match_id = %s
                )
                ORDER BY p.player_name
                """,
                (match_id, match_id),
            )

            market = [
                {
                    "Player": player_name,
                    "Current Odds": odds_american,
                    "David Wagers": [],
                }
                for player_name, odds_american in cursor.fetchall()
            ]

            market_by_player = {
                entry["Player"]: entry
                for entry in market
            }

            cursor.execute(
                """
                SELECT
                    p.player_name,
                    mp.odds_american,
                    w.wager_amount
                FROM wagers w
                JOIN market_prices mp
                    ON mp.market_price_id = w.market_price_id
                JOIN players p
                    ON p.id = mp.player_id
                WHERE w.gambler_id = %s
                AND mp.match_id = %s
                AND w.outcome IS NULL
                ORDER BY
                    w.wagered_at,
                    w.wager_id
                """,
                (david_gambler_id, match_id),
            )

            david_wagers = []

            for player_name, odds_american, wager_amount in cursor.fetchall():
                wager = {
                    "Odds": odds_american,
                    "Wager Amount": float(wager_amount),
                }

                david_wagers.append(wager)

                if player_name in market_by_player:
                    market_by_player[player_name]["David Wagers"].append(
                        wager
                    )

            if market:
                david_gambling = {
                    "Starting Bankroll": float(starting_balance),
                    "Current Bankroll": float(current_balance),
                    "Total Wagered On Match": sum(
                        wager["Wager Amount"]
                        for wager in david_wagers
                    ),
                    "Sportsbook Market": market,
                }

        player_history = {}

        if player_names:
            cursor.execute(
                """
                SELECT
                    player_name,
                    match_id,
                    match_date,
                    player_points,
                    match_performance,
                    group_winner,
                    match_winner
                FROM vw_completed_match_results
                WHERE player_name IN ({})
                ORDER BY match_date, match_id
                """.format(
                    ",".join(["%s"] * len(player_names))
                ),
                tuple(player_names),
            )

            for (
                player_name,
                history_match_id,
                history_match_date,
                player_points,
                match_performance,
                group_winner,
                match_winner,
            ) in cursor.fetchall():

                player_history.setdefault(
                    player_name,
                    [],
                ).append(
                    {
                        "Match ID": history_match_id,
                        "Match Date": str(history_match_date),
                        "Points": player_points,
                        "Match Performance": float(match_performance),
                        "Group Winner": bool(group_winner),
                        "Match Winner": bool(match_winner),
                    }
                )

        cursor.execute(
            """
            SELECT player_name
            FROM vw_completed_match_results
            WHERE match_winner = 1
            ORDER BY match_date DESC, match_id DESC
            LIMIT 1
            """
        )

        holder_row = cursor.fetchone()

        current_holder = (
            holder_row[0]
            if holder_row is not None
            else None
        )

        return {
            "match": match,
            "player_availability": player_availability,
            "player_notes": player_notes,
            "david_gambling": david_gambling,
            "player_history": player_history,
            "current_holder": current_holder,
        }

    finally:
        cursor.close()
        connection.close()


def save_response(match_id, response_text):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO responses (
                match_id,
                command,
                response_text
            )
            VALUES (%s, %s, %s)
            """,
            (
                match_id,
                "preview",
                response_text,
            ),
        )

        connection.commit()
        return cursor.lastrowid

    finally:
        cursor.close()
        connection.close()


async def main():
    print("Loading preview context...")

    context = load_preview_context()

    if context is None:
        raise RuntimeError("No upcoming CFB match found.")

    match = context["match"]

    (
        match_id,
        match_date,
        location,
        tee_time_1,
        tee_time_2,
        tee_time_3,
        tee_time_4,
        special_rule,
    ) = match

    tee_times = [
        tee_time
        for tee_time in (
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4,
        )
        if tee_time is not None
    ]

    player_availability = context["player_availability"]

    if not player_availability:
        raise RuntimeError(
            "Nobody is currently marked IN or MAYBE "
            "for the next CFB match."
        )

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

    preview_players = []

    for name, status in player_availability:
        history = context["player_history"].get(name, [])

        preview_players.append(
            {
                "Player": name,
                "Availability": status.upper(),
                "Matches Played": len(history),
                "History": history,
            }
        )

    preview_data = {
        "Match Date": str(match_date),
        "Days Until Match": (
            match_date - datetime.now().date()
        ).days,
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
        "Players UNKNOWN": sum(
            status == "unknown"
            for _, status in player_availability
        ),
        "Field Status": (
            "Players marked IN are the current field. "
            "Players marked MAYBE are possible additions. "
            "Players marked UNKNOWN have not responded."
        ),
        "Players": preview_players,
        "Current CFB Holder": context["current_holder"],
    }

    preview_data["Player Notes"] = context["player_notes"]

    if special_rule:
        preview_data["Weekly Special Rule"] = special_rule

    if context["david_gambling"] is not None:
        preview_data["David Gambling"] = context["david_gambling"]

    print(f"Generating preview for Match ID {match_id}...")

    result = await generate_preview(preview_data)

    print("Preview generated. Saving response...")

    response_id = save_response(
        match_id,
        result["text"],
    )

    print(f"Response saved as ID {response_id}.")

    print()
    print(f"Match ID:    {match_id}")
    print(f"Response ID: {response_id}")
    print()
    print("----- PREVIEW -----")
    print()
    print(result["text"])
    print()
    print("-------------------")


if __name__ == "__main__":
    asyncio.run(main())