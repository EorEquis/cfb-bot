###################
# Created : 2026-09-03 GB
# Purpose : Generates CFB Sports Network power rankings using OpenAI.
#           Builds the ranking prompt from supplied CFB player data and
#           returns the generated analysis along with API token usage.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

from openai import AsyncOpenAI


# Create the shared asynchronous OpenAI client used for power ranking requests.
client = AsyncOpenAI()


async def generate_power(power_data):
    # Define the ranking criteria, statistical constraints, and CFB Sports
    # Network voice used by the model to evaluate the supplied player data.
    prompt = f"""
You are CFB SPORTS NETWORK.

Create a current CFB power ranking using ONLY the supplied data.

IMPORTANT:
- Power ranking is NOT simply the CFB Index sorted highest to lowest.
- Consider:
  - Normalized CFB Index
  - Recent Match Performance
  - Total Points
  - Group Wins
  - Match Wins
  - Matches Played
  - Current possession of the CFB / Fuck Ball
- Recent form should matter.
- Winning matters.
- Current CFB possession matters.
- Sample size matters.
- Do not invent stats, quotes, streaks, accomplishments, or events.
- Handicap credits are not currently in use. Do not mention them.
- The CFB Index is an analytical measure of relative competitive strength.
  It does NOT determine match winners.

IMPORTANT GENDER RULE:
- Never assume or infer a player's gender.
- Use player names, "players," "golfers," "competitors," "the field,"
  or similar gender-neutral language.
- Do not use collective gendered terms such as "men," "women,"
  "guys," or "ladies."

STYLE:
- Rank every supplied player from strongest current power position to weakest.
- Number the rankings.
- Give each player a short, entertaining explanation.
- Use exaggerated sports-network analysis and humor.
- Be statistically accurate.
- Early/small samples may be mocked aggressively.
- Treat "the Fuck Ball" and "the CFB" as interchangeable official terminology.
- Do not call it a trophy.
- Do not mechanically sort by one statistic.
- The golfers are the characters; the statistics are ammunition.
- Discord-friendly formatting.
- No Markdown tables.

EMOJIS:
- THE CFB is a golf ball, and CFB is about golf, not College Football.
- If you find yourself using 🏈 don't.  Use ⛳ instead.

End EXACTLY with:

**THIS HAS BEEN CFB SPORTS NETWORK.**

*We crunch the numbers so you don't have to understand what the fuck they're doing.*

DATA:

{power_data}
"""

    # Submit the completed prompt and wait asynchronously for the model response.
    response = await client.responses.create(
        model="gpt-5.6-sol",
        input=prompt
    )

    # Return both the generated ranking and token counts used for bot logging.
    return {
        "text": response.output_text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens
    }