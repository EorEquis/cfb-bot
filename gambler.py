###################
# Created : 2026-09-08 GB
# Purpose : Runs the Tan City Sportsbook gambler agents.
#           Reads gambler personality/bankroll, the current Tan City market,
#           completed CFB history/current normalized indexes, and each gambler's
#           private wager history, then asks OpenAI for one wagering decision
#           per active gambler and stores any resulting wagers.
# Notes   : Gamblers may use their own prior wager reasons as persistent private
#           memory. Bookie private pricing reasons are never exposed.
###################

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import logging
import os

import mysql.connector
from openai import AsyncOpenAI

import sheets


logger = logging.getLogger(__name__)

CONCURRENT_GAMBLERS = int(os.getenv("CONCURRENT_GAMBLERS", "10"))
MODEL = os.getenv("GAMBLER_MODEL", "gpt-5.6-sol")
NUMBER_GAMBLERS = int(os.getenv("NUMBER_GAMBLERS", "10"))

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")

client = AsyncOpenAI()


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
        "player_data": player_data,
        "wager_history": [
            {
                "wager_id": row["wager_id"],
                "market_price_id": row["market_price_id"],
                "match_id": row["match_id"],
                "match_date": str(row["match_date"]),
                "player_id": row["player_id"],
                "player": row["player_name"],
                "odds_american": row["odds_american"],
                "wager_amount": float(row["wager_amount"]),
                "reason": row["reason"],
                "outcome": row["outcome"],
                "payout": (
                    float(row["payout"])
                    if row["payout"] is not None
                    else None
                ),
                "wagered_at": str(row["wagered_at"]),
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
  Higher values make you more willing to reject obvious favorites, conventional
  wisdom, and popular-looking choices in favor of less obvious prices.

- confidence:
  Higher values make you trust your own conclusions more strongly and act more
  decisively when you believe you have found value.

- bankroll_discipline:
  Higher values favor careful bankroll preservation and smaller wager sizing.
  Lower values permit much more aggressive, reckless, or concentrated betting.

These traits should influence your reasoning naturally. They are tendencies,
not rigid formulas. Their interaction matters.

These traits should not be mentioned when giving your reason for a wager.

Your previous wagers and their reasons are your own persistent memory. You may
learn from them, double down on them, regret them, ignore them, or repeat them
depending on your personality and the current evidence.

If is_david is true, this gambler is David. David's supplied personality scores
are intentional. Do not moderate them toward normal bettor behavior merely
because they appear extreme.

WHAT YOU KNOW:

- Your current bankroll.
- Your own personality traits.
- The current Tan City market prices.
- Current Normalized CFB Index for players in the market.
- Completed CFB match history for those players.
- Your own prior wagers, reasons, and any known outcomes.
- You do NOT have access to the bookmaker's private reasoning.
- You must independently decide whether you believe a price is good or bad.
- Do NOT invent injuries, weather, course history, inside information, or any
  other facts not supplied here.

HOW TO THINK:

- Higher Normalized CFB Index represents stronger current competitive strength.
- Historical Match Performance, points, group wins, match wins, and recent form
  are evidence about a player's ability to win.
- Compare your own assessment of a player's chance to the price offered by the
  sportsbook.
- The historical sample may be absurdly small. This has never stopped CFB from
  drawing sweeping conclusions, and it should not stop you. Use the available
  evidence seriously without apologizing for the sample size.
- Current Normalized CFB Index should be an important anchor, especially when
  historical sample sizes are small.
- Do NOT use handicap benefit credits or provisional offsets.
- You do not have to bet merely because betting is available.
- Pass if no price is attractive enough for this gambler.
- If you do bet, choose the player and wager size yourself.
- Never wager more than your current bankroll.
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
  "player_id": 456,
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
  "reason": "Short explanation of why you are passing."
}}

RULES FOR THE JSON:
- Return valid JSON only.
- Do not include markdown code fences.
- Do not include commentary before or after the JSON.
- If betting, market_price_id must exactly match one of the supplied current
  market prices.
- If betting, player_id and player must match the player associated with that
  market_price_id.
- wager_amount must be numeric.
- wager_amount must not exceed current_balance.
- If passing, wager_amount must be 0.

DATA:
{json.dumps(gambler_data, indent=2, default=str)}
""".strip()

    return prompt


# Read active gamblers who currently have money available to wager.
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


# Read the most recent complete market snapshot for the upcoming match.
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
            (
                match_id,
                match_id,
            ),
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
                m.match_date,
                mp.player_id,
                p.player_name,
                mp.odds_american,
                w.wager_amount,
                w.reason,
                w.outcome,
                w.payout,
                w.wagered_at
            FROM wagers w
            INNER JOIN market_prices mp
                ON mp.market_price_id = w.market_price_id
            INNER JOIN matches m
                ON m.id = mp.match_id
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


# Ask the model to make one gambler decision.
async def generate_decision(gambler_data):
    prompt = build_prompt(gambler_data)

    response = await client.responses.create(
        model=MODEL,
        input=prompt,
    )

    return json.loads(response.output_text)


# Run all active gambler agents once when this module is executed directly.
async def main():
    results = await run_gamblers()

    if not results:
        print("No Tan City gambler decisions were made.")
        return

    bets = sum(
        1
        for result in results
        if result["decision"]["bet"]
    )

    passes = len(results) - bets

    print(
        f"Tan City gamblers complete | "
        f"Gamblers: {len(results)} | "
        f"Bets: {bets} | "
        f"Passes: {passes}"
    )


# Run one gambler against the current market.
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

        if decision["bet"]:
            result["new_balance"] = save_wager(
                gambler["gambler_id"],
                decision,
            )

        return result


# Run one complete Tan City gambler cycle.
async def run_gamblers():
    match = get_upcoming_match()

    if match is None:
        return []

    current_market = get_current_market(match["id"])

    if not current_market:
        return []

    gamblers = get_active_gamblers()

    if not gamblers:
        return []

    logger.info(
        "Tan City gamblers starting | Gamblers: %s",
        len(gamblers),
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

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    successful_results = []

    for gambler, result in zip(gamblers, results):
        if isinstance(result, Exception):
            logger.error(
                "Tan City gambler %s failed | %s: %s",
                gambler["gambler_id"],
                type(result).__name__,
                result,
            )
            continue

        successful_results.append(result)

    return successful_results


# Store one validated wager and immediately reserve/deduct the stake
# from the gambler's available bankroll.
#
# The wager insert and bankroll update occur in one transaction.
def save_wager(gambler_id, decision):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        # Lock the gambler row while we verify and modify the bankroll.
        connection.start_transaction()

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
            raise ValueError(
                f"Gambler {gambler_id} not found."
            )

        current_balance = float(gambler["current_balance"])
        wager_amount = float(decision["wager_amount"])

        # Re-check bankroll inside the transaction in case it changed after
        # the model decision was generated.
        if wager_amount <= 0:
            raise ValueError(
                "Wager amount must be greater than zero."
            )

        if wager_amount > current_balance:
            raise ValueError(
                f"Wager amount ${wager_amount:.2f} exceeds current "
                f"bankroll ${current_balance:.2f}."
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

        # Reserve the stake immediately so it cannot be wagered again.
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

        if cursor.rowcount != 1:
            raise RuntimeError(
                f"Gambler {gambler_id} balance was not updated exactly once."
            )

        connection.commit()

        return round(
            current_balance - wager_amount,
            2,
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# Validate the gambler's decision before doing anything with it.
def validate_decision(decision, gambler_data):
    if not isinstance(decision.get("bet"), bool):
        raise ValueError(
            "Gambler decision must contain bet=true or bet=false."
        )

    reason = decision.get("reason")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(
            "Gambler decision must contain a non-empty reason."
        )

    # Nothing else needs validation if the gambler passed.
    if decision["bet"] is False:
        return

    current_market = gambler_data["current_market"]

    market_price_id = decision.get("market_price_id")

    selected_market = next(
        (
            price
            for price in current_market
            if price["market_price_id"] == market_price_id
        ),
        None,
    )

    if selected_market is None:
        raise ValueError(
            "Returned market_price_id is not in the current market."
        )

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
        raise ValueError(
            "wager_amount must be numeric."
        )

    if wager_amount <= 0:
        raise ValueError(
            "wager_amount must be greater than zero when betting."
        )

    current_balance = gambler_data["gambler"]["current_balance"]

    if wager_amount > current_balance:
        raise ValueError(
            "wager_amount cannot exceed current_balance."
        )


if __name__ == "__main__":
    asyncio.run(main())