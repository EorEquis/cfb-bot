###################
# Created : 2026-09-15 GB
# Purpose : Delivers Tan City After Dark episodes through the dedicated
#           Tan City Discord bot account.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 7
#           OpenAI model/version: GPT-5.6 Sol
###################

import discord
import os


TAN_CITY_BOT_TOKEN = os.getenv("TAN_CITY_BOT_TOKEN")


async def send_tan_city_episode(channel_id, chunks):
    intents = discord.Intents.none()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            channel = await client.fetch_channel(channel_id)

            for chunk in chunks:
                await channel.send(chunk)

        finally:
            await client.close()

    await client.start(TAN_CITY_BOT_TOKEN)