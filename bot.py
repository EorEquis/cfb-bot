import os
import discord
import sys
import logging
from discord import app_commands
from dotenv import load_dotenv
from commands import register_commands
from app_log import DatabaseLogHandler

load_dotenv()

logger = logging.getLogger(__name__)

LOG_LEVEL_NAME = sys.argv[1].upper() if len(sys.argv) > 1 else "INFO"

LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, None)

if not isinstance(LOG_LEVEL, int):
    raise ValueError(f"Invalid logging level: {LOG_LEVEL_NAME}")

BOT_VERSION = "1.1.0-dev"

TOKEN = os.getenv("DISCORD_TOKEN")
DEV_CHANNEL_ID = int(os.getenv("DEV_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
ADMIN_DISCORD_ID = int(os.getenv("ADMIN_DISCORD_ID"))

db_log_handler = DatabaseLogHandler(
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DATABASE
)

db_log_handler.setLevel(LOG_LEVEL)

logging.getLogger().addHandler(db_log_handler)
logging.getLogger().setLevel(LOG_LEVEL)

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
    logger.info(f"CFB Bot v{BOT_VERSION} is online as {bot.user}")
    print(f"CFB Bot v{BOT_VERSION} is online as {bot.user}")
    
@bot.event
async def on_resumed():
    logger.info("Discord session resumed")

@bot.event
async def on_disconnect():
    logger.warning("Disconnected from Discord")
        
bot.run(TOKEN, log_handler=None)