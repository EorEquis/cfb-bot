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
import os

from dailystat import generate_dailystat
from datetime import datetime
from db._db import execute_query
from infrastructure.db_sync import sync_db
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
from match._matches import get_next_match
from match.preview import generate_preview
from power import generate_power
from tancity import generate_tan_city
from tan_city_bot import send_tan_city_episode
from weather import (
    format_time,
    get_forecast,
    weather_emoji
)
from match.wrapup import generate_wrapup


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
    mysql_password,
    tts_output_dir
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


    # Find one ridiculous but defensible observation in complete CFB match history.
    @bot.tree.command(
        name="dailystat",
        description="Get today's unnecessary CFB statistical analysis",
        guild=dev_guild
    )
    async def dailystat(interaction: discord.Interaction):
        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        usage_id = await asyncio.to_thread(
            log_bot_usage,
            "dailystat",
            interaction.user.id
        )

        def load_history(cursor):
            cursor.execute(
                """
                SELECT
                    match_id,
                    match_date,
                    location,
                    notes,
                    special_rule,
                    group_id,
                    players_in_group,
                    total_points,
                    ending_hole,
                    player_id,
                    player_name,
                    player_points,
                    group_winner,
                    match_winner,
                    pre_match_index,
                    match_performance,
                    net_handicap_credits
                FROM vw_completed_match_results
                ORDER BY
                    match_date,
                    match_id,
                    group_id,
                    player_name
                """
            )

            columns = [
                column[0]
                for column in cursor.description
            ]

            return [
                dict(zip(columns, row))
                for row in cursor.fetchall()
            ]

        history_data = await asyncio.to_thread(
            database_operation,
            load_history
        )

        if not history_data:
            await interaction.edit_original_response(
                content="The Ministry of Statistics has investigated and found no statistics."
            )
            return

        try:
            result = await generate_dailystat(history_data)

            await asyncio.to_thread(
                mark_bot_usage_api_call,
                usage_id
            )

            await asyncio.to_thread(
                update_bot_usage_tokens,
                usage_id,
                result["input_tokens"],
                result["output_tokens"]
            )

            messages = split_discord_message(result["text"])

            await interaction.delete_original_response()

            for message in messages:
                await interaction.channel.send(message)

        except Exception:
            logger.exception("Failed to generate daily CFB statistic.")

            await interaction.edit_original_response(
                content=(
                    "The CFB Department of Unnecessary Analytics has suffered "
                    "an extremely necessary systems failure."
                )
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
            f"📖 CFB Bot v{bot_version} Commands",
            "**Bold = admin-only.**" if is_admin else "",
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

            command_line = f"`{usage}` — {command.description}"

            command_is_admin_only = getattr(
                command.callback,
                "admin_only",
                False
            )

            if command_is_admin_only:
                command_line = f"**{command_line}**"

            lines.append(command_line)

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
                    p.player_name,
                    p.discord_display_name,
                    s.quote,
                    s.normalized_cfb_index,
                    s.matches_played,
                    s.total_points,
                    s.group_wins,
                    s.match_wins,
                    (
                        SELECT r.match_performance
                        FROM vw_completed_match_results r
                        WHERE r.player_id = p.id
                        ORDER BY r.match_date DESC, r.match_id DESC
                        LIMIT 1
                    ) AS recent_performance
                FROM players p
                JOIN vw_player_career_stats s
                    ON s.player_id = p.id
                WHERE p.active = TRUE
                AND (
                        p.player_name = %s
                    OR p.discord_display_name = %s
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

        (
            player_name,
            display_name,
            quote,
            current_index,
            matches_played,
            total_points,
            group_wins,
            match_wins,
            recent_performance
        ) = row

        message = (
            f"🏌️ **CFB PLAYER PROFILE**\n\n"
            f"**{player_name}**"
        )

        if display_name:
            message += f"\n🎮 Discord: **{display_name}**"

        message += (
            f"\n\n"
            f"📊 **CFB Index:** {current_index:.2f}\n"
            f"⛳ **Matches Played:** {matches_played}\n"
            f"🎯 **Total Points:** {total_points:g}\n"
            f"🏆 **Group Wins:** {group_wins}\n"
            f"👑 **Match Wins:** {match_wins}"
        )

        if recent_performance is not None:
            message += (
                f"\n📈 **Last Match Performance:** "
                f"{recent_performance:.2f}"
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

        def load_power_data(cursor):
            cursor.execute(
                """
                SELECT
                    s.player_id,
                    s.player_name,
                    s.normalized_cfb_index,
                    s.matches_played,
                    s.total_points,
                    s.group_wins,
                    s.match_wins
                FROM vw_player_career_stats s
                WHERE s.active = TRUE
                ORDER BY s.player_name
                """
            )

            player_rows = cursor.fetchall()

            players = []

            for (
                player_id,
                player_name,
                normalized_cfb_index,
                matches_played,
                total_points,
                group_wins,
                match_wins
            ) in player_rows:

                cursor.execute(
                    """
                    SELECT match_performance
                    FROM vw_completed_match_results
                    WHERE player_id = %s
                    ORDER BY match_date DESC, match_id DESC
                    LIMIT 3
                    """,
                    (player_id,)
                )

                recent_performances = [
                    float(row[0])
                    for row in cursor.fetchall()
                ]

                players.append({
                    "Player": player_name,
                    "Normalized CFB Index": (
                        float(normalized_cfb_index)
                        if normalized_cfb_index is not None
                        else None
                    ),
                    "Matches Played": matches_played,
                    "Total Points": float(total_points),
                    "Group Wins": group_wins,
                    "Match Wins": match_wins,
                    "Recent Performances": recent_performances
                })

            cursor.execute(
                """
                SELECT player_name
                FROM vw_completed_match_results
                WHERE match_winner = 1
                ORDER BY match_date DESC, match_id DESC
                LIMIT 1
                """
            )

            holder_row = cursor.fetchone()

            current_holder = (
                holder_row[0]
                if holder_row is not None
                else None
            )

            return {
                "Players": players,
                "Current CFB Holder": current_holder
            }

        power_data = await asyncio.to_thread(
            database_operation,
            load_power_data
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

        await interaction.delete_original_response()

        for chunk in chunks:
            await interaction.channel.send(chunk)

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

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        usage_id = await asyncio.to_thread(
            log_bot_usage,
            "preview",
            interaction.user.id
        )

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
                return None, [], {}, None, {}, None

            match_id = match[0]

            cursor.execute(
                """
                SELECT
                    p.player_name,
                    CASE
                        WHEN a.status = 'in' THEN 'in'
                        WHEN a.status = 'maybe' THEN 'maybe'
                        ELSE 'unknown'
                    END AS status
                FROM players p
                LEFT JOIN availability a
                    ON a.player_id = p.id
                    AND a.match_id = %s
                WHERE p.active = TRUE
                AND (
                    a.status IN ('in', 'maybe')
                    OR a.status IS NULL
                )
                ORDER BY
                    CASE
                        WHEN a.status = 'in' THEN 1
                        WHEN a.status = 'maybe' THEN 2
                        ELSE 3
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

            # Load David's Tan City bankroll.
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

                # Load the latest sportsbook market snapshot.
                cursor.execute(
                    """
                    SELECT
                        p.player_name,
                        mp.odds_american
                    FROM market_prices mp
                    JOIN players p
                        ON mp.player_id = p.id
                    WHERE mp.match_id = %s
                    AND mp.effective_at = (
                        SELECT MAX(effective_at)
                        FROM market_prices
                        WHERE match_id = %s
                    )
                    ORDER BY p.player_name
                    """,
                    (
                        match_id,
                        match_id
                    )
                )

                market = [
                    {
                        "Player": player_name,
                        "Current Odds": odds_american,
                        "David Wagers": []
                    }
                    for player_name, odds_american
                    in cursor.fetchall()
                ]

                market_by_player = {
                    entry["Player"]: entry
                    for entry in market
                }

                # Attach David's unsettled wagers to the player he wagered on.
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

                david_wagers = []

                for player_name, odds_american, wager_amount in cursor.fetchall():
                    wager = {
                        "Odds": odds_american,
                        "Wager Amount": float(wager_amount)
                    }

                    david_wagers.append(wager)

                    if player_name in market_by_player:
                        market_by_player[player_name]["David Wagers"].append(
                            wager
                        )

                if market:
                    david_gambling = {
                        "Starting Bankroll": float(starting_balance),
                        "Current Bankroll": float(current_balance),
                        "Total Wagered On Match": sum(
                            wager["Wager Amount"]
                            for wager in david_wagers
                        ),
                        "Sportsbook Market": market
                    }

            # Load completed-match history for players in the upcoming field.
            player_history = {}

            if player_names:
                cursor.execute(
                    """
                    SELECT
                        player_name,
                        match_id,
                        match_date,
                        player_points,
                        match_performance,
                        group_winner,
                        match_winner
                    FROM vw_completed_match_results
                    WHERE player_name IN ({})
                    ORDER BY match_date, match_id
                    """.format(
                        ",".join(["%s"] * len(player_names))
                    ),
                    tuple(player_names)
                )

                for (
                    player_name,
                    history_match_id,
                    history_match_date,
                    player_points,
                    match_performance,
                    group_winner,
                    match_winner
                ) in cursor.fetchall():

                    player_history.setdefault(
                        player_name,
                        []
                    ).append({
                        "Match ID": history_match_id,
                        "Match Date": str(history_match_date),
                        "Points": player_points,
                        "Match Performance": float(match_performance),
                        "Group Winner": bool(group_winner),
                        "Match Winner": bool(match_winner)
                    })

            cursor.execute(
                """
                SELECT player_name
                FROM vw_completed_match_results
                WHERE match_winner = 1
                ORDER BY match_date DESC, match_id DESC
                LIMIT 1
                """
            )

            holder_row = cursor.fetchone()

            current_holder = (
                holder_row[0]
                if holder_row is not None
                else None
            )
            
            return (
                match,
                player_availability,
                player_notes,
                david_gambling,
                player_history,
                current_holder
            )

        (
            match,
            player_availability,
            player_notes,
            david_gambling,
            player_history,
            current_holder
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
            formatted_tee_times = []

            for tee_time in tee_times:
                total_seconds = int(tee_time.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60

                period = "AM" if hours < 12 else "PM"
                display_hour = hours % 12

                if display_hour == 0:
                    display_hour = 12

                formatted_tee_times.append(
                    f"{display_hour}:{minutes:02d} {period}"
                )

            preview_players = []

            for name, status in player_availability:
                history = player_history.get(name, [])

                preview_players.append({
                    "Player": name,
                    "Availability": status.upper(),
                    "Matches Played": len(history),
                    "History": history
                })

            preview_data = {
                "Match Date": str(match_date),
                "Days Until Match": (
                    match_date - datetime.now().date()
                ).days,
                "Location": location,
                "Tee Times": formatted_tee_times,
                "Number of Tee Times": len(formatted_tee_times),
                "Maximum Groups": len(formatted_tee_times),
                "Maximum Players": len(formatted_tee_times) * 4,
                "Players IN": sum(
                    status == "in"
                    for _, status in player_availability
                ),
                "Players MAYBE": sum(
                    status == "maybe"
                    for _, status in player_availability
                ),
                "Players UNKNOWN": sum(
                    status == "unknown"
                    for _, status in player_availability
                ),
                "Field Status": (
                    "Players marked IN are the current field. "
                    "Players marked MAYBE are possible additions. "
                    "Players marked UNKNOWN have not responded."
                ),
                "Players": preview_players,
                "Current CFB Holder": current_holder
            }

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

            await interaction.delete_original_response()

            for chunk in chunks:
                await interaction.channel.send(chunk)

        except Exception as e:
            logger.error(f"PREVIEW ERROR: {e}")

            await interaction.followup.send(
                "CFB Sports Network's pregame desk has suffered "
                "a catastrophic production failure."
            )
            

    # Publish a staged preview from the database with its generated audio file.
    @bot.tree.command(
        name="preview-dbtest",
        description="Test publishing a staged CFB Sports Network preview",
        guild=dev_guild
    )
    @admin_only
    async def preview_dbtest(interaction: discord.Interaction):
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

        await interaction.response.defer()

        await asyncio.to_thread(
            log_bot_usage,
            "preview-dbtest",
            interaction.user.id
        )

        match = await asyncio.to_thread(get_next_match)

        if match is None:
            await interaction.edit_original_response(
                content="There are no upcoming CFB matches scheduled."
            )
            return

        match_id = match["id"]

        response_rows = await asyncio.to_thread(
            execute_query,
            """
            SELECT
                r.response_id,
                r.response_text,
                m.match_date
            FROM responses r
            JOIN matches m
                ON m.id = r.match_id
            WHERE r.match_id = %s
            AND r.command = 'preview'
            ORDER BY r.response_id DESC
            LIMIT 1
            """,
            (match_id,)
        )

        response = response_rows[0] if response_rows else None

        if response is None:
            await interaction.edit_original_response(
                content=(
                    "No staged preview was found for the next CFB match."
                )
            )
            return

        response_id = response["response_id"]
        response_text = response["response_text"]
        match_date = response["match_date"]

        audio_filename = (
            f"preview_{match_date:%Y%m%d}_{response_id}.mp3"
        )

        audio_path = os.path.join(
            tts_output_dir,
            audio_filename
        )

        if not os.path.isfile(audio_path):
            await interaction.edit_original_response(
                content=(
                    f"Staged preview response {response_id} was found, "
                    "but {audio_filename} file is missing."
                )
            )
            return

        chunks = split_discord_message(response_text)

        await interaction.delete_original_response()

        print(
            f"preview-dbtest: response_id={response_id}, "
            f"audio_path={audio_path}, "
            f"exists={os.path.isfile(audio_path)}, "
            f"chunks={len(chunks)}"
        )

        for index, chunk in enumerate(chunks):
            print(
                f"preview-dbtest: sending chunk {index + 1}/{len(chunks)}, "
                f"attach={index == len(chunks) - 1}"
            )
            if index == len(chunks) - 1:
                await interaction.channel.send(
                    chunk,
                    file=discord.File(audio_path)
                )
            else:
                await interaction.channel.send(chunk)
                
                            
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


    # Show the current Tan City market and wagering action for the upcoming match.
    @bot.tree.command(
        name="sportsbook",
        description="Show the current Tan City market and wagering action",
        guild=dev_guild
    )
    async def sportsbook(interaction: discord.Interaction):
        await asyncio.to_thread(
            log_bot_usage,
            "sportsbook",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        def load_sportsbook(cursor):
            cursor.execute(
                """
                SELECT id
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

            if not match:
                return None

            match_id = match[0]

            cursor.execute(
                """
                SELECT
                    p.player_name,
                    mp.odds_american,
                    mp.effective_at
                FROM market_prices mp
                JOIN players p
                    ON mp.player_id = p.id
                WHERE mp.match_id = %s
                AND mp.effective_at = (
                    SELECT MAX(effective_at)
                    FROM market_prices
                    WHERE match_id = %s
                )
                ORDER BY p.player_name
                """,
                (
                    match_id,
                    match_id
                )
            )
            
            current_market = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    p.player_name,
                    SUM(w.wager_amount) AS total_wagered,
                    mp.odds_american
                FROM wagers w
                JOIN market_prices mp
                    ON w.market_price_id = mp.market_price_id
                JOIN players p
                    ON mp.player_id = p.id
                WHERE mp.match_id = %s
                GROUP BY
                    p.player_name,
                    mp.odds_american
                ORDER BY
                    p.player_name,
                    total_wagered DESC,
                    CAST(mp.odds_american AS INTEGER) DESC
                """,
                (match_id,)
            )

            wagers = cursor.fetchall()

            cursor.execute(
                """
                SELECT MAX(w.wagered_at)
                FROM wagers w
                JOIN market_prices mp
                    ON w.market_price_id = mp.market_price_id
                WHERE mp.match_id = %s
                """,
                (match_id,)
            )

            latest_wager = cursor.fetchone()[0]

            return current_market, wagers, latest_wager

        result = await asyncio.to_thread(
            database_operation,
            load_sportsbook
        )

        if result is None:
            await interaction.edit_original_response(
                content=(
                    "🎰 **TAN CITY SPORTSBOOK**\n\n"
                    "No upcoming CFB match found."
                )
            )
            return

        current_market, wagers, latest_wager = result

        def format_odds(odds):
            odds = int(odds)

            if odds > 0:
                return f"+{odds}"

            return str(odds)

        if latest_wager:
            sportsbook_time = latest_wager.strftime(
                "%A, %B %d, %Y %I:%M %p"
            )
        else:
            sportsbook_time = datetime.now().strftime(
                "%A, %B %d, %Y %I:%M %p"
    )

        lines = [
            f"🎰 **TAN CITY SPORTS BOOK @ {sportsbook_time}**",
            "",
            "**CURRENT MARKET**"
        ]

        if current_market:
            for player_name, odds_american, effective_at in current_market:
                lines.append(
                    f"**{player_name}** — {format_odds(odds_american)}"
                )
        else:
            lines.append("No current market.")

        lines.extend([
            "",
            "**WAGERED**"
        ])

        if wagers:
            current_player = None

            for player_name, total_wagered, odds_american in wagers:
                if player_name != current_player:
                    if current_player is not None:
                        lines.append("")

                    lines.append(f"**{player_name}**")
                    current_player = player_name

                lines.append(
                    f"• ${total_wagered:,.2f} @ {format_odds(odds_american)}"
                )
        else:
            lines.append("No wagers yet.")

        message = "\n".join(lines)

        chunks = split_discord_message(message)

        await interaction.followup.send(chunks[0])

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)    


    # Manually synchronize authoritative spreadsheet data into the database.
    @bot.tree.command(
        name="syncdb",
        description="Synchronize CFB spreadsheet data to the database",
        guild=dev_guild
    )
    @admin_only
    async def syncdb(
        interaction: discord.Interaction
    ):
        await asyncio.to_thread(
            log_bot_usage,
            "syncdb",
            interaction.user.id
        )

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            await asyncio.to_thread(sync_db)

            await interaction.edit_original_response(
                content="CFB database sync complete."
            )

        except Exception as e:
            logger.exception(
                "Manual database sync failed"
            )

            await interaction.edit_original_response(
                content=f"CFB database sync failed: {e}"
            )


    # Generate a Tan City After Dark pre-match or post-match episode.
    @bot.tree.command(
        name="tancity",
        description="Generate a Tan City After Dark episode",
        guild=dev_guild
    )
    @admin_only
    @app_commands.describe(
        mode="Episode type"
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="pre", value="pre"),
            app_commands.Choice(name="post", value="post")
        ]
    )
    async def tancity(
        interaction: discord.Interaction,
        mode: app_commands.Choice[str]
    ):
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

        if (
            mode.value == "pre"
            and datetime.now().weekday() < 3
        ):
            await interaction.response.send_message(
                "The betting window does not open until Thursday.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🎙️ **Let's check in with Tan City After Dark...**"
        )

        usage_id = await asyncio.to_thread(
            log_bot_usage,
            "tancity",
            interaction.user.id
        )

        try:
            await asyncio.to_thread(
                mark_bot_usage_api_call,
                usage_id
            )

            result = await generate_tan_city(mode.value)

            await asyncio.to_thread(
                update_bot_usage_tokens,
                usage_id,
                result["input_tokens"],
                result["output_tokens"]
            )

        except Exception as e:
            logger.error(f"TAN CITY ERROR: {e}")

            await interaction.edit_original_response(
                content="Tan City After Dark has suffered a catastrophic production failure."
            )
            return

        chunks = split_discord_message(
            result["text"]
        )

        await interaction.edit_original_response(
            content="🎙️ **Tan City After Dark is going live...**"
        )

        await send_tan_city_episode(
            interaction.channel_id,
            chunks
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
            def load_wrapup_data(cursor):
                cursor.execute(
                    """
                    SELECT
                        match_id,
                        match_date
                    FROM vw_completed_match_results
                    ORDER BY match_date DESC, match_id DESC
                    LIMIT 1
                    """
                )

                latest_match = cursor.fetchone()

                if latest_match is None:
                    raise RuntimeError(
                        "No completed CFB matches found."
                    )

                match_id, match_date = latest_match

                cursor.execute(
                    """
                    SELECT
                        group_id,
                        players_in_group,
                        total_points,
                        ending_hole,
                        player_id,
                        player_name,
                        player_points,
                        group_winner,
                        match_winner,
                        pre_match_index,
                        match_performance
                    FROM vw_completed_match_results
                    WHERE match_id = %s
                    ORDER BY group_id, player_name
                    """,
                    (match_id,)
                )

                match_rows = cursor.fetchall()

                groups_by_id = {}
                current_player_ids = []

                for (
                    group_id,
                    players_in_group,
                    total_points,
                    ending_hole,
                    player_id,
                    player_name,
                    player_points,
                    group_winner,
                    match_winner,
                    pre_match_index,
                    match_performance
                ) in match_rows:

                    current_player_ids.append(player_id)

                    if group_id not in groups_by_id:
                        groups_by_id[group_id] = {
                            "Group": int(group_id),
                            "Players in Group": int(players_in_group),
                            "Total Points": int(total_points),
                            "Ending Hole": int(ending_hole),
                            "Players": []
                        }

                    groups_by_id[group_id]["Players"].append({
                        "Player": player_name,
                        "Player ID": player_id,
                        "Points": int(player_points),
                        "Pre-Match Index": float(pre_match_index),
                        "Match Performance": float(match_performance),
                        "Group Winner": bool(group_winner),
                        "Match Winner": bool(match_winner),
                        "Previous Performance": None,
                        "Performance Change": None,
                        "Previous Matches": 0,
                        "Previous Group Wins": 0,
                        "Previous Match Wins": 0
                    })

                match_data = {
                    "Match ID": int(match_id),
                    "Match Date": str(match_date),
                    "Groups": list(groups_by_id.values())
                }

                if current_player_ids:
                    cursor.execute(
                        """
                        SELECT
                            player_id,
                            match_date,
                            match_id,
                            match_performance,
                            group_winner,
                            match_winner
                        FROM vw_completed_match_results
                        WHERE player_id IN ({})
                        AND (
                            match_date < %s
                            OR (
                                match_date = %s
                                AND match_id < %s
                            )
                        )
                        ORDER BY
                            player_id,
                            match_date,
                            match_id
                        """.format(
                            ",".join(["%s"] * len(current_player_ids))
                        ),
                        tuple(current_player_ids)
                        + (
                            match_date,
                            match_date,
                            match_id
                        )
                    )

                    history_by_player = {}

                    for (
                        player_id,
                        history_match_date,
                        history_match_id,
                        match_performance,
                        group_winner,
                        match_winner
                    ) in cursor.fetchall():

                        history_by_player.setdefault(
                            player_id,
                            []
                        ).append({
                            "Match Performance": float(match_performance),
                            "Group Winner": bool(group_winner),
                            "Match Winner": bool(match_winner)
                        })

                    for group in match_data["Groups"]:
                        for player in group["Players"]:
                            history = history_by_player.get(
                                player["Player ID"],
                                []
                            )

                            player["Previous Matches"] = len(history)
                            player["Previous Group Wins"] = sum(
                                item["Group Winner"]
                                for item in history
                            )
                            player["Previous Match Wins"] = sum(
                                item["Match Winner"]
                                for item in history
                            )

                            if history:
                                previous_performance = history[-1][
                                    "Match Performance"
                                ]

                                player[
                                    "Previous Performance"
                                ] = previous_performance

                                player[
                                    "Performance Change"
                                ] = round(
                                    player["Match Performance"]
                                    - previous_performance,
                                    2
                                )

                all_players = [
                    player
                    for group in match_data["Groups"]
                    for player in group["Players"]
                ]

                players_with_change = [
                    player
                    for player in all_players
                    if player["Performance Change"] is not None
                ]

                highlights = {}

                if players_with_change:
                    highlights["Biggest Improvement"] = max(
                        players_with_change,
                        key=lambda p: p["Performance Change"]
                    )

                    highlights["Biggest Decline"] = min(
                        players_with_change,
                        key=lambda p: p["Performance Change"]
                    )

                highlights["Best Performance"] = max(
                    all_players,
                    key=lambda p: p["Match Performance"]
                )

                highlights["Worst Performance"] = min(
                    all_players,
                    key=lambda p: p["Match Performance"]
                )

                match_data["Highlights"] = highlights

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

                player_notes = {
                    player_name: notes
                    for player_name, notes in cursor.fetchall()
                }

                cursor.execute(
                    """
                    SELECT
                        gambler_id,
                        current_balance
                    FROM gamblers
                    WHERE is_david = TRUE
                    LIMIT 1
                    """
                )

                david = cursor.fetchone()
                david_gambling = None

                if david is not None:
                    david_gambler_id, current_balance = david

                    cursor.execute(
                        """
                        SELECT
                            p.player_name,
                            mp.odds_american,
                            w.wager_amount,
                            w.outcome,
                            w.payout
                        FROM wagers w
                        JOIN market_prices mp
                            ON mp.market_price_id = w.market_price_id
                        JOIN players p
                            ON p.id = mp.player_id
                        WHERE w.gambler_id = %s
                        AND mp.match_id = %s
                        AND w.outcome IS NOT NULL
                        ORDER BY
                            w.wagered_at,
                            w.wager_id
                        """,
                        (
                            david_gambler_id,
                            match_id
                        )
                    )

                    wager_rows = cursor.fetchall()

                    if wager_rows:
                        david_wagers = [
                            {
                                "Player": player_name,
                                "Odds": odds_american,
                                "Wager Amount": float(wager_amount),
                                "Outcome": outcome,
                                "Payout": float(payout or 0)
                            }
                            for (
                                player_name,
                                odds_american,
                                wager_amount,
                                outcome,
                                payout
                            ) in wager_rows
                        ]

                        david_gambling = {
                            "Current Bankroll": float(current_balance),
                            "Total Wagered": round(
                                sum(
                                    wager["Wager Amount"]
                                    for wager in david_wagers
                                ),
                                2
                            ),
                            "Total Payout": round(
                                sum(
                                    wager["Payout"]
                                    for wager in david_wagers
                                ),
                                2
                            ),
                            "Wagers": david_wagers
                        }

                return (
                    match_data,
                    player_notes,
                    david_gambling
                )

            (
                match_data,
                player_notes,
                david_gambling
            ) = await asyncio.to_thread(
                database_operation,
                load_wrapup_data
            )

            match_data["Player Notes"] = player_notes

            if david_gambling is not None:
                match_data["David Gambling"] = david_gambling

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

            await interaction.delete_original_response()

            for chunk in chunks:
                await interaction.channel.send(chunk)

        except Exception as e:
            logger.error(f"WRAPUP ERROR: {e}")

            await interaction.followup.send(
                "CFB Sports Network's postgame desk has suffered "
                "a catastrophic production failure."
            )