###################
# Created : 2026-09-05 GB
# Purpose : Provides shared helper functions used by CFB Bot commands.
#           Includes Discord utility functions, database-backed helpers,
#           autocomplete callbacks, authorization checks, and other
#           supporting command logic.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import discord
import mysql.connector
from discord import app_commands


_mysql_host = None
_mysql_port = None
_mysql_database = None
_mysql_user = None
_mysql_password = None
_admin_discord_id = None


def configure_helpers(
    mysql_host,
    mysql_port,
    mysql_database,
    mysql_user,
    mysql_password,
    admin_discord_id
):
    global _mysql_host
    global _mysql_port
    global _mysql_database
    global _mysql_user
    global _mysql_password
    global _admin_discord_id

    _mysql_host = mysql_host
    _mysql_port = mysql_port
    _mysql_database = mysql_database
    _mysql_user = mysql_user
    _mysql_password = mysql_password
    _admin_discord_id = admin_discord_id

    
async def active_match_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:

    connection = mysql.connector.connect(
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT match_date, location
        FROM matches
        WHERE active = TRUE
        ORDER BY match_date
        """
    )

    matches = cursor.fetchall()

    cursor.close()
    connection.close()

    choices = []

    for match_date, location in matches:
        date_text = str(match_date)

        if current.lower() in date_text.lower() or current.lower() in location.lower():
            choices.append(
                app_commands.Choice(
                    name=f"{date_text} — {location}",
                    value=date_text
                )
            )

    return choices[:25]


def admin_only(func):
    func.admin_only = True
    return func

    
def bot_admin_only(interaction: discord.Interaction):
    # Permanent/bootstrap admin from .env
    if interaction.user.id == _admin_discord_id:
        return True

    # Discord Admins role
    if any(role.name == "Admins" for role in interaction.user.roles):
        return True

    return False


def dev_channel_only(interaction: discord.Interaction) -> bool:
    return True
    
def log_bot_usage(
    command_name,
    discord_user_id
):
    conn = mysql.connector.connect(
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO bot_usage
            (
                command_name,
                discord_user_id,
                api_call
            )
        VALUES (%s, %s, FALSE)
        """,
        (
            command_name,
            discord_user_id
        )
    )

    usage_id = cursor.lastrowid

    conn.commit()
    cursor.close()
    conn.close()

    return usage_id


def mark_bot_usage_api_call(usage_id):
    conn = mysql.connector.connect(
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE bot_usage
        SET api_call = TRUE
        WHERE id = %s
        """,
        (usage_id,)
    )

    conn.commit()
    cursor.close()
    conn.close()
    
    
async def player_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    conn = mysql.connector.connect(
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            player_name,
            discord_display_name
        FROM players
        WHERE active = TRUE
        AND (
                player_name LIKE %s
            OR discord_display_name LIKE %s
        )
        ORDER BY player_name
        LIMIT 25
        """,
        (
            f"%{current}%",
            f"%{current}%"
        )
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    choices = []

    for player_name, display_name in rows:
        if display_name:
            label = f"{player_name} ({display_name})"
        else:
            label = player_name

        choices.append(
            app_commands.Choice(
                name=label,
                value=player_name
            )
        )

    return choices


async def set_availability(
    interaction: discord.Interaction,
    status: str
):
    log_bot_usage(
        status,
        interaction.user.id
    )

    if not dev_channel_only(interaction):
        await interaction.response.send_message(
            "CFB Bot is currently restricted to #cfb-bot-dev.",
            ephemeral=True
        )
        return

    connection = mysql.connector.connect(
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id, player_name
        FROM players
        WHERE discord_user_id = %s
          AND active = TRUE
        """,
        (interaction.user.id,)
    )

    player = cursor.fetchone()

    if player is None:
        cursor.close()
        connection.close()

        await interaction.response.send_message(
            "I couldn't find you in the CFB player list.",
            ephemeral=True
        )
        return

    player_id, player_name = player

    cursor.execute(
        """
        SELECT
            id,
            match_date,
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4
        FROM matches
        WHERE active = TRUE
        AND match_date >= CURDATE()
        ORDER BY match_date
        LIMIT 1
        """
    )

    match = cursor.fetchone()

    if match is None:
        cursor.close()
        connection.close()

        await interaction.response.send_message(
            "There are no upcoming CFB matches scheduled.",
            ephemeral=True
        )
        return

    match_id, match_date, tee_time_1, tee_time_2, tee_time_3, tee_time_4 = match

    capacity = sum(
        tee_time is not None
        for tee_time in (
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4
        )
    ) * 4

    if status == "in":
        cursor.execute(
            """
            SELECT status
            FROM availability
            WHERE match_id = %s
            AND player_id = %s
            """,
            (match_id, player_id)
        )

        current = cursor.fetchone()

        if current is None or current[0] != "in":
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM availability
                WHERE match_id = %s
                AND status = 'in'
                """,
                (match_id,)
            )

            in_count = cursor.fetchone()[0]

            if in_count >= capacity:
                cursor.close()
                connection.close()

                await interaction.response.send_message(
                    f"That match is currently full — {in_count} of {capacity} spots are claimed.",
                    ephemeral=True
                )
                return

    cursor.execute(
        """
        INSERT INTO availability
            (match_id, player_id, status)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            status = VALUES(status)
        """,
        (match_id, player_id, status)
    )

    connection.commit()
    cursor.close()
    connection.close()

    await interaction.response.send_message(
        f"**{player_name}** is **{status.upper()}** "
        f"for {match_date:%A, %B %d}."
    )
    
    
def split_discord_message(text, limit=2000):
    chunks = []

    while len(text) > limit:
        # Prefer splitting at a line break
        split_at = text.rfind("\n", 0, limit)

        # Otherwise split at a space
        if split_at == -1:
            split_at = text.rfind(" ", 0, limit)

        # Absolute fallback
        if split_at == -1:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    if text:
        chunks.append(text)

    return chunks


def update_bot_usage_tokens(
    usage_id,
    input_tokens,
    output_tokens
):
    conn = mysql.connector.connect(
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE bot_usage
        SET
            input_tokens = %s,
            output_tokens = %s
        WHERE id = %s
        """,
        (
            input_tokens,
            output_tokens,
            usage_id
        )
    )

    conn.commit()
    cursor.close()
    conn.close()    