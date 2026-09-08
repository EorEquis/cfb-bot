###################
# Created : 2026-09-08 GB
# Purpose : Development test harness for a CFB gambler agent.
#           Reads gambler personality/bankroll, the current Tan City market,
#           completed CFB history/current normalized indexes, and the gambler's
#           prior wager history, then asks OpenAI to make one wagering decision.
# Notes   : Console output if WRITE_WAGER is false, otherwise stores the wager.
###################

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os

import mysql.connector
from openai import AsyncOpenAI

import sheets


CONCURRENT_GAMBLERS = int(os.getenv("CONCURRENT_GAMBLERS", "10"))
MODEL = os.getenv("GAMBLER_MODEL", "gpt-5.6-sol")
NUMBER_GAMBLERS = int(os.getenv("NUMBER_GAMBLERS", "10"))
WRITE_WAGER = os.getenv("GAMBLER_WRITE_WAGER", "false").lower() == "true"

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


def get_active_gamblers():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                gambler_id,
                is_david,
                risk_tolerance,
                loss_aversion,
                contrarianism,
                confidence,
                bankroll_discipline,
                starting_balance,
                current_balance
            FROM gamblers
            WHERE current_balance > 0
            ORDER BY gambler_id
            LIMIT %s
            """,
            (NUMBER_GAMBLERS,),
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# Return the next active match that has not finished yet.
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


# Read the most recent complete Tan City market snapshot for this match.
#
# The bookmaker writes one snapshot for the entire field at a time, so all rows
# from the most recent effective_at represent the currently offered market.
#
# Bookie "reason" is intentionally NOT selected here. That is private bookie
# memory and is not information available to gamblers.
def get_current_market(match_id):
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
                mp.effective_at
            FROM market_prices mp
            INNER JOIN players p
                ON p.id = mp.player_id
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

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# Read this gambler's complete wager history.
#
# This includes the gambler's own prior reason because that is part of the
# gambler's persistent memory. It does NOT expose the bookmaker's reason.
def get_wager_history(gambler_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                w.wager_id,
                w.market_price_id,
                mp.match_id,
                mp.player_id,
                p.player_name,
                mp.odds_american,
                w.wagered_at,
                w.wager_amount,
                w.reason,
                w.outcome,
                w.payout
            FROM wagers w
            INNER JOIN market_prices mp
                ON mp.market_price_id = w.market_price_id
            INNER JOIN players p
                ON p.id = mp.player_id
            WHERE w.gambler_id = %s
            ORDER BY
                w.wagered_at,
                w.wager_id
            """,
            (gambler_id,),
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


# Build public CFB performance/history data for players in the current market.
def get_player_data(current_market):
    completed_matches = sheets.get_completed_matches()
    current_players = sheets.get_players()

    player_data = []

    for market_player in current_market:
        name = market_player["player_name"]

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
                "player_id": market_player["player_id"],
                "player": name,
                "normalized_cfb_index": normalized_index,
                "matches_played": len(appearances),
                "history": appearances,
            }
        )

    return player_data


# Combine everything the gambler is allowed to know into one data structure.
def build_gambler_data(gambler, match, current_market):
    player_data = get_player_data(current_market)
    wager_history = get_wager_history(gambler["gambler_id"])

    tee_times = [
        match["tee_time_1"],
        match["tee_time_2"],
        match["tee_time_3"],
        match["tee_time_4"],
    ]

    return {
        "gambler": {
            "gambler_id": gambler["gambler_id"],
            "is_david": bool(gambler["is_david"]),
            "risk_tolerance": gambler["risk_tolerance"],
            "loss_aversion": gambler["loss_aversion"],
            "contrarianism": gambler["contrarianism"],
            "confidence": gambler["confidence"],
            "bankroll_discipline": gambler["bankroll_discipline"],
            "starting_balance": float(gambler["starting_balance"]),
            "current_balance": float(gambler["current_balance"]),
        },

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

        "current_market": [
            {
                "market_price_id": row["market_price_id"],
                "player_id": row["player_id"],
                "player": row["player_name"],
                "odds_american": row["odds_american"],
                "effective_at": str(row["effective_at"]),
            }
            for row in current_market
        ],

        "players": player_data,

        "wager_history": [
            {
                "wager_id": row["wager_id"],
                "match_id": row["match_id"],
                "player_id": row["player_id"],
                "player": row["player_name"],
                "odds_american": row["odds_american"],
                "wagered_at": str(row["wagered_at"]),
                "wager_amount": float(row["wager_amount"]),
                "reason": row["reason"],
                "outcome": row["outcome"],
                "payout": (
                    float(row["payout"])
                    if row["payout"] is not None
                    else None
                ),
            }
            for row in wager_history
        ],
    }


# Describe the gambler's job, personality, information, and allowed action.
def build_prompt(gambler_data):
    prompt = f"""
You are a CFB GAMBLER participating in the imaginary Tan City Sportsbook.

You are not the bookmaker. You are a bettor trying to grow your bankroll.

You may make AT MOST ONE wagering decision during this run:
- Place one wager on one player at the currently offered price.
- Or pass and make no wager.

You are allowed to bet on the same market price more than once across separate
runs. A previous wager does not prevent you from deciding later that the same
price is still attractive enough to bet again.

YOUR PERSONALITY:

Your persistent behavioral traits are numerical values from 0-100:

- risk_tolerance:
  Higher values favor larger risks and greater willingness to gamble.

- loss_aversion:
  Higher values make losses hurt more and encourage caution after losing.

- contrarianism:
  Higher values make you more willing to disagree with the apparent market
  consensus and seek prices you think the bookmaker has wrong.

- confidence:
  Higher values make you more willing to trust your own analysis and prior
  conclusions.

- bankroll_discipline:
  Higher values encourage conservative wager sizing and protection of bankroll.
  Low values allow reckless wager sizing.

These traits should materially influence BOTH whether you bet and how much you bet.

If is_david is true, this gambler is David. David's supplied personality scores
are intentional. Do not moderate them toward normal bettor behavior merely
because they appear extreme.

WHAT YOU KNOW:

- Your current bankroll.
- Your own personality traits.
- The current Tan City market prices.
- Current Normalized CFB Index for players in the market.
- Completed CFB match history for those players.
- Your own previous wagers, including why you made them and their outcomes.

WHAT YOU DO NOT KNOW:

- You do NOT know why the bookmaker set any particular price.
- You do NOT have access to the bookmaker's private reasoning.
- You must independently decide whether you believe a price is good or bad.
- Do NOT invent injuries, weather, course history, inside information, or any
  other facts not supplied here.

HOW TO THINK:

- Higher Normalized CFB Index represents stronger current competitive strength.
- Historical Match Performance, points, group wins, match wins, and recent form
  are evidence about a player's ability to win.
- Compare your own assessment of a player's chance to the price offered by the
  bookmaker.
- A wager is attractive when you believe the offered price pays better than the
  player's actual chance of winning deserves.
- You are not required to bet. Passing is a legitimate decision.
- Your previous wagers and outcomes are your own experience and memory.
- You may learn from them, overlearn from them, become more confident because
  of them, become gun-shy because of them, or otherwise react according to your
  personality.
- The historical sample may be absurdly small. This is CFB. Two observations
  have never prevented anyone from declaring a trend.
- Do NOT assume or infer any player's gender. Use the player's name or
  gender-neutral language.

WAGER SIZING:

- wager_amount may not exceed current_balance.
- wager_amount must be greater than zero if placing a wager.
- Determine wager size yourself based on perceived value, confidence,
  personality, prior experience, and bankroll.
- Do not use a fixed percentage formula unless you independently believe that is
  how this gambler would behave.

OUTPUT:

Return valid JSON only.

If placing a wager:

{{
  "bet": true,
  "market_price_id": 123,
  "player_id": 7,
  "player": "Player Name",
  "wager_amount": 250.00,
  "reason": "Short explanation of why you believe this wager is worth making."
}}

If passing:

{{
  "bet": false,
  "market_price_id": null,
  "player_id": null,
  "player": null,
  "wager_amount": 0,
  "reason": "Short explanation of why no available price is worth betting."
}}

RULES FOR THE JSON:

- Return exactly one decision.
- If bet is true, use one of the supplied market_price_id values exactly.
- If bet is true, player_id and player must correspond to that market price.
- wager_amount must be numeric.
- Do not include markdown code fences.
- Do not include commentary before or after the JSON.

DATA:

{json.dumps(gambler_data, indent=2, default=str)}
""".strip()

    return prompt


# Ask the model to make one gambler decision.
async def generate_decision(gambler_data):
    prompt = build_prompt(gambler_data)

    response = await client.responses.create(
        model=MODEL,
        input=prompt,
    )

    return json.loads(response.output_text)


# Validate the gambler's decision before doing anything with it.
def validate_decision(decision, gambler_data):
    if not isinstance(decision.get("bet"), bool):
        raise ValueError("Gambler decision must contain bet=true or bet=false.")

    reason = decision.get("reason")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Gambler decision must contain a non-empty reason.")

    # Nothing else needs validation if the gambler passed.
    if decision["bet"] is False:
        return

    current_market = gambler_data["current_market"]

    market_by_id = {
        row["market_price_id"]: row
        for row in current_market
    }

    market_price_id = decision.get("market_price_id")

    if market_price_id not in market_by_id:
        raise ValueError(
            f"Invalid market_price_id: {market_price_id}"
        )

    selected_market = market_by_id[market_price_id]

    if decision.get("player_id") != selected_market["player_id"]:
        raise ValueError(
            "Returned player_id does not match selected market_price_id."
        )

    if decision.get("player") != selected_market["player"]:
        raise ValueError(
            "Returned player name does not match selected market_price_id."
        )

    wager_amount = decision.get("wager_amount")

    if not isinstance(wager_amount, (int, float)):
        raise ValueError("wager_amount must be numeric.")

    if wager_amount <= 0:
        raise ValueError("wager_amount must be greater than zero.")

    current_balance = gambler_data["gambler"]["current_balance"]

    if wager_amount > current_balance:
        raise ValueError(
            f"Wager amount {wager_amount:.2f} exceeds current bankroll "
            f"{current_balance:.2f}."
        )


# Store one validated wager and immediately reserve/deduct the stake
# from the gambler's available bankroll.
#
# The wager insert and bankroll update occur in one transaction.
def save_wager(gambler_id, decision):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        # Lock the gambler row while we verify and modify the bankroll.
        cursor.execute(
            """
            SELECT current_balance
            FROM gamblers
            WHERE gambler_id = %s
            FOR UPDATE
            """,
            (gambler_id,),
        )

        gambler = cursor.fetchone()

        if gambler is None:
            raise ValueError(f"Gambler {gambler_id} not found.")

        current_balance = float(gambler["current_balance"])
        wager_amount = float(decision["wager_amount"])

        # Re-check bankroll inside the transaction in case it changed after
        # the model decision was generated.
        if wager_amount <= 0:
            raise ValueError("Wager amount must be greater than zero.")

        if wager_amount > current_balance:
            raise ValueError(
                f"Wager amount ${wager_amount:,.2f} exceeds current bankroll "
                f"${current_balance:,.2f}."
            )

        # Write the wager at the exact market price selected by the gambler.
        cursor.execute(
            """
            INSERT INTO wagers (
                market_price_id,
                gambler_id,
                wager_amount,
                reason
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                decision["market_price_id"],
                gambler_id,
                wager_amount,
                decision["reason"],
            ),
        )

        # Deduct the stake immediately. If the wager later wins, settlement
        # will return the stake plus the winnings.
        cursor.execute(
            """
            UPDATE gamblers
            SET current_balance = current_balance - %s
            WHERE gambler_id = %s
            """,
            (
                wager_amount,
                gambler_id,
            ),
        )

        connection.commit()

        return current_balance - wager_amount

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


async def run_gambler(gambler, match, current_market, semaphore):
    async with semaphore:
        gambler_data = build_gambler_data(
            gambler,
            match,
            current_market,
        )

        decision = await generate_decision(gambler_data)

        validate_decision(
            decision,
            gambler_data,
        )

        result = {
            "gambler": gambler,
            "decision": decision,
            "new_balance": None,
        }

        if decision["bet"] and WRITE_WAGER:
            result["new_balance"] = save_wager(
                gambler["gambler_id"],
                decision,
            )

        return result
    

async def main():
    match = get_upcoming_match()

    if match is None:
        print("No upcoming active match found.")
        return

    current_market = get_current_market(match["id"])

    if not current_market:
        print("No current market found for upcoming match.")
        return

    gamblers = get_active_gamblers()

    if not gamblers:
        print("No active gamblers found.")
        return

    print(
        f"\nRunning {len(gamblers)} gamblers for "
        f"match {match['id']} on {match['match_date']}"
    )

    print(
        f"Maximum concurrent gamblers: "
        f"{CONCURRENT_GAMBLERS}"
    )

    semaphore = asyncio.Semaphore(CONCURRENT_GAMBLERS)

    tasks = [
        run_gambler(
            gambler,
            match,
            current_market,
            semaphore,
        )
        for gambler in gamblers
    ]

    results = await asyncio.gather(*tasks)

    for result in results:
        gambler = result["gambler"]
        decision = result["decision"]

        print("\n" + "=" * 70)

        print(
            f"Gambler {gambler['gambler_id']}: "
            f"bankroll=${float(gambler['current_balance']):,.2f}"
        )

        print(
            f"risk={gambler['risk_tolerance']} "
            f"loss_aversion={gambler['loss_aversion']} "
            f"contrarianism={gambler['contrarianism']} "
            f"confidence={gambler['confidence']} "
            f"discipline={gambler['bankroll_discipline']}"
        )

        if decision["bet"]:
            market = next(
                row
                for row in current_market
                if row["market_price_id"]
                == decision["market_price_id"]
            )

            odds = market["odds_american"]
            odds_text = (
                f"+{odds}"
                if odds > 0
                else str(odds)
            )

            print(
                f"\nBET ${decision['wager_amount']:,.2f} "
                f"on {decision['player']} at {odds_text}"
            )

            print(f"REASON: {decision['reason']}")

            if WRITE_WAGER:
                print("Wager written to wagers.")
                print(
                    f"Remaining bankroll: "
                    f"${result['new_balance']:,.2f}"
                )

        else:
            print("\nPASS")
            print(f"REASON: {decision['reason']}")

    print("\n" + "=" * 70)
    print("Gambler run complete.")    

if __name__ == "__main__":
    asyncio.run(main())