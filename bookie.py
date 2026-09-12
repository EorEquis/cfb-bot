###################
# Created : 2026-09-08 GB
# Purpose : Runs the Tan City Sportsbook bookie.
#           Reads completed CFB history and current normalized indexes from
#           Google Sheets, reads the upcoming match/field and wager exposure
#           from MariaDB, asks OpenAI to price the field, and stores the
#           resulting American moneyline market in market_prices.
# Notes   : The bookie may use its own prior pricing reasons as persistent
#           private memory. Gambler private wager reasons are never exposed.
###################

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os

import mysql.connector
from openai import AsyncOpenAI


MODEL = os.getenv("BOOKIE_MODEL", "gpt-5.6-sol")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")

client = AsyncOpenAI()


# Convert American odds to implied probability as a decimal.
def american_to_implied_probability(odds):
    if odds > 0:
        return 100 / (odds + 100)

    return abs(odds) / (abs(odds) + 100)


# Combine active-player availability context with DB history/current indexes.
def build_bookie_data(match, player_context):
    previous_market_prices = get_previous_market_prices(match["id"])
    current_wagers = get_current_wagers(match["id"])
    current_wager_exposure = build_wager_exposure(current_wagers)

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                s.player_id,
                s.normalized_cfb_index
            FROM vw_player_career_stats s
            WHERE s.active = TRUE
            """
        )

        current_players = {
            row["player_id"]: row
            for row in cursor.fetchall()
        }

        cursor.execute(
            """
            SELECT
                player_id,
                match_id,
                match_date,
                player_points,
                pre_match_index,
                match_performance,
                group_winner,
                match_winner
            FROM vw_completed_match_results
            ORDER BY
                player_id,
                match_date,
                match_id
            """
        )

        history_by_player = {}

        for row in cursor.fetchall():
            history_by_player.setdefault(
                row["player_id"],
                []
            ).append(
                {
                    "match_id": int(row["match_id"]),
                    "match_date": str(row["match_date"]),
                    "player_points": int(row["player_points"]),
                    "pre_match_index": float(row["pre_match_index"]),
                    "match_performance": float(row["match_performance"]),
                    "group_winner": bool(row["group_winner"]),
                    "match_winner": bool(row["match_winner"]),
                }
            )

    finally:
        cursor.close()
        connection.close()

    player_data = []

    for db_player in player_context:
        player_id = db_player["player_id"]
        name = db_player["player_name"]

        player_row = current_players.get(player_id)
        normalized_index = None

        if (
            player_row is not None
            and player_row["normalized_cfb_index"] is not None
        ):
            normalized_index = float(
                player_row["normalized_cfb_index"]
            )

        appearances = history_by_player.get(
            player_id,
            []
        )

        player_data.append(
            {
                "player_id": player_id,
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
        "player_context": player_data,
        "previous_market_prices": [
            {
                "market_price_id": row["market_price_id"],
                "player_id": row["player_id"],
                "player": row["player_name"],
                "odds_american": row["odds_american"],
                "reason": row["reason"],
                "effective_at": str(row["effective_at"]),
            }
            for row in previous_market_prices
        ],
        "current_wager_exposure": current_wager_exposure,
    }
    

# Describe the bookie's job and provide only the data it may use.
def build_prompt(bookie_data):
    prompt = f"""
You are the CFB BOOKIE, the market maker for an imaginary CFB golf betting market.

Your job in this test is to set PRE-MATCH AMERICAN MONEYLINE ODDS for each player
currently marked IN for the upcoming match.

Use ONLY the supplied data.

WHAT YOU KNOW:
- Completed CFB match history for each active player.
- Each active player's current Normalized CFB Index.
- Each active player's current availability status.
- IN means the player currently expects to participate and is in the betting field.
- UNKNOWN means it is not currently known whether the player will participate.
- OUT means the player has indicated they do not currently expect to participate,
  but availability can change because real people and real schedules are involved.
- The upcoming match date/location/tee times.
- Your own previous market prices and stated reasons for this upcoming match, if any.

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
- Set prices only for players marked IN. UNKNOWN and OUT players are not currently
  in the betting field, but their supplied history, strength, and availability
  are legitimate context when assessing the upcoming match.
- Do not assign a probability that an UNKNOWN or OUT player will ultimately
  participate unless such a probability is explicitly supplied.
- Produce realistic bookmaker odds with a modest house margin rather than fair
  probabilities that sum to exactly 100%.
- Use standard American odds notation, including an explicit + sign on positive
  odds.
- Do NOT assume or infer any player's gender. Use the player's name or gender-neutral language.
- Previous market prices are your own prior decisions. Treat them as memory, not as
  authoritative truth. You may keep them, move them, or substantially reprice a
  player if your current judgment supports doing so.
- Do not change a price merely for the sake of changing it.

OUTPUT:

Return valid JSON only.

Use exactly this structure:

{{
  "match_summary": "short sentence identifying the upcoming match",
  "prices": [
    {{
      "player_id": 123,
      "player": "Player Name",
      "odds_american": 150,
      "reason": "Short reason tied directly to the supplied data."
    }}
  ]
}}

RULES FOR THE JSON:
- Return exactly one price for every player currently IN.
- Use each supplied player_id exactly as provided.
- odds_american must be an integer.
- Positive American odds should be represented as positive integers, such as 150.
- Negative American odds should be represented as negative integers, such as -120.
- Do not include implied probability; Python will calculate it.
- Do not calculate or return book percentage; Python will calculate it.
- Do not include markdown code fences.
- Do not include commentary before or after the JSON.

DATA:
{json.dumps(bookie_data, indent=2, default=str)}
""".strip()

    return prompt


# Summarize the sportsbook's outstanding exposure by player.
def build_wager_exposure(current_wagers):
    exposure = {}

    for wager in current_wagers:
        player_id = wager["player_id"]

        if player_id not in exposure:
            exposure[player_id] = {
                "player_id": player_id,
                "player": wager["player_name"],
                "wager_count": 0,
                "total_staked": 0.0,
                "potential_profit_liability": 0.0,
                "potential_total_return": 0.0,
                "wagers": [],
            }

        wager_amount = float(wager["wager_amount"])
        odds = wager["odds_american"]

        profit = calculate_wager_profit(
            wager_amount,
            odds,
        )

        total_return = wager_amount + profit

        exposure[player_id]["wager_count"] += 1
        exposure[player_id]["total_staked"] += wager_amount
        exposure[player_id]["potential_profit_liability"] += profit
        exposure[player_id]["potential_total_return"] += total_return

        exposure[player_id]["wagers"].append(
            {
                "wager_id": wager["wager_id"],
                "market_price_id": wager["market_price_id"],
                "gambler_id": wager["gambler_id"],
                "odds_american": odds,
                "wager_amount": wager_amount,
                "potential_profit": profit,
                "wagered_at": str(wager["wagered_at"]),
            }
        )

    return list(exposure.values())


# Calculate the sportsbook's total implied probability across the field.
def calculate_book_percentage(prices):
    return sum(
        american_to_implied_probability(price["odds_american"])
        for price in prices
    ) * 100


# Calculate the bettor's profit if a wager wins.
# This excludes return of the original stake.
def calculate_wager_profit(wager_amount, odds):
    if odds > 0:
        return wager_amount * odds / 100

    return wager_amount * 100 / abs(odds)


# Ask the model to price the current field.
async def generate_odds(bookie_data):
    prompt = build_prompt(bookie_data)

    response = await client.responses.create(
        model=MODEL,
        input=prompt,
    )

    return json.loads(response.output_text)


# Read all active players and their current availability context.
# MAYBE and no response are both exposed to the agent as UNKNOWN.
def get_player_context(match_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                p.id AS player_id,
                p.player_name,
                CASE
                    WHEN a.status = 'in' THEN 'in'
                    WHEN a.status = 'out' THEN 'out'
                    ELSE 'unknown'
                END AS status
            FROM players p
            LEFT JOIN availability a
                ON a.player_id = p.id
                AND a.match_id = %s
            WHERE p.active = TRUE
            ORDER BY p.player_name
            """,
            (match_id,),
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# Read the Players and Availability tables and return players currently IN.
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


# Read all currently unsettled wagers for the upcoming match.
#
# The bookmaker can see bets placed against its market, but does not receive
# the gambler's private reasoning stored in wagers.reason.
def get_current_wagers(match_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                w.wager_id,
                w.market_price_id,
                w.gambler_id,
                w.wager_amount,
                w.wagered_at,
                mp.player_id,
                p.player_name,
                mp.odds_american
            FROM wagers w
            INNER JOIN market_prices mp
                ON mp.market_price_id = w.market_price_id
            INNER JOIN players p
                ON p.id = mp.player_id
            WHERE mp.match_id = %s
              AND w.outcome IS NULL
            ORDER BY
                w.wagered_at,
                w.wager_id
            """,
            (match_id,),
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# Open a MariaDB/MySQL connection using the application's .env settings.
def get_db_connection():
    return mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )


# Read all previous market prices already posted for this match.
# The stored reason is the bookie's own persistent private memory.
def get_previous_market_prices(match_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                mp.market_price_id,
                mp.player_id,
                p.player_name,
                mp.odds_american,
                mp.reason,
                mp.effective_at
            FROM market_prices mp
            INNER JOIN players p
                ON p.id = mp.player_id
            WHERE mp.match_id = %s
            ORDER BY
                mp.effective_at,
                mp.market_price_id
            """,
            (match_id,),
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# Return the next active match that has not finished yet.
# An active match remains upcoming until its latest configured tee time passes.
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


# Run the bookie once when this module is executed directly.
async def main():
    result = await run_bookie()

    if result is None:
        print("No Tan City market was created.")
        return

    print(
        f"Tan City market created for "
        f"{result['match_date']} — {result['location']} | "
        f"{result['players']} players | "
        f"Book: {result['book_percentage']:.1f}%"
    )


# Run one complete Tan City bookie cycle.
async def run_bookie():
    match = await asyncio.to_thread(get_upcoming_match)

    if match is None:
        return None

    field = await asyncio.to_thread(
        get_current_field,
        match["id"],
    )

    if not field:
        return None

    player_context = await asyncio.to_thread(
        get_player_context,
        match["id"],
    )

    bookie_data = await asyncio.to_thread(
        build_bookie_data,
        match,
        player_context,
    )

    market = await generate_odds(bookie_data)

    validate_market(
        market,
        field,
    )

    book_percentage = calculate_book_percentage(
        market["prices"]
    )

    await asyncio.to_thread(
        save_market_prices,
        match["id"],
        market["prices"],
    )

    return {
        "match_id": match["id"],
        "match_date": str(match["match_date"]),
        "location": match["location"],
        "players": len(field),
        "book_percentage": book_percentage,
        "market": market,
    }


# Save one complete market snapshot to market_prices.
def save_market_prices(match_id, prices):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.executemany(
            """
            INSERT INTO market_prices (
                match_id,
                player_id,
                odds_american,
                reason
            )
            VALUES (%s, %s, %s, %s)
            """,
            [
                (
                    match_id,
                    price["player_id"],
                    price["odds_american"],
                    price["reason"],
                )
                for price in prices
            ],
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# Make sure the model returned exactly one valid price for every IN player.
def validate_market(market, field):
    if "prices" not in market or not isinstance(market["prices"], list):
        raise ValueError(
            "Model response does not contain a valid prices list."
        )

    expected_ids = {
        player["player_id"]
        for player in field
    }

    returned_ids = [
        price.get("player_id")
        for price in market["prices"]
    ]

    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError(
            "Model returned duplicate player IDs."
        )

    if set(returned_ids) != expected_ids:
        raise ValueError(
            "Returned market does not exactly match the current IN field."
        )

    for price in market["prices"]:
        odds = price.get("odds_american")

        if not isinstance(odds, int):
            raise ValueError(
                f"Invalid odds for player_id {price.get('player_id')}: "
                "American odds must be integers."
            )

        if -100 < odds < 100:
            raise ValueError(
                f"Invalid odds for player_id {price.get('player_id')}: "
                "American odds must be +100 or greater, or -100 or less."
            )

        reason = price.get("reason")

        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                f"Invalid reason for player_id {price.get('player_id')}: "
                "reason must be a non-empty string."
            )


if __name__ == "__main__":
    asyncio.run(main())