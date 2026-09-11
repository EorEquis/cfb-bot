###################
# Created : 2026-09-08 GB
# Purpose : Runs scheduled CFB Bot background jobs.
#           Tan City creates a new market four times daily, then runs the
#           gambler agents after the market is successfully created.
# Notes   : Most code was generated with assistance from ChatGPT.
#           OpenAI model/version: GPT-5.6 Sol
###################

import datetime
import logging

from bookie import run_bookie
from discord.ext import tasks
from gambler import run_gamblers
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

CENTRAL_TIME = ZoneInfo("America/Chicago")

BETTING_TIMES = [
    datetime.time(hour=0, minute=0, tzinfo=CENTRAL_TIME),
    datetime.time(hour=6, minute=0, tzinfo=CENTRAL_TIME),
    datetime.time(hour=12, minute=0, tzinfo=CENTRAL_TIME),
    datetime.time(hour=18, minute=0, tzinfo=CENTRAL_TIME),
]


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


# Run the Tan City betting cycle at midnight, 6 AM, noon, and 6 PM Central.
@tasks.loop(time=BETTING_TIMES)
async def tan_city_scheduler():
    await run_betting_cycle()