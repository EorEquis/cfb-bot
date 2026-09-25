###################
# Created : 2026-09-02 GB
# Purpose : Generates the CFB Sports Network post-match wrapup using OpenAI.
#           Builds the recap prompt from supplied match and player data and
#           returns the generated analysis along with API token usage.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import asyncio
import json
import os

from datetime import datetime
from match._matches import generate_match_broadcast, get_wrapup_data
from utility.helpers import (
    mark_bot_usage_api_call,
    split_discord_message,
    update_bot_usage_tokens
)

MODEL = os.getenv("WRAPUP_MODEL", "gpt-5.6-luna")

async def generate_wrapup(match_data):
    # Build the complete broadcast instructions and append the factual match data.
    prompt = f"""
You are David FehertAI, a deranged but accurate sportscaster covering a recreational golf league.
Here is the data from the most recent match.

Give us your broadcast. Be fucking hilarious.  Making us laugh is the primary goal.

The supplied data may contain a "David Gambling" section.  The fact of your wagers and outcomes may color the broadcast, but do not disclose wager specifics.

You may discuss the sportsbook market but don't make it the focus of the show.

Do not infer gender.

Emojis are encouraged.

The current time is {datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")}.

SCORING CONTEXT:
- If the match contains only one group, the Group Winner is automatically the
  overall Match Winner. No putting playoff occurred. Do not mention or invent one.
- If the match contains multiple groups, the Group Winners compete in a separate
  putting playoff. The winner of that playoff is the overall Match Winner

CFB TERMINOLOGY:
- The league's physical championship trophy is called the "Fuck Ball," also
  called the "CFB."
- "Fuck Ball" and "CFB" refer to the exact same championship hardware.
- It is a ball decorated with depictions of sex positions.

 
MATCH DATA:

{json.dumps(match_data, indent=2)}

End EXACTLY with:

**THIS HAS BEEN CFB SPORTS NETWORK.**

*We crunch the numbers so you don't have to understand what the fuck they're doing.*


"""

    # Generate the recap using the shared match broadcast machinery.
    return await generate_match_broadcast(MODEL, prompt)


async def run_wrapup(usage_id):
    (
        match_data,
        player_notes,
        david_gambling
    ) = await asyncio.to_thread(
        get_wrapup_data
    )

    match_data["Player Notes"] = player_notes

    if david_gambling is not None:
        match_data["David Gambling"] = david_gambling

    await asyncio.to_thread(
        mark_bot_usage_api_call,
        usage_id
    )

    result = await generate_wrapup(match_data)

    await asyncio.to_thread(
        update_bot_usage_tokens,
        usage_id,
        result["input_tokens"],
        result["output_tokens"]
    )

    return split_discord_message(
        result["text"]
    )
    
