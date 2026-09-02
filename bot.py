import os
import discord
from discord import app_commands
from dotenv import load_dotenv
from commands import register_commands

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DEV_CHANNEL_ID = int(os.getenv("DEV_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
ADMIN_DISCORD_ID = int(os.getenv("ADMIN_DISCORD_ID"))

intents = discord.Intents.default()
intents.members = True

# CFB server used during development
DEV_GUILD = discord.Object(id=GUILD_ID)


class CFBBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Delete the old globally registered commands from Discord.
        # During development, commands will exist only in the CFB server.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()

        # Sync our guild-specific commands.
        synced = await self.tree.sync(guild=DEV_GUILD)

        print("SYNCED COMMANDS:", [cmd.name for cmd in synced])


bot = CFBBot()
register_commands(
    bot,
    DEV_GUILD,
    DEV_CHANNEL_ID,
    ADMIN_DISCORD_ID,
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DATABASE
)


@bot.event
async def on_ready():
    print(f"CFB Bot is online as {bot.user}")

bot.run(TOKEN)