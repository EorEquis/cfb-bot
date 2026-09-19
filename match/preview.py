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
from openai import AsyncOpenAI



# Create the shared asynchronous OpenAI client used for preview requests.
client = AsyncOpenAI()

MODEL = os.getenv("PREVIEW_MODEL", "gpt-5.6-luna")


async def generate_preview(preview_data):
    # Define the factual constraints, CFB rules, field interpretation, and
    # broadcast style used by the model to generate the pre-match preview.
    prompt = f"""
You are David FehertAI, a sportscaster covering a recreational golf league.
Here is the data from an upcoming match.
Give us your broadcast. Be fucking hilarious.

The fact of your wagers may color the broadcast, but do not disclose wager specifics. You may freely discuss the sportsbook market.

Do not infer gender.

Emojis are encouraged.

The current time is {datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")}.

UPCOMING MATCH DATA:

{preview_data}

End EXACTLY with:

**THIS HAS BEEN CFB SPORTS NETWORK.**

*We crunch the numbers so you don't have to understand what the fuck they're doing.*
"""

    # Submit the completed prompt and wait asynchronously for the model response.
    response = await client.responses.create(
        model=MODEL,
        input=prompt
    )

    # Return both the generated preview and token counts used for bot logging.
    return {
        "text": response.output_text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens
    }