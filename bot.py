###################
# Created : 2026-08-30 GB
# Purpose : Main entry point for the CFB Bot.
#           Loads configuration, initializes database logging and Discord,
#           registers bot commands, and starts the Discord client.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

# Load configuration values from the .env file before importing application modules.
# Some imported modules use environment variables during initialization.
from dotenv import load_dotenv
load_dotenv()

import discord
import logging
import os
import sys
from app_log import DatabaseLogHandler
from commands import register_commands
from discord import app_commands


# Create a standard Python logger for this module.
# Messages written to this logger are handled by the database logging
# configuration established below.
logger = logging.getLogger(__name__)


# Logging level can be supplied as the first command-line argument when the bot
# is started (DEBUG, INFO, WARNING, etc.). Default to INFO if none is supplied.
LOG_LEVEL_NAME = sys.argv[1].upper() if len(sys.argv) > 1 else "INFO"
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, None)

# getattr() returns None for an invalid logging level. Valid Python logging
# levels resolve to integers, so reject anything else before starting the bot.
if not isinstance(LOG_LEVEL, int):
    raise ValueError(f"Invalid logging level: {LOG_LEVEL_NAME}")


# Application configuration loaded from .env.
# IDs and the MySQL port are converted to integers because environment
# variables are loaded as strings.
ADMIN_DISCORD_ID = int(os.getenv("ADMIN_DISCORD_ID"))
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")

if not ADMIN_ROLE_ID or not ADMIN_ROLE_ID.isdigit():
    raise ValueError(
        "ADMIN_ROLE_ID must be configured as a numeric Discord role ID."
    )

ADMIN_ROLE_ID = int(ADMIN_ROLE_ID)
BOT_VERSION = os.getenv("BOT_VERSION")
DEV_CHANNEL_ID = int(os.getenv("DEV_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
TOKEN = os.getenv("DISCORD_TOKEN")


# Send Python logging output to the MariaDB bot_log table.
# DatabaseLogHandler is defined in app_log.py.
db_log_handler = DatabaseLogHandler(
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_DATABASE,
    MYSQL_USER,
    MYSQL_PASSWORD
)

db_log_handler.setLevel(LOG_LEVEL)

# Attach the database handler to Python's root logger so logging performed
# throughout the application can use the same database-backed logging system.
logging.getLogger().addHandler(db_log_handler)
logging.getLogger().setLevel(LOG_LEVEL)


# Discord intents determine which categories of Discord events the bot receives.
# Start with Discord's default set and explicitly enable member information.
intents = discord.Intents.default()
intents.members = True


# Discord guild (server) where CFB commands are registered during development.
# Keeping commands guild-specific makes command changes available immediately
# rather than waiting for Discord's global command propagation.
DEV_GUILD = discord.Object(id=GUILD_ID)


# Discord client for the CFB Bot.
# The CommandTree holds the bot's slash commands.
class CFBBot(discord.Client):
    def __init__(self):
        # Treat all message content as untrusted by default. Literal mention
        # text remains visible without notifying users, roles, @here, or @everyone.
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none()
        )
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Remove any old globally registered slash commands.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()

        # Register/sync the current commands specifically to the CFB guild.
        synced = await self.tree.sync(guild=DEV_GUILD)

        print("SYNCED COMMANDS:", [cmd.name for cmd in synced])


# Create the Discord client, then register all slash commands defined in
# commands.py with this client's CommandTree.
bot = CFBBot()

register_commands(
    bot,
    BOT_VERSION,
    DEV_GUILD,
    ADMIN_DISCORD_ID,
    ADMIN_ROLE_ID,
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_DATABASE,
    MYSQL_USER,
    MYSQL_PASSWORD
)


# Discord event handlers.
# The @bot.event decorator registers each function with the Discord client;
# Discord calls them automatically when the corresponding event occurs.

@bot.event
async def on_disconnect():
    # Discord connection was lost.
    logger.warning("Disconnected from Discord")


@bot.event
async def on_ready():
    # Bot has successfully connected to Discord and is ready for use.
    logger.info(f"CFB Bot v{BOT_VERSION} is online as {bot.user}")
    print(f"CFB Bot v{BOT_VERSION} is online as {bot.user}")


@bot.event
async def on_resumed():
    # An interrupted Discord session successfully resumed.
    logger.info("Discord session resumed")


# Start the Discord client. This is the point where execution effectively
# hands control over to discord.py's event loop and the bot begins running.
# Discord's own log handler is disabled because application logging is handled
# by our DatabaseLogHandler instead.
bot.run(TOKEN, log_handler=None)