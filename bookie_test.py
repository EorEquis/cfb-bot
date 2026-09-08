###################
# Created : 2026-09-07 GB
# Purpose : Development test harness for the CFB bookie.
#           Reads completed match history and current normalized indexes from
#           Google Sheets, reads the upcoming match/field from MariaDB, and asks
#           OpenAI to price the current field with American moneyline odds.
# Notes   : Console output if WRITE_MARKET is false, otherwise stores results in market_prices
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
WRITE_MARKET = os.getenv("BOOKIE_WRITE_MARKET", "false").lower() == "true"

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


# Convert American odds to implied probability as a decimal.
def american_to_implied_probability(odds):
    if odds > 0:
        return 100 / (odds + 100)

    return abs(odds) / (abs(odds) + 100)


# Calculate the sportsbook's total implied probability across the field.
def calculate_book_percentage(prices):
    return sum(
        american_to_implied_probability(price["odds_american"])
        for price in prices
    ) * 100


# Make sure the model returned exactly one valid price for every IN player.
def validate_market(market, field):
    if "prices" not in market or not isinstance(market["prices"], list):
        raise ValueError("Model response does not contain a valid prices list.")

    expected_ids = {player["player_id"] for player in field}
    returned_ids = [price.get("player_id") for price in market["prices"]]

    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("Model returned duplicate player IDs.")

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

    finally:
        cursor.close()
        connection.close()
                    

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


# Read all previous market prices already posted for this match.
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
        

# Combine database field information with spreadsheet history/current indexes.
def build_bookie_data(match, field):
    completed_matches = sheets.get_completed_matches()
    current_players = sheets.get_players()
    previous_market_prices = get_previous_market_prices(match["id"])
    current_wagers = get_current_wagers(match["id"])
    current_wager_exposure = build_wager_exposure(current_wagers)    

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
- Price the players relative to the CURRENT FIELD, not relative to players who
  are not entered.
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


async def generate_odds(bookie_data):
    prompt = build_prompt(bookie_data)

    response = await client.responses.create(
        model=MODEL,
        input=prompt,
    )

    return json.loads(response.output_text)


# Calculate the bettor's profit if a wager wins.
# This excludes return of the original stake.
def calculate_wager_profit(wager_amount, odds):
    if odds > 0:
        return wager_amount * odds / 100

    return wager_amount * 100 / abs(odds)


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

    print("\nCURRENT WAGER EXPOSURE:")
    print(
        json.dumps(
            bookie_data["current_wager_exposure"],
            indent=2,
            default=str,
        )
    )    

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

    previous_prices = bookie_data["previous_market_prices"]

    print(
        f"\nPrevious market prices for this match: "
        f"{len(previous_prices)}"
    )
    
    print(f"\n[4/4] Asking {MODEL} to price the field...\n")

    market = await generate_odds(bookie_data)

    validate_market(market, field)

    book_percentage = calculate_book_percentage(market["prices"])

    print("=" * 72)
    print("TAN CITY SPORTSBOOK — TEST MARKET")
    print("=" * 72)

    print(market["match_summary"])
    print()

    sorted_prices = sorted(
        market["prices"],
        key=lambda price: american_to_implied_probability(
            price["odds_american"]
        ),
        reverse=True,
    )

    for price in sorted_prices:
        implied = (
            american_to_implied_probability(price["odds_american"])
            * 100
        )

        odds_text = (
            f"+{price['odds_american']}"
            if price["odds_american"] > 0
            else str(price["odds_american"])
        )

        print(
            f"{price['player']} | "
            f"{odds_text} | "
            f"{implied:.1f}% | "
            f"{price['reason']}"
        )

    print()
    print(f"BOOK PERCENTAGE: {book_percentage:.1f}%")

    if WRITE_MARKET:
        save_market_prices(
            match["id"],
            market["prices"],
        )
        print("\nMarket snapshot written to market_prices.")
    else:
        print("\nMarket snapshot NOT written. BOOKIE_WRITE_MARKET=false.")
        
    print("=" * 72)        
    
if __name__ == "__main__":
    asyncio.run(main())
