###################
# Created : 2026-08-30 GB
# Purpose : Registers Discord slash commands for the CFB Bot.
#           Handles match administration, player availability and profiles,
#           league information, and CFB Sports Network AI commands.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import asyncio
import discord
import logging
import mysql.connector

from datetime import datetime
from discord import app_commands
from helpers import (
    active_match_autocomplete,
    admin_only,
    bot_admin_only,
    configure_helpers,
    dev_channel_only,
    log_bot_usage,
    mark_bot_usage_api_call,
    player_autocomplete,
    set_availability,
    split_discord_message,
    update_bot_usage_tokens
)
from power import generate_power
from preview import generate_preview
from sheets import (
    get_latest_match_with_history,
    get_player_profile,
    get_power_data,
    get_preview_data
)
from weather import (
    format_time,
    get_forecast,
    weather_emoji
)
from wrapup import generate_wrapup

logger = logging.getLogger(__name__)

def register_commands(
    bot,
    bot_version,
    dev_guild,
    admin_discord_id,
    admin_role_id,
    mysql_host,
    mysql_port,
    mysql_database,
    mysql_user,
    mysql_password
):

    # Supply shared helper configuration once before registering commands.
    configure_helpers(
        mysql_host,
        mysql_port,
        mysql_database,
        mysql_user,
        mysql_password,
        admin_discord_id,
        admin_role_id
    )

    # Run one complete database operation on a worker thread so MariaDB never
    # blocks Discord's event loop. Database resources stay on the same thread.
    def database_operation(operation, commit=False):
        connection = mysql.connector.connect(
            connection_timeout=5,
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
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


    # Add a new active match after validating the date and any supplied tee times.
    @bot.tree.command(
        name="addmatch",
        description="Add a new CFB match",
        guild=dev_guild
    )
    @admin_only
    @app_commands.describe(
        match_date="Match date in YYYY-MM-DD format",
        location="Match location",
        tee_time_1="First tee time in HH:MM format",
        tee_time_2="Second tee time in HH:MM format",
        tee_time_3="Third tee time in HH:MM format",
        tee_time_4="Fourth tee time in HH:MM format",
        notes="Optional match notes"
    )
    async def addmatch(
        interaction: discord.Interaction,
        match_date: str,
        location: str,
        tee_time_1: str,
        tee_time_2: str | None = None,
        tee_time_3: str | None = None,
        tee_time_4: str | None = None,
        notes: str | None = None
    ):
        await asyncio.to_thread(
            log_bot_usage,
            "addmatch",
            interaction.user.id
        )

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        try:
            datetime.strptime(match_date, "%Y-%m-%d")
        except ValueError:
            await interaction.response.send_message(
                "Invalid date. Use YYYY-MM-DD.",
                ephemeral=True
            )
            return

        for tee_time in (tee_time_1, tee_time_2, tee_time_3, tee_time_4):
            if tee_time is not None:
                try:
                    datetime.strptime(tee_time, "%H:%M")
                except ValueError:
                    await interaction.response.send_message(
                        "Invalid tee time. Use HH:MM.",
                        ephemeral=True
                    )
                    return

        def add_match_record(cursor):
            cursor.execute(
                """
                SELECT id
                FROM matches
                WHERE match_date = %s
                AND active = TRUE
                LIMIT 1
                """,
                (match_date,)
            )

            if cursor.fetchone():
                return False

            cursor.execute(
                """
                INSERT INTO matches
                    (
                        match_date,
                        location,
                        tee_time_1,
                        tee_time_2,
                        tee_time_3,
                        tee_time_4,
                        notes,
                        active
                    )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, TRUE)
                """,
                (
                    match_date,
                    location,
                    tee_time_1,
                    tee_time_2,
                    tee_time_3,
                    tee_time_4,
                    notes
                )
            )

            return True

        match_added = await asyncio.to_thread(
            database_operation,
            add_match_record,
            True
        )

        if not match_added:
            await interaction.response.send_message(
                f"A match already exists on **{match_date}**.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Match added for **{match_date}** at **{location}**.",
            ephemeral=True
        )

    # Soft-delete an active match selected by date.
    @bot.tree.command(
        name="deletematch",
        description="Delete an existing CFB match",
        guild=dev_guild
    )
    @admin_only
    @app_commands.autocomplete(
        match_date=active_match_autocomplete
    )
    async def deletematch(
        interaction: discord.Interaction,
        match_date: str
    ):
        await asyncio.to_thread(
            log_bot_usage,
            "deletematch",
            interaction.user.id
        )

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        def delete_match_record(cursor):
            cursor.execute(
                """
                SELECT location
                FROM matches
                WHERE match_date = %s
                  AND active = TRUE
                LIMIT 1
                """,
                (match_date,)
            )

            match = cursor.fetchone()

            if not match:
                return None

            cursor.execute(
                """
                UPDATE matches
                SET active = FALSE
                WHERE match_date = %s
                  AND active = TRUE
                """,
                (match_date,)
            )

            return match[0]

        location = await asyncio.to_thread(
            database_operation,
            delete_match_record,
            True
        )

        if location is None:
            await interaction.response.send_message(
                f"No active match found for **{match_date}**.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Deleted match for **{match_date}** at **{location}**.",
            ephemeral=True
        )

    # Update one editable field on an active match; optional fields may be cleared.
    @bot.tree.command(
        name="editmatch",
        description="Edit an existing CFB match",
        guild=dev_guild
    )
    @admin_only
    @app_commands.autocomplete(
        match_date=active_match_autocomplete
    )
    @app_commands.choices(
        field=[
            app_commands.Choice(name="Location", value="location"),
            app_commands.Choice(name="Notes", value="notes"),
            app_commands.Choice(name="Special Rule", value="special_rule"),
            app_commands.Choice(name="Tee Time 1", value="tee_time_1"),
            app_commands.Choice(name="Tee Time 2", value="tee_time_2"),
            app_commands.Choice(name="Tee Time 3", value="tee_time_3"),
            app_commands.Choice(name="Tee Time 4", value="tee_time_4")
        ]
    )
    async def editmatch(
        interaction: discord.Interaction,
        match_date: str,
        field: app_commands.Choice[str],
        value: str
    ):
        await asyncio.to_thread(
            log_bot_usage,
            "editmatch",
            interaction.user.id
        )

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        allowed_fields = {
            "location",
            "notes",
            "special_rule",
            "tee_time_1",
            "tee_time_2",
            "tee_time_3",
            "tee_time_4"
        }

        if field.value not in allowed_fields:
            await interaction.response.send_message(
                "Invalid field.",
                ephemeral=True
            )
            return

        new_value = value

        if value.lower() == "clear":
            if field.value in ("location", "tee_time_1"):
                await interaction.response.send_message(
                    f"**{field.name}** cannot be cleared.",
                    ephemeral=True
                )
                return

            new_value = None

        elif field.value.startswith("tee_time_"):
            try:
                datetime.strptime(value, "%H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "Invalid tee time. Use HH:MM, or `clear` to remove an optional tee time.",
                    ephemeral=True
                )
                return

        def update_match_record(cursor):
            cursor.execute(
                f"""
                UPDATE matches
                SET {field.value} = %s
                WHERE match_date = %s
                  AND active = TRUE
                """,
                (
                    new_value,
                    match_date
                )
            )

            return cursor.rowcount

        updated = await asyncio.to_thread(
            database_operation,
            update_match_record,
            True
        )

        if updated == 0:
            await interaction.response.send_message(
                f"No active match found for **{match_date}**.",
                ephemeral=True
            )
            return

        if new_value is None:
            await interaction.response.send_message(
                f"Cleared **{field.name}** for **{match_date}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Updated **{field.name}** for **{match_date}** to **{value}**.",
                ephemeral=True
            )
                                            
    # Build the command help display dynamically, hiding admin-only commands from non-admins.
    @bot.tree.command(
        name="helpbot",
        description="Show available CFB Bot commands",
        guild=dev_guild
    )
    async def helpbot(interaction: discord.Interaction):
        await asyncio.to_thread(
            log_bot_usage,
            "helpbot",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        commands = bot.tree.get_commands(guild=dev_guild)
        is_admin = bot_admin_only(interaction)

        visible_commands = []

        for command in commands:
            is_admin_only = getattr(
                command.callback,
                "admin_only",
                False
            )

            if is_admin_only and not is_admin:
                continue

            visible_commands.append(command)

        visible_commands = sorted(
            visible_commands,
            key=lambda cmd: cmd.name
        )

        lines = [
            f"📖 **CFB Bot v{bot_version} Commands**",
            ""
        ]

        for command in visible_commands:
            usage = f"/{command.name}"

            help_parameter_name = command.extras.get(
                "help_parameter_name"
            )

            for param in command.parameters:
                display_name = help_parameter_name or param.name

                if param.required:
                    usage += f" <{display_name}>"
                else:
                    usage += f" [{display_name}]"

            lines.append(
                f"`{usage}` — {command.description}"
            )

            for param in command.parameters:
                if param.description:
                    display_name = help_parameter_name or param.name

                    if param.required:
                        parameter_display = f"<{display_name}>"
                    else:
                        parameter_display = f"[{display_name}]"

                    lines.append(
                        f"   `{parameter_display}` - {param.description}"
                    )

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True
        )


    # Record the current player as IN for the next match.
    @bot.tree.command(
        name="in",
        description="Mark yourself as playing in the next CFB match",
        guild=dev_guild
    )
    async def playing_in(interaction: discord.Interaction):
        await set_availability(interaction, "in")


    # Provide the shared CFB Index spreadsheet link.
    @bot.tree.command(
        name="index",
        description="View the CFB Index spreadsheet",
        guild=dev_guild
    )
    async def index(interaction: discord.Interaction):
        await asyncio.to_thread(
            log_bot_usage,
            "index",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📜 **Official CFB Index:**\n"
            "https://docs.google.com/spreadsheets/d/"
            "14KFO24N0DGu24mRUu5BE6_vpObWGyFCYhKKGQRLG6Do/"
            "edit?usp=sharing"
        )


    # Show the next match, or all upcoming matches, with weather for the next match when available.
    @bot.tree.command(
        name="match",
        description="Show information for upcoming CFB matches",
        guild=dev_guild,
        extras={
            "help_parameter_name": "option"
        }
    )
    @app_commands.describe(
        show='Use "all" to show all upcoming matches'
    )
    @app_commands.choices(show=[
        app_commands.Choice(name="all", value="all")
    ])
    async def match(
        interaction: discord.Interaction,
        show: app_commands.Choice[str] | None = None
    ):
        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        await asyncio.to_thread(
            log_bot_usage,
            "match",
            interaction.user.id
        )

        show_all = show is not None and show.value == "all"

        def load_matches(cursor):
            cursor.execute(
                f"""
                SELECT
                    match_date,
                    location,
                    tee_time_1,
                    tee_time_2,
                    tee_time_3,
                    tee_time_4,
                    notes,
                    special_rule
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
                {"" if show_all else "LIMIT 1"}
                """
            )

            if show_all:
                return cursor.fetchall()

            match_row = cursor.fetchone()
            return [match_row] if match_row else []

        matches = await asyncio.to_thread(
            database_operation,
            load_matches
        )

        if not matches:
            await interaction.followup.send(
                "There are no upcoming CFB matches scheduled."
            )
            return

        # Local display helper for converting database tee-time intervals to 12-hour clock text.
        def format_tee_time(t):
            total_seconds = int(t.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            suffix = "AM" if hours < 12 else "PM"
            display_hour = hours % 12

            if display_hour == 0:
                display_hour = 12

            return f"{display_hour}:{minutes:02d} {suffix}"

        # Select an icon appropriate to the apparent temperature.
        def feels_like_emoji(apparent_temperature):
            if apparent_temperature <= 40:
                return "🥶"
            elif apparent_temperature >= 85:
                return "🥵"

            return "🌡️"

        blocks = []

        for (
            match_date,
            location,
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4,
            notes,
            special_rule
        ) in matches:

            tee_times = [
                tee_time_1,
                tee_time_2,
                tee_time_3,
                tee_time_4
            ]

            tee_times = [
                t for t in tee_times
                if t is not None
            ]

            if tee_times:
                tee_time_text = "\n".join(
                    f"⛳ **Tee Time {i}:** {format_tee_time(t)}"
                    for i, t in enumerate(
                        tee_times,
                        start=1
                    )
                )
            else:
                tee_time_text = "⛳ **Tee Times:** TBD"

            block = (
                f"📅 **{match_date:%A, %B %d}**\n"
                f"📍 **Location:** {location or 'TBD'}\n"
                f"{tee_time_text}"
            )

            if notes:
                block += f"\n📝 **Notes:** {notes}"

            if special_rule:
                block += f"\n🎲 **Special Rule:** {special_rule}"

            blocks.append(block)

        heading = (
            "🏌️ **UPCOMING CFB MATCHES**"
            if show_all
            else "🏌️ **NEXT CFB MATCH**"
        )

        message = (
            heading
            + "\n\n"
            + "\n\n────────────\n\n".join(blocks)
        )

        if not show_all:
            match_date, location, tee_time_1, _, _, _, _, _ = matches[0]

            if tee_time_1 is not None:
                try:
                    forecast_data = await asyncio.to_thread(
                        get_forecast,
                        match_date,
                        tee_time_1
                    )
                except Exception as e:
                    logger.error(f"FORECAST ERROR: {e}")
                    forecast_data = None

            else:
                forecast_data = None

            if forecast_data is not None:
                start = forecast_data["start"]
                end = forecast_data["end"]

                start_emoji = weather_emoji(start["weather_code"])
                end_emoji = weather_emoji(end["weather_code"])

                start_feels_like_emoji = feels_like_emoji(
                    start["apparent_temperature"]
                )
                end_feels_like_emoji = feels_like_emoji(
                    end["apparent_temperature"]
                )

                message += (
                    f"\n\n🌤️ **MATCH FORECAST**\n\n"

                    f"**{start_emoji} START — {format_time(start['time'])}**\n"
                    f"🌡️ Temp: **{start['temperature']}°F**\n"
                    f"💧 Humidity: **{start['humidity']}%**\n"
                    f"{start_feels_like_emoji} Feels Like: **{start['apparent_temperature']}°F**\n"
                    f"🌧️ Rain: **{start['rain_chance']}%**\n"
                    f"☁️ Cloud Cover: **{start['cloud_cover']}%**\n"
                    f"💨 Wind: **{start['wind_direction']} {start['wind_speed']} mph** "
                    f"(gusts {start['wind_gusts']} mph)\n\n"

                    f"**{end_emoji} END — {format_time(end['time'])}**\n"
                    f"🌡️ Temp: **{end['temperature']}°F**\n"
                    f"💧 Humidity: **{end['humidity']}%**\n"
                    f"{end_feels_like_emoji} Feels Like: **{end['apparent_temperature']}°F**\n"
                    f"🌧️ Rain: **{end['rain_chance']}%**\n"
                    f"☁️ Cloud Cover: **{end['cloud_cover']}%**\n"
                    f"💨 Wind: **{end['wind_direction']} {end['wind_speed']} mph** "
                    f"(gusts {end['wind_gusts']} mph)"
                )

            else:
                message += (
                    "\n\n🌤️ **MATCH FORECAST**\n\n"
                    "Unable to retrieve the forecast right now."
                )

        await interaction.followup.send(message)

    # Record the current player as MAYBE for the next match.
    @bot.tree.command(
        name="maybe",
        description="Mark yourself as maybe playing in the next CFB match",
        guild=dev_guild
    )
    async def playing_maybe(interaction: discord.Interaction):
        await set_availability(interaction, "maybe")


    # Record the current player as OUT for the next match.
    @bot.tree.command(
        name="out",
        description="Mark yourself as not playing in the next CFB match",
        guild=dev_guild
    )
    async def playing_out(interaction: discord.Interaction):
        await set_availability(interaction, "out")


    # Lightweight bot availability check.
    @bot.tree.command(
        name="ping",
        description="Make sure CFB Bot is alive",
        guild=dev_guild
    )
    async def ping(interaction: discord.Interaction):
        await asyncio.to_thread(
            log_bot_usage,
            "ping",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.send_message("https://klipy.com/gifs/cars-cruz-ramirez-2")

    # Display a player profile using database identity data and calculated CFB statistics.
    @bot.tree.command(
        name="player",
        description="Show a CFB player profile",
        guild=dev_guild
    )
    @app_commands.describe(
        player="Player name or Discord display name"
    )
    @app_commands.autocomplete(
        player=player_autocomplete
    )
    async def player(
        interaction: discord.Interaction,
        player: str
    ):
        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        await asyncio.to_thread(
            log_bot_usage,
            "player",
            interaction.user.id
        )

        def load_player(cursor):
            cursor.execute(
                """
                SELECT
                    player_name,
                    discord_display_name,
                    quote
                FROM players
                WHERE active = TRUE
                AND (
                        player_name = %s
                    OR discord_display_name = %s
                )
                LIMIT 1
                """,
                (
                    player,
                    player
                )
            )

            return cursor.fetchone()

        row = await asyncio.to_thread(
            database_operation,
            load_player
        )

        if row is None:
            await interaction.followup.send(
                f'No active CFB player found for "{player}".',
                ephemeral=True
            )
            return

        player_name, display_name, quote = row
        
        profile = await asyncio.to_thread(
            get_player_profile,
            player_name
        )

        message = (
            f"🏌️ **CFB PLAYER PROFILE**\n\n"
            f"**{player_name}**"
        )

        if display_name:
            message += f"\n🎮 Discord: **{display_name}**"

        message += (
            f"\n\n"
            f"📊 **CFB Index:** {profile['Current Index']:.2f}\n"
            f"⛳ **Matches Played:** {profile['Matches Played']}\n"
            f"🎯 **Total Points:** {profile['Total Points']:g}\n"
            f"🏆 **Group Wins:** {profile['Group Wins']}\n"
            f"👑 **Match Wins:** {profile['Match Wins']}"
        )

        if profile["Recent Performance"] is not None:
            message += (
                f"\n📈 **Last Match Performance:** "
                f"{profile['Recent Performance']:.2f}"
            )

        if quote and quote.strip():
            message += (
                f'\n\n💬 **Favorite Quote:** '
                f'*"{quote.strip()}"*'
            )

        await interaction.followup.send(
            message,
            allowed_mentions=discord.AllowedMentions.none()
        )

    # Generate AI-assisted CFB Sports Network power rankings and record API token usage.
    @bot.tree.command(
        name="power",
        description="Show the latest CFB Sports Network power rankings",
        guild=dev_guild
    )
    @admin_only
    async def power(interaction: discord.Interaction):
        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📡 **CFB Sports Network is convening the completely unbiased ranking committee...**"
        )

        usage_id = await asyncio.to_thread(
            log_bot_usage,
            "power",
            interaction.user.id
        )

        def load_player_names(cursor):
            cursor.execute(
                """
                SELECT player_name
                FROM players
                WHERE active = TRUE
                ORDER BY player_name
                """
            )

            return [
                row[0]
                for row in cursor.fetchall()
            ]

        player_names = await asyncio.to_thread(
            database_operation,
            load_player_names
        )

        power_data = await asyncio.to_thread(
            get_power_data,
            player_names
        )

        try:
            await asyncio.to_thread(
                mark_bot_usage_api_call,
                usage_id
            )

            result = await generate_power(power_data)

            await asyncio.to_thread(
                update_bot_usage_tokens,
                usage_id,
                result["input_tokens"],
                result["output_tokens"]
            )

        except Exception as e:
            logger.error(f"POWER ERROR: {e}")

            await interaction.edit_original_response(
                content="CFB Sports Network suffered an internal ranking committee scandal."
            )
            return

        chunks = split_discord_message(
            result["text"]
        )

        await interaction.edit_original_response(
            content=chunks[0]
        )

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    # Generate an AI-assisted preview for the next match using IN and MAYBE players.
    @bot.tree.command(
        name="preview",
        description="Get the CFB Sports Network preview for the next match",
        guild=dev_guild
    )
    @admin_only
    async def preview(interaction: discord.Interaction):
        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        usage_id = await asyncio.to_thread(
            log_bot_usage,
            "preview",
            interaction.user.id
        )

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        def load_preview_context(cursor):
            cursor.execute(
                """
                SELECT
                    m.id,
                    m.match_date,
                    m.location,
                    m.tee_time_1,
                    m.tee_time_2,
                    m.tee_time_3,
                    m.tee_time_4,
                    m.special_rule
                FROM matches m
                WHERE m.active = TRUE
                AND TIMESTAMP(
                    m.match_date,
                    GREATEST(
                        COALESCE(m.tee_time_1, '00:00:00'),
                        COALESCE(m.tee_time_2, '00:00:00'),
                        COALESCE(m.tee_time_3, '00:00:00'),
                        COALESCE(m.tee_time_4, '00:00:00')
                    )
                ) >= NOW()
                ORDER BY m.match_date
                LIMIT 1
                """
            )

            match = cursor.fetchone()

            if match is None:
                return None, [], {}, None

            match_id = match[0]

            cursor.execute(
                """
                SELECT
                    p.player_name,
                    a.status
                FROM availability a
                JOIN players p
                    ON p.id = a.player_id
                WHERE a.match_id = %s
                AND a.status IN ('in', 'maybe')
                AND p.active = TRUE
                ORDER BY
                    CASE a.status
                        WHEN 'in' THEN 1
                        WHEN 'maybe' THEN 2
                    END,
                    p.player_name
                """,
                (match_id,)
            )

            player_availability = cursor.fetchall()
            player_names = [row[0] for row in player_availability]

            player_notes = {}

            if player_names:
                cursor.execute(
                    """
                    SELECT
                        player_name,
                        notes
                    FROM players
                    WHERE active = TRUE
                    AND player_name IN ({})
                    AND notes IS NOT NULL
                    AND TRIM(notes) <> ''
                    """.format(
                        ",".join(["%s"] * len(player_names))
                    ),
                    tuple(player_names)
                )

                player_notes = {
                    player_name: notes
                    for player_name, notes in cursor.fetchall()
                }

            # Load David's Tan City bankroll and any unsettled wagers on this match.
            cursor.execute(
                """
                SELECT
                    gambler_id,
                    starting_balance,
                    current_balance
                FROM gamblers
                WHERE is_david = TRUE
                LIMIT 1
                """
            )

            david = cursor.fetchone()
            david_gambling = None

            if david is not None:
                david_gambler_id, starting_balance, current_balance = david

                cursor.execute(
                    """
                    SELECT
                        p.player_name,
                        mp.odds_american,
                        w.wager_amount
                    FROM wagers w
                    JOIN market_prices mp
                        ON mp.market_price_id = w.market_price_id
                    JOIN players p
                        ON p.id = mp.player_id
                    WHERE w.gambler_id = %s
                    AND mp.match_id = %s
                    AND w.outcome IS NULL
                    ORDER BY
                        w.wagered_at,
                        w.wager_id
                    """,
                    (
                        david_gambler_id,
                        match_id
                    )
                )

                david_wagers = [
                    {
                        "Player": player_name,
                        "Odds": odds_american,
                        "Wager Amount": float(wager_amount)
                    }
                    for player_name, odds_american, wager_amount
                    in cursor.fetchall()
                ]

                # Only expose gambling context to the preview when David actually
                # has action on the upcoming match.
                if david_wagers:
                    david_gambling = {
                        "Starting Bankroll": float(starting_balance),
                        "Current Bankroll": float(current_balance),
                        "Total Wagered On Match": sum(
                            wager["Wager Amount"]
                            for wager in david_wagers
                        ),
                        "Wagers": david_wagers
                    }

            return (
                match,
                player_availability,
                player_notes,
                david_gambling
            )

        (
            match,
            player_availability,
            player_notes,
            david_gambling
        ) = await asyncio.to_thread(
            database_operation,
            load_preview_context
        )

        if match is None:
            await interaction.edit_original_response(
                content="There are no upcoming CFB matches scheduled."
            )
            return

        (
            match_id,
            match_date,
            location,
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4,
            special_rule
        ) = match

        tee_times = [
            tee_time
            for tee_time in (
                tee_time_1,
                tee_time_2,
                tee_time_3,
                tee_time_4
            )
            if tee_time is not None
        ]

        if not player_availability:
            await interaction.edit_original_response(
                content=(
                    "Nobody is currently marked IN or MAYBE "
                    "for the next CFB match."
                )
            )
            return

        await interaction.edit_original_response(
            content=(
                "📡 **CFB Sports Network is examining the field "
                "and manufacturing irresponsible expectations...**"
            )
        )

        try:
            preview_data = await asyncio.to_thread(
                get_preview_data,
                player_availability,
                match_date,
                location,
                tee_times
            )

            preview_data["Player Notes"] = player_notes

            if special_rule:
                preview_data["Weekly Special Rule"] = special_rule

            if david_gambling is not None:
                preview_data["David Gambling"] = david_gambling

            await asyncio.to_thread(
                mark_bot_usage_api_call,
                usage_id
            )

            result = await generate_preview(preview_data)

            await asyncio.to_thread(
                update_bot_usage_tokens,
                usage_id,
                result["input_tokens"],
                result["output_tokens"]
            )

            preview_text = result["text"]

            chunks = split_discord_message(preview_text)

            await interaction.edit_original_response(
                content=chunks[0]
            )

            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

        except Exception as e:
            logger.error(f"PREVIEW ERROR: {e}")

            await interaction.followup.send(
                "CFB Sports Network's pregame desk has suffered "
                "a catastrophic production failure."
            )

    # Save the invoking player's favorite quote after basic validation.
    @bot.tree.command(
        name="quote",
        description="Set your favorite quote",
        guild=dev_guild
    )
    @app_commands.describe(
        quote="Your new favorite quote"
    )
    async def quote(
        interaction: discord.Interaction,
        quote: str
    ):
        await asyncio.to_thread(
            log_bot_usage,
            "quote",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        quote = quote.strip()

        if not quote:
            await interaction.response.send_message(
                "Your quote cannot be empty.",
                ephemeral=True
            )
            return

        if len(quote) > 500:
            await interaction.response.send_message(
                "Your quote must be 500 characters or fewer.",
                ephemeral=True
            )
            return

        def update_quote(cursor):
            cursor.execute(
                """
                UPDATE players
                SET quote = %s
                WHERE discord_user_id = %s
                AND active = TRUE
                """,
                (
                    quote,
                    interaction.user.id
                )
            )

            return cursor.rowcount

        updated = await asyncio.to_thread(
            database_operation,
            update_quote,
            True
        )

        if updated == 0:
            await interaction.response.send_message(
                "I couldn't find an active CFB player linked to your Discord account.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f'💬 **Favorite quote updated:** *"{quote}"*',
            allowed_mentions=discord.AllowedMentions.none()
        )

    # Refresh stored Discord usernames and display names for active linked players.
    @bot.tree.command(
        name="refresh",
        description="Refresh Discord names for CFB players",
        guild=dev_guild
    )
    @admin_only
    async def refresh(interaction: discord.Interaction):
        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        await asyncio.to_thread(
            log_bot_usage,
            "refresh",
            interaction.user.id
        )

        def load_linked_players(cursor):
            cursor.execute(
                """
                SELECT id, discord_user_id
                FROM players
                WHERE discord_user_id IS NOT NULL
                  AND active = TRUE
                """
            )

            return cursor.fetchall()

        players = await asyncio.to_thread(
            database_operation,
            load_linked_players
        )

        updated = 0
        not_found = 0
        name_updates = []

        for player_id, discord_user_id in players:
            try:
                member = await interaction.guild.fetch_member(
                    discord_user_id
                )
            except discord.NotFound:
                not_found += 1
                continue

            name_updates.append(
                (
                    member.name,
                    member.display_name,
                    player_id
                )
            )

            updated += 1

        def update_player_names(cursor):
            cursor.executemany(
                """
                UPDATE players
                SET discord_username = %s,
                    discord_display_name = %s
                WHERE id = %s
                """,
                name_updates
            )

        if name_updates:
            await asyncio.to_thread(
                database_operation,
                update_player_names,
                True
            )

        await interaction.followup.send(
            f"🔄 Player refresh complete.\n"
            f"Updated: **{updated}**\n"
            f"Not found: **{not_found}**",
            ephemeral=True
        )


    # Provide the official CFB rules document link.
    @bot.tree.command(
        name="rules",
        description="Get the official CFB rules",
        guild=dev_guild
    )
    async def rules(interaction: discord.Interaction):
        await asyncio.to_thread(
            log_bot_usage,
            "rules",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📜 **Official CFB Rules:**\n"
            "https://docs.google.com/document/d/"
            "1TVKjPrOkk5n_VvjfKff3ZEqdVmj_f1IS7qpm5diBFf4/"
            "edit?usp=sharing"
        )


    # Summarize availability and remaining capacity for the next active match.
    @bot.tree.command(
        name="who",
        description="Show who's in, out, maybe, or unknown for the next CFB match",
        guild=dev_guild
    )
    async def who(interaction: discord.Interaction):
        await asyncio.to_thread(
            log_bot_usage,
            "who",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        def load_availability(cursor):
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
                """
            )

            match = cursor.fetchone()

            if match is None:
                return None, []

            cursor.execute(
                """
                SELECT
                    p.player_name,
                    COALESCE(a.status, 'unknown') AS status
                FROM players p
                LEFT JOIN availability a
                    ON a.player_id = p.id
                   AND a.match_id = %s
                WHERE p.active = TRUE
                ORDER BY p.player_name
                """,
                (match[0],)
            )

            return match, cursor.fetchall()

        match, rows = await asyncio.to_thread(
            database_operation,
            load_availability
        )

        if match is None:
            await interaction.response.send_message(
                "There are no upcoming CFB matches scheduled."
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

        in_count = sum(
            status == "in"
            for _, status in rows
        )

        spots_available = capacity - in_count

        groups = {
            "in": [],
            "out": [],
            "maybe": [],
            "unknown": []
        }

        for player_name, status in rows:
            groups[status].append(player_name)

        # Local display helper for rendering empty player groups consistently.
        def format_names(names):
            return ", ".join(names) if names else "Nobody"

        message = (
            f"🏌️ **CFB Availability — {match_date:%A, %B %d}**\n"
            f"⛳ **{in_count} IN — {spots_available} spots available**\n\n"
            f"✅ **IN:** {format_names(groups['in'])}\n"
            f"❌ **OUT:** {format_names(groups['out'])}\n"
            f"🤷 **MAYBE:** {format_names(groups['maybe'])}\n"
            f"❓ **UNKNOWN:** {format_names(groups['unknown'])}"
        )

        await interaction.response.send_message(message)


    # Generate an AI-assisted recap of the latest match and record API token usage.
    @bot.tree.command(
        name="wrapup",
        description="Get the latest CFB Sports Network match recap",
        guild=dev_guild
    )
    @admin_only
    async def wrapup(interaction: discord.Interaction):
        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📡 **CFB Sports Network is reviewing the tape "
            "and preparing irresponsible conclusions...**"
        )

        usage_id = await asyncio.to_thread(
            log_bot_usage,
            "wrapup",
            interaction.user.id
        )

        try:
            match_data = await asyncio.to_thread(
                get_latest_match_with_history
            )

            def load_player_notes(cursor):
                cursor.execute(
                    """
                    SELECT
                        player_name,
                        notes
                    FROM players
                    WHERE active = TRUE
                    AND notes IS NOT NULL
                    AND TRIM(notes) <> ''
                    """
                )

                return {
                    player_name: notes
                    for player_name, notes in cursor.fetchall()
                }

            player_notes = await asyncio.to_thread(
                database_operation,
                load_player_notes
            )

            match_data["Player Notes"] = player_notes            

            await asyncio.to_thread(
                mark_bot_usage_api_call,
                usage_id
            )

            result = await generate_wrapup(match_data)

            recap = result["text"]

            await asyncio.to_thread(
                update_bot_usage_tokens,
                usage_id,
                result["input_tokens"],
                result["output_tokens"]
            )

            chunks = split_discord_message(recap)

            # Replace the "reviewing the tape" message
            # with the first chunk
            await interaction.edit_original_response(
                content=chunks[0]
            )

            # Send any remaining chunks as follow-up messages
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

        except Exception as e:
            logger.error(f"WRAPUP ERROR: {e}")

            await interaction.followup.send(
                "CFB Sports Network has suffered "
                "a catastrophic production failure."
            )