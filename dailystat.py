###################
# Created : 2026-09-13 GB
# Purpose : Generates a ridiculous but statistically defensible CFB observation
#           from complete recorded match history using OpenAI.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 6
#           OpenAI model/version: GPT-5.6 Sol
###################

import json
import os

from datetime import datetime
from openai import AsyncOpenAI


# Shared asynchronous OpenAI client used for daily-stat generation.
client = AsyncOpenAI()

MODEL = os.getenv("DAILYSTAT_MODEL", "gpt-5.6-luna")


async def generate_dailystat(history_data):
    prompt = f"""
You are David FehertAI, of the CFB Department of Unnecessary Analytics.

Here is the complete match history for a recreational golf league.

Find a fucking hilarious stat.  Making us laugh is the primary goal.

Emojis are encouraged.

Do not infer gender.

The current time is {datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")}.

CFB MATCH HISTORY:

{json.dumps(history_data, indent=2, default=str)}
"""

    response = await client.responses.create(
        model=MODEL,
        input=prompt
    )

    return {
        "text": response.output_text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens
    }