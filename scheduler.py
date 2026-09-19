###################
# Created : 2026-09-08 GB
# Purpose : Runs scheduled CFB Bot background jobs.
#           Tan City creates markets and runs gambler agents.
#           Database sync mirrors authoritative spreadsheet data into MySQL.
# Notes   : Most code was generated with assistance from ChatGPT.
#           OpenAI model/version: GPT-5.6 Sol
###################

import asyncio
import datetime
import logging
import mysql.connector
import os

from bookie import run_bookie
from infrastructure.db_sync import sync_db
from discord.ext import tasks
from gambler import run_gamblers
from settlement import run_settlement
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

CENTRAL_TIME = ZoneInfo("America/Chicago")

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")

BETTING_TIMES = [
    datetime.time(hour=0, minute=0, tzinfo=CENTRAL_TIME),
    datetime.time(hour=6, minute=0, tzinfo=CENTRAL_TIME),
    datetime.time(hour=12, minute=0, tzinfo=CENTRAL_TIME),
    datetime.time(hour=18, minute=0, tzinfo=CENTRAL_TIME),
]

DB_SYNC_FIXED_TIMES = {
    (0, 0),
    (6, 0),
    (12, 0),
    (18, 0),
}

_last_db_sync_minute = None


def _get_today_match_status(today):
    connection = mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                m.id,
                TIMESTAMP(
                    m.match_date,
                    GREATEST(
                        COALESCE(m.tee_time_1, '00:00:00'),
                        COALESCE(m.tee_time_2, '00:00:00'),
                        COALESCE(m.tee_time_3, '00:00:00'),
                        COALESCE(m.tee_time_4, '00:00:00')
                    )
                ),
                (
                    SELECT COUNT(*)
                    FROM match_results mr
                    WHERE mr.match_id = m.id
                    AND mr.match_winner = 1
                )
            FROM matches m
            WHERE m.match_date = %s
            AND m.active = TRUE
            LIMIT 1
            """,
            (today,)
        )

        return cursor.fetchone()

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()


def _rollover_gambler_balances():
    connection = mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE gamblers
            SET previous_balance = cycle_start_balance
            """
        )

        connection.commit()

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()
        
async def run_db_sync():
    logger.info("CFB database sync starting")

    try:
        await asyncio.to_thread(sync_db)
        logger.info("CFB database sync complete")
        return True

    except Exception:
        logger.exception("CFB database sync failed")
        return False


# Run one complete Tan City betting cycle.
# A new market must be created successfully before gamblers are allowed to run.
async def run_betting_cycle():
    logger.info("Tan City betting cycle starting")

    try:
        market = await run_bookie()

        if market is None:
            logger.info(
                "Tan City betting cycle stopped: no market was created"
            )
            return

        logger.info(
            "Tan City market created for match %s | Players: %s | Book: %.1f%%",
            market["match_id"],
            market["players"],
            market["book_percentage"],
        )

        results = await run_gamblers()

        bets = sum(
            1
            for result in results
            if result["decision"]["bet"]
        )
        passes = len(results) - bets

        logger.info(
            "Tan City gamblers complete | Decisions: %s | Bets: %s | Passes: %s",
            len(results),
            bets,
            passes,
        )

        logger.info("Tan City betting cycle complete")

    except Exception:
        logger.exception("Tan City betting cycle failed")


# Check twice per minute so scheduled minute boundaries cannot be missed.
# Actual database sync is limited to once per minute.
@tasks.loop(seconds=30)
async def db_sync_scheduler():
    global _last_db_sync_minute

    now = datetime.datetime.now(CENTRAL_TIME)
    current_minute = now.replace(second=0, microsecond=0)

    if current_minute == _last_db_sync_minute:
        return

    should_sync = (now.hour, now.minute) in DB_SYNC_FIXED_TIMES
    aggressive_sync = False

    # Sunday
    if now.weekday() == 6:

        # Additional hourly syncs from 4 AM through 7 AM.
        if now.hour in (4, 5, 6, 7) and now.minute == 0:
            should_sync = True

        match_status = await asyncio.to_thread(
            _get_today_match_status,
            now.date()
        )

        if match_status is not None:
            match_id, latest_tee_datetime, match_winner_count = match_status

            latest_tee_datetime = latest_tee_datetime.replace(
                tzinfo=CENTRAL_TIME
            )

            aggressive_sync_start = (
                latest_tee_datetime
                + datetime.timedelta(hours=2)
            )

            # Once the aggressive window begins, sync every minute until
            # exactly one match winner exists.
            if (
                now >= aggressive_sync_start
                and match_winner_count != 1
            ):
                should_sync = True
                aggressive_sync = True

    if not should_sync:
        return

    _last_db_sync_minute = current_minute

    sync_succeeded = await run_db_sync()

    # An aggressive sync that mirrors the completed match ends the one-minute
    # cycle. Run Tan City settlement immediately after that successful sync.
    if aggressive_sync and sync_succeeded:
        match_status = await asyncio.to_thread(
            _get_today_match_status,
            now.date()
        )

        if match_status is not None:
            match_id, latest_tee_datetime, match_winner_count = match_status

            if match_winner_count == 1:
                try:
                    summaries = await asyncio.to_thread(run_settlement)

                    for summary in summaries:
                        logger.info(
                            "Tan City settlement complete | Match: %s | "
                            "Winner: %s | Settled: %s | Wins: %s | Losses: %s | "
                            "Bookie net: $%.2f",
                            summary["match_id"],
                            summary["winner"],
                            summary["settled"],
                            summary["wins"],
                            summary["losses"],
                            summary["bookie_net"],
                        )

                except Exception:
                    logger.exception("Tan City settlement failed")


# Preserve the previous Tan City cycle's starting balances before
# the new betting cycle begins Thursday.
@tasks.loop(
    time=datetime.time(hour=0, minute=0, tzinfo=CENTRAL_TIME)
)
async def tan_city_balance_scheduler():
    now = datetime.datetime.now(CENTRAL_TIME)

    # Wednesday
    if now.weekday() != 2:
        return

    try:
        await asyncio.to_thread(_rollover_gambler_balances)
        logger.info("Tan City gambler balance rollover complete")

    except Exception:
        logger.exception("Tan City gambler balance rollover failed")
        

# Run the Tan City betting cycle at midnight, 6 AM, noon, and 6 PM Central Thurs - Sat.
# On Sunday, run only at midnight and 6 AM.
@tasks.loop(time=BETTING_TIMES)
async def tan_city_scheduler():
    now = datetime.datetime.now(CENTRAL_TIME)

    if now.weekday() < 3:
        return

    if now.weekday() == 6 and now.hour not in (0, 6):
        return

    await run_betting_cycle()