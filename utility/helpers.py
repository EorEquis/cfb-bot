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

import asyncio
import discord
import mysql.connector
import re

from db._db import execute_upsert
from discord import app_commands
from match._matches import get_upcoming_matches


_mysql_host = None
_mysql_port = None
_mysql_database = None
_mysql_user = None
_mysql_password = None
_admin_discord_id = None
_admin_role_id = None


def _database_operation(operation, commit=False):
    connection = mysql.connector.connect(
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = None

    try:
        cursor = connection.cursor()
        result = operation(cursor)

        if commit:
            connection.commit()

        return result

    except Exception:
        if commit:
            connection.rollback()

        raise

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()


def _split_oversized_discord_section(section, limit):
    chunks = []

    while len(section) > limit:
        target = min(len(section) // 2, limit)
        minimum = max(0, target - 500)
        maximum = min(limit, target + 500)

        sentence_breaks = [
            match.end()
            for match in re.finditer(
                r"(?<=[.!?])(?:[ \t]+|\n+)",
                section[minimum:maximum]
            )
        ]

        if sentence_breaks:
            split_at = min(
                (
                    minimum + position
                    for position in sentence_breaks
                ),
                key=lambda position: abs(position - target)
            )
        else:
            split_at = section.rfind("\n", 0, limit)

            if split_at == -1:
                split_at = section.rfind(" ", 0, limit)

            if split_at == -1:
                split_at = limit

        chunks.append(section[:split_at].strip())
        section = section[split_at:].strip()

    if section:
        chunks.append(section)

    return chunks


def _split_discord_sections(text):
    lines = text.split("\n")
    sections = []
    current = []

    for line in lines:
        is_heading = re.match(r"^##\s+\S", line)
        is_numbered_entry = re.match(r"^(?:\*\*)?\d+\.\s+\S", line)

        if (is_heading or is_numbered_entry) and current:
            sections.append("\n".join(current).strip())
            current = []

        current.append(line)

    if current:
        sections.append("\n".join(current).strip())

    return [section for section in sections if section]


def configure_helpers(
    mysql_host,
    mysql_port,
    mysql_database,
    mysql_user,
    mysql_password,
    admin_discord_id,
    admin_role_id
):
    global _mysql_host
    global _mysql_port
    global _mysql_database
    global _mysql_user
    global _mysql_password
    global _admin_discord_id
    global _admin_role_id

    _mysql_host = mysql_host
    _mysql_port = mysql_port
    _mysql_database = mysql_database
    _mysql_user = mysql_user
    _mysql_password = mysql_password
    _admin_discord_id = admin_discord_id
    _admin_role_id = admin_role_id

    
async def active_match_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:

    matches = await asyncio.to_thread(
        get_upcoming_matches
    )

    choices = []

    for match in matches:
        date_text = str(match["match_date"])
        location = match["location"]

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

    
def apply_availability(
    player_id: int,
    player_name: str,
    status: str
):
    connection = mysql.connector.connect(
        connection_timeout=5,
        host=_mysql_host,
        port=_mysql_port,
        database=_mysql_database,
        user=_mysql_user,
        password=_mysql_password
    )

    cursor = None

    try:
        # Lock the shared match row so concurrent availability changes make
        # their capacity decisions one at a time.
        connection.start_transaction()
        cursor = connection.cursor()
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
            AND TIMESTAMP(
                match_date,
                GREATEST(
                    COALESCE(tee_time_1, '00:00:00'),
                    COALESCE(tee_time_2, '00:00:00'),
                    COALESCE(tee_time_3, '00:00:00'),
                    COALESCE(tee_time_4, '00:00:00')
                )
            ) >= NOW()
            ORDER BY match_date
            LIMIT 1
            FOR UPDATE
            """
        )

        match = cursor.fetchone()

        if match is None:
            connection.rollback()
            return None, "There are no upcoming CFB matches scheduled."

        (
            match_id,
            match_date,
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4
        ) = match

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
                    connection.rollback()
                    return (
                        None,
                        f"That match is currently full — "
                        f"{in_count} of {capacity} spots are claimed."
                    )

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

        return (
            f"**{player_name}** is **{status.upper()}** "
            f"for {match_date:%A, %B %d}.",
            None
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()


def bot_admin_only(interaction: discord.Interaction):
    # Permanent/bootstrap admin from .env
    if interaction.user.id == _admin_discord_id:
        return True

    # Configured Discord administrator role
    if any(role.id == _admin_role_id for role in interaction.user.roles):
        return True

    return False


def dev_channel_only(interaction: discord.Interaction) -> bool:
    return True
    
def log_bot_usage(
    command_name,
    discord_user_id
):
    def insert_usage(cursor):
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

        return cursor.lastrowid

    return _database_operation(insert_usage, commit=True)


def mark_bot_usage_api_call(usage_id):
    execute_upsert(
        """
        UPDATE bot_usage
        SET api_call = TRUE
        WHERE id = %s
        """,
        (usage_id,)
    )
    
    
async def player_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    def load_players(cursor):
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

        return cursor.fetchall()

    rows = await asyncio.to_thread(
        _database_operation,
        load_players
    )

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


########## Availability UI ##########

class AvailabilityPlayerSelect(discord.ui.Select):
    def __init__(self, availability_view):
        self.availability_view = availability_view

        page_start = availability_view.page * 25
        page_players = availability_view.players[
            page_start:page_start + 25
        ]

        options = []

        for player_id, player_name, display_name in page_players:
            if display_name:
                label = f"{player_name} ({display_name})"
            else:
                label = player_name

            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(player_id),
                    default=(
                        player_id
                        == availability_view.selected_player_id
                    )
                )
            )

        super().__init__(
            placeholder="Select a CFB player",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        self.availability_view.selected_player_id = int(
            self.values[0]
        )

        self.availability_view.refresh_items()

        await interaction.response.edit_message(
            content=self.availability_view.prompt(),
            view=self.availability_view
        )


class AvailabilityPlayerView(discord.ui.View):
    def __init__(
        self,
        invoking_admin_id: int,
        status: str,
        players,
        default_player_id: int
    ):
        super().__init__(timeout=120)

        self.invoking_admin_id = invoking_admin_id
        self.status = status
        self.players = players
        self.player_names = {
            player_id: player_name
            for player_id, player_name, _ in players
        }
        self.selected_player_id = default_player_id
        self.page_count = (
            (len(players) + 24) // 25
        )
        self.page = next(
            (
                index // 25
                for index, player in enumerate(players)
                if player[0] == default_player_id
            ),
            0
        )

        self.refresh_items()

    def prompt(self):
        selected_name = self.player_names[
            self.selected_player_id
        ]

        return (
            f"Select the player to mark **{self.status.upper()}**.\n"
            f"Currently selected: **{selected_name}**"
        )

    def refresh_items(self):
        self.clear_items()

        self.add_item(
            AvailabilityPlayerSelect(self)
        )

        self.previous_page.disabled = self.page == 0
        self.next_page.disabled = (
            self.page >= self.page_count - 1
        )

        if self.page_count > 1:
            self.add_item(self.previous_page)
            self.add_item(self.next_page)

        self.add_item(self.confirm)

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:
        if interaction.user.id != self.invoking_admin_id:
            await interaction.response.send_message(
                "This player picker belongs to another administrator.",
                ephemeral=True
            )
            return False

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to perform this action.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        self.page -= 1
        self.refresh_items()

        await interaction.response.edit_message(
            content=self.prompt(),
            view=self
        )

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        self.page += 1
        self.refresh_items()

        await interaction.response.edit_message(
            content=self.prompt(),
            view=self
        )

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.green
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        player_id = self.selected_player_id
        player_name = self.player_names[player_id]

        message, error = await asyncio.to_thread(
            apply_availability,
            player_id,
            player_name,
            self.status
        )

        if error:
            await interaction.response.edit_message(
                content=error,
                view=None
            )
            self.stop()
            return

        await interaction.response.edit_message(
            content=(
                f"Updated **{player_name}** to "
                f"**{self.status.upper()}**."
            ),
            view=None
        )

        await interaction.followup.send(
            message,
            ephemeral=False
        )

        self.stop()


async def set_availability(
    interaction: discord.Interaction,
    status: str
):
    await asyncio.to_thread(
        log_bot_usage,
        status,
        interaction.user.id
    )

    if not dev_channel_only(interaction):
        await interaction.response.send_message(
            "CFB Bot is currently restricted to #cfb-bot-dev.",
            ephemeral=True
        )
        return

    is_admin = bot_admin_only(interaction)

    def load_players(cursor):
        cursor.execute(
            """
            SELECT id, player_name
            FROM players
            WHERE discord_user_id = %s
            AND active = TRUE
            """,
            (interaction.user.id,)
        )

        invoking_player = cursor.fetchone()

        if is_admin:
            cursor.execute(
                """
                SELECT
                    id,
                    player_name,
                    discord_display_name
                FROM players
                WHERE active = TRUE
                ORDER BY player_name
                """
            )

            players = cursor.fetchall()
        else:
            players = None

        return invoking_player, players

    invoking_player, players = await asyncio.to_thread(
        _database_operation,
        load_players
    )

    if invoking_player is None and not is_admin:
        await interaction.response.send_message(
            "I couldn't find you in the CFB player list.",
            ephemeral=True
        )
        return

    if not is_admin:
        player_id, player_name = invoking_player

        message, error = await asyncio.to_thread(
            apply_availability,
            player_id,
            player_name,
            status
        )

        if error:
            await interaction.response.send_message(
                error,
                ephemeral=True
            )
            return

        await interaction.response.send_message(message)
        return

    if not players:
        await interaction.response.send_message(
            "There are no active CFB players.",
            ephemeral=True
        )
        return

    if invoking_player is not None:
        default_player_id = invoking_player[0]
    else:
        default_player_id = players[0][0]

    view = AvailabilityPlayerView(
        invoking_admin_id=interaction.user.id,
        status=status,
        players=players,
        default_player_id=default_player_id
    )

    await interaction.response.send_message(
        view.prompt(),
        view=view,
        ephemeral=True
    )

def split_discord_message(text, limit=1950):
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    sections = _split_discord_sections(text)
    chunks = []
    current = ""

    for section in sections:
        if len(section) > limit:
            if current:
                chunks.append(current)
                current = ""

            oversized_chunks = _split_oversized_discord_section(
                section,
                limit
            )

            chunks.extend(oversized_chunks[:-1])
            current = oversized_chunks[-1]
            continue

        candidate = (
            f"{current}\n\n{section}"
            if current
            else section
        )

        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = section

    if current:
        chunks.append(current)

    return chunks


def update_bot_usage_tokens(
    usage_id,
    input_tokens,
    output_tokens
):
    execute_upsert(
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