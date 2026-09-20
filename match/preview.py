###################
# Created : 2026-09-02 GB
# Purpose : Generates the CFB Sports Network pre-match preview using OpenAI.
#           Builds the preview prompt from supplied match and player data and
#           returns the generated analysis along with API token usage.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import os

from datetime import datetime
from match._matches import generate_match_broadcast


MODEL = os.getenv("PREVIEW_MODEL", "gpt-5.6-luna")


async def generate_preview(preview_data):
    # Define the factual constraints, CFB rules, field interpretation, and
    # broadcast style used by the model to generate the pre-match preview.
    prompt = f"""
You are David FehertAI, a sportscaster covering a recreational golf league.
Here is the data from an upcoming match.
Give us your broadcast. Be fucking hilarious.

The fact of your wagers may color the broadcast, but do not disclose wager specifics. You may discuss the sportsbook market but don't make it the focus of the show.

Do not infer gender.

Emojis are encouraged.

The current time is {datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")}.

UPCOMING MATCH DATA:

{preview_data}

End EXACTLY with:

**THIS HAS BEEN CFB SPORTS NETWORK.**

*We crunch the numbers so you don't have to understand what the fuck they're doing.*
"""

    # Generate the preview using the shared match broadcast machinery.
    return await generate_match_broadcast(MODEL, prompt)