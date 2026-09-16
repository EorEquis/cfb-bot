###################
# Created : 2026-09-15 GB
# Purpose : Generates Tan City After Dark pre-match and post-match episodes.
#           Builds a compact betting payload, preserves prior episode memory,
#           stores generated responses, and returns API token usage.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 7
#           OpenAI model/version: GPT-5.6 Sol
###################

import json
import mysql.connector
import os

from openai import AsyncOpenAI



# Create the shared asynchronous OpenAI client used for Tan City requests.
client = AsyncOpenAI()

MODEL = os.getenv("TAN_CITY_MODEL", "gpt-5.6-luna")

MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER")


def build_betting_payload(rows):
    gamblers = {}
    wagers = []

    for row in rows:
        gambler_id = row["gambler_id"]

        if gambler_id not in gamblers:
            gamblers[gambler_id] = {
                "is_david": row["is_david"],
                "risk_tolerance": row["risk_tolerance"],
                "loss_aversion": row["loss_aversion"],
                "contrarianism": row["contrarianism"],
                "confidence": row["confidence"],
                "bankroll_discipline": row["bankroll_discipline"],
                "starting_balance": row["starting_balance"],
                "current_balance": row["current_balance"],
                "previous_balance": row["previous_balance"],
                "cycle_start_balance": row["cycle_start_balance"],
                "personality": row["personality"],
            }

        wagers.append(
            {
                "gambler_id": gambler_id,
                "player_name": row["player_name"],
                "wager_amount": row["wager_amount"],
                "odds_american": row["odds_american"],
                "reason": row["reason"],
            }
        )

    return {
        "gamblers": gamblers,
        "wagers": wagers,
    }


async def generate_tan_city(mode):
    rows = get_betting_history(mode)

    if not rows:
        raise RuntimeError("No betting history found for Tan City.")

    match_id = rows[0]["match_id"]
    payload = build_betting_payload(rows)
    betting_json = json.dumps(
        payload,
        separators=(",", ":"),
        default=str,
    )

    if mode == "pre":
        prompt = f"""
You are the host of Tan City After Dark, a late-night comedy podcast sponsored  by Tan City Sports King, a sportsbook covering a recreational golf league.

Here's the pre-match betting market for an upcoming golf match.

Make a short comedy podcast about the funniest or most interesting stories you find.
Be fucking hilarious. The primary goal is to make me laugh.

Roughly 600 words is a good length, but not a mandatory maximum.

Choose only 2 or 3 stories. Don't try to summarize the whole market or cover every player. Individual bettors are frequently funnier stories than the market on a particular player.

David is our CFB Network host, David FehertAI.

This is fake money in a fake market. You do not need to remind people to gamble responsibly. Indeed, lack of responsibility is often the point.

The podcast should have only 1 host.

The podcast should not have theme music.

EXPLANATION OF BALANCES:
    - starting_balance : ignore this
    - current_balance : the gambler's current balance.  This does not reflect losses yet, it is cycle_start_balance - total wagered on this match.
    - previous_balance : ignore this
    - cycle_start_balance : The gambler's balance when the betting window first opened for this match.

PRE-MATCH SPORTS MARKET DATA

{betting_json}
"""

        command = "tancity_pre"

    elif mode == "post":
        prior_response = get_latest_response(
            "tancity_pre",
            match_id=match_id,
        )

        prior_response_text = (
            prior_response["response_text"]
            if prior_response is not None
            else "No pre-match episode was recorded for this match."
        )

        prompt = f"""
You are the host of Tan City After Dark, a late-night comedy podcast sponsored by Tan City Sports King, a sportsbook covering a recreational golf league.

Here's the post-match wager results.

Make a short comedy podcast about the funniest or most interesting things that happened.
Be fucking hilarious. The primary goal is to make me laugh.

Choose only 2 or 3 stories. Don't try to summarize the whole match or cover every player. Individual bettors are frequently funnier stories than the market on a particular player.

Roughly 600 words is a good length, but not a mandatory maximum.

You also have what you said before the match. Treat that as your own memory of the story going into the match. Pay attention to anything you said before the match that became funnier, more interesting, or spectacularly wrong in hindsight.

David is our CFB Network host, David FehertAI.

This is fake money in a fake market. You do not need to remind people to gamble responsibly. Indeed, lack of responsibility is often the point.

The podcast should have only 1 host.

The podcast should not have theme music.

EXPLANATION OF BALANCES:
    - starting_balance : ignore this
    - current_balance : the gambler's current balance.  This reflects gains and losses. It is previous_balance + profit or loss on match wagers.
    - previous_balance : the gambler's balance when the betting window first opened for this match.
    - cycle_start_balance : ignore this.

Prior to the match you said:

{prior_response_text}

POST-MATCH WAGER RESULTS:

{betting_json}
"""

        command = "tancity_post"

    else:
        raise ValueError("Tan City mode must be 'pre' or 'post'.")

    response = await client.responses.create(
        model=MODEL,
        input=prompt,
    )

    save_response(
        command=command,
        response_text=response.output_text,
        match_id=match_id,
    )

    return {
        "text": response.output_text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


def get_betting_history(mode):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        ## Keeping this if statement in case we want to revert back to our temp table for debugging
        source = (
            "vw_betting_history_latest_match"
            if mode == "pre"
            else "vw_betting_history_latest_match"
        )

        cursor.execute(
            f"""
            SELECT *
            FROM {source}
            ORDER BY gambler_id, wagered_at
            """
        )

        return cursor.fetchall()

    finally:
        cursor.close()
        connection.close()


def get_db_connection():
    return mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )


def get_latest_response(command, match_id=None):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        if match_id is None:
            cursor.execute(
                """
                SELECT
                    response_id,
                    match_id,
                    command,
                    response_text,
                    created_at
                FROM responses
                WHERE command = %s
                ORDER BY created_at DESC, response_id DESC
                LIMIT 1
                """,
                (command,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    response_id,
                    match_id,
                    command,
                    response_text,
                    created_at
                FROM responses
                WHERE command = %s
                  AND match_id = %s
                ORDER BY created_at DESC, response_id DESC
                LIMIT 1
                """,
                (command, match_id),
            )

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()
        
        
def save_response(command, response_text, match_id=None):
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
                command,
                response_text,
            ),
        )

        connection.commit()
        return cursor.lastrowid

    finally:
        cursor.close()
        connection.close()