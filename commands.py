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
import os


from datetime import datetime
from db._db import (
    execute_query,
    execute_upsert,
    get_recent_responses,
    save_response
)
from discord import app_commands
from infrastructure.db_sync import sync_db
from match._matches import (
    get_completed_match_history,
    get_next_match,
    get_upcoming_matches,
    get_wrapup_data
)
from match.preview import generate_preview
from match.wrapup import generate_wrapup
from player._players import (
    get_current_cfb_holder,
    get_player_availability,
    get_player_profile,
    get_player_recent_performances,
)
from player.dailystat import generate_dailystat
from player.power import generate_power
from tan_city.tancity import generate_tan_city
from tan_city.tan_city_bot import send_tan_city_episode
from utility.helpers import (
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
from utility.weather import (
    format_time,
    get_forecast,
    weather_emoji
)

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

        existing_matches = await asyncio.to_thread(
            execute_query,
            """
            SELECT id
            FROM matches
            WHERE match_date = %s
            AND active = TRUE
            LIMIT 1
            """,
            (match_date,)
        )

        if existing_matches:
            match_added = False
        else:
            await asyncio.to_thread(
                execute_upsert,
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

            match_added = True

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


    # Provide the official CFB Drive folder link.
    @bot.tree.command(
        name="cfb",
        description="See the official CFB documents",
        guild=dev_guild
    )
    async def cfb(interaction: discord.Interaction):
        await asyncio.to_thread(
            log_bot_usage,
            "cfb",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📜 **Official CFB Drive Folder:**\n"
            "https://drive.google.com/drive/folders/1nSsaS5M_nz_e8SlGS9Tu7fl6dWwxHmEy?usp=sharing"
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

        history_data = await asyncio.to_thread(
            get_completed_match_history
        )

        if not history_data:
            await interaction.edit_original_response(
                content="The Ministry of Statistics has investigated and found no statistics."
            )
            return

        try:
            previous_responses = await asyncio.to_thread(
                get_recent_responses,
                "dailystat",
                2
            )

            result = await generate_dailystat(
                history_data,
                previous_responses
            )

            await asyncio.to_thread(
                save_response,
                "dailystat",
                result["text"]
            )

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

        matches = await asyncio.to_thread(
            execute_query,
            """
            SELECT location
            FROM matches
            WHERE match_date = %s
              AND active = TRUE
            LIMIT 1
            """,
            (match_date,)
        )

        if matches:
            location = matches[0]["location"]

            await asyncio.to_thread(
                execute_upsert,
                """
                UPDATE matches
                SET active = FALSE
                WHERE match_date = %s
                  AND active = TRUE
                """,
                (match_date,)
            )
        else:
            location = None

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

        updated = await asyncio.to_thread(
            execute_upsert,
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

        if show_all:
            matches = await asyncio.to_thread(
                get_upcoming_matches
            )

        else:
            next_match = await asyncio.to_thread(
                get_next_match
            )

            matches = (
                [next_match]
                if next_match is not None
                else []
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

        for match_data in matches:
            match_date = match_data["match_date"]
            location = match_data["location"]
            notes = match_data["notes"]
            special_rule = match_data["special_rule"]

            tee_times = [
                match_data["tee_time_1"],
                match_data["tee_time_2"],
                match_data["tee_time_3"],
                match_data["tee_time_4"]
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
            match_date = matches[0]["match_date"]
            tee_time_1 = matches[0]["tee_time_1"]

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

        player_rows = await asyncio.to_thread(
            get_player_profile
        )

        row = next(
            (
                row for row in player_rows
                if row["player_name"] == player
                or row["discord_display_name"] == player
            ),
            None
        )

        if row is None:
            await interaction.followup.send(
                f'No active CFB player found for "{player}".',
                ephemeral=True
            )
            return

        player_name = row["player_name"]
        display_name = row["discord_display_name"]
        quote = row["quote"]
        current_index = row["normalized_cfb_index"]
        matches_played = row["matches_played"]
        total_points = row["total_points"]
        group_wins = row["group_wins"]
        match_wins = row["match_wins"]
        current_cfb = row["current_cfb"]
        recent_performance = row["recent_performance"]

        message = (
            f"🏌️ **CFB PLAYER PROFILE**\n\n"
            f"**{player_name}**"
        )

        if display_name:
            message += f"\n🎮 Discord: **{display_name}**"

        message += "\n\n"

        if current_cfb:
            message += "👑 **Current CFB Holder**\n"

        message += (
            f"📊 **CFB Index:** {current_index:.2f}\n"
            f"⛳ **Matches Played:** {matches_played}\n"
            f"🎯 **Total Points:** {total_points:g}\n"
            f"🏆 **Group Wins:** {group_wins}\n"
            f"🥇 **Match Wins:** {match_wins}"
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

        player_rows = await asyncio.to_thread(
            get_player_profile
        )

        players = []

        for row in player_rows:
            recent_rows = await asyncio.to_thread(
                get_player_recent_performances,
                row["player_id"]
            )

            recent_performances = [
                float(recent_row["match_performance"])
                for recent_row in recent_rows
            ]

            players.append({
                "Player": row["player_name"],
                "Normalized CFB Index": (
                    float(row["normalized_cfb_index"])
                    if row["normalized_cfb_index"] is not None
                    else None
                ),
                "Matches Played": row["matches_played"],
                "Total Points": float(row["total_points"]),
                "Group Wins": row["group_wins"],
                "Match Wins": row["match_wins"],
                "Recent Performances": recent_performances
            })

        current_holder = await asyncio.to_thread(
            get_current_cfb_holder
        )

        power_data = {
            "Players": players,
            "Current CFB Holder": current_holder
        }

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

        match = await asyncio.to_thread(get_next_match)

        if match is None:
            await interaction.edit_original_response(
                content="There are no upcoming CFB matches scheduled."
            )
            return

        match_id = match["id"]

        availability = await asyncio.to_thread(
            get_player_availability,
            match_id
        )

        player_availability = [
            row
            for row in availability["players"]
            if row["status"] != "out"
        ]

        player_availability.sort(
            key=lambda row: (
                {
                    "in": 1,
                    "maybe": 2,
                    "unknown": 3
                }[row["status"]],
                row["player_name"]
            )
        )

        player_names = [
            row["player_name"]
            for row in player_availability
        ]

        player_notes = {}

        if player_names:
            player_note_rows = await asyncio.to_thread(
                execute_query,
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
                row["player_name"]: row["notes"]
                for row in player_note_rows
            }

        # Load David's Tan City bankroll.
        david_rows = await asyncio.to_thread(
            execute_query,
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

        david = david_rows[0] if david_rows else None
        david_gambling = None

        if david is not None:
            david_gambler_id = david["gambler_id"]
            starting_balance = david["starting_balance"]
            current_balance = david["current_balance"]

            # Load the latest sportsbook market snapshot.
            market_rows = await asyncio.to_thread(
                execute_query,
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
                    "Player": row["player_name"],
                    "Current Odds": row["odds_american"],
                    "David Wagers": []
                }
                for row in market_rows
            ]

            market_by_player = {
                entry["Player"]: entry
                for entry in market
            }

            # Attach David's unsettled wagers to the player he wagered on.
            david_wager_rows = await asyncio.to_thread(
                execute_query,
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

            for row in david_wager_rows:
                wager = {
                    "Odds": row["odds_american"],
                    "Wager Amount": float(row["wager_amount"])
                }

                david_wagers.append(wager)

                if row["player_name"] in market_by_player:
                    market_by_player[
                        row["player_name"]
                    ]["David Wagers"].append(wager)

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

        # Load completed-match history and select what preview needs.
        history_rows = await asyncio.to_thread(
            get_completed_match_history
        )

        player_history = {}

        for row in history_rows:
            if row["player_name"] not in player_names:
                continue

            player_history.setdefault(
                row["player_name"],
                []
            ).append({
                "Match ID": row["match_id"],
                "Match Date": str(row["match_date"]),
                "Points": row["player_points"],
                "Match Performance": float(
                    row["match_performance"]
                ),
                "Group Winner": bool(row["group_winner"]),
                "Match Winner": bool(row["match_winner"])
            })

        current_holder = next(
            (
                row["player_name"]
                for row in reversed(history_rows)
                if row["match_winner"]
            ),
            None
        )

        match_date = match["match_date"]
        location = match["location"]
        tee_time_1 = match["tee_time_1"]
        tee_time_2 = match["tee_time_2"]
        tee_time_3 = match["tee_time_3"]
        tee_time_4 = match["tee_time_4"]
        special_rule = match["special_rule"]

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

            for row in player_availability:
                name = row["player_name"]
                status = row["status"]
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
                    row["status"] == "in"
                    for row in player_availability
                ),
                "Players MAYBE": sum(
                    row["status"] == "maybe"
                    for row in player_availability
                ),
                "Players UNKNOWN": sum(
                    row["status"] == "unknown"
                    for row in player_availability
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

        updated = await asyncio.to_thread(
            execute_upsert,
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

        players = await asyncio.to_thread(
            execute_query,
            """
            SELECT id, discord_user_id
            FROM players
            WHERE discord_user_id IS NOT NULL
              AND active = TRUE
            """
        )

        updated = 0
        not_found = 0
        name_updates = []

        for player in players:
            player_id = player["id"]
            discord_user_id = player["discord_user_id"]

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

        for name_update in name_updates:
            await asyncio.to_thread(
                execute_upsert,
                """
                UPDATE players
                SET discord_username = %s,
                    discord_display_name = %s
                WHERE id = %s
                """,
                name_update
            )

        await interaction.followup.send(
            f"🔄 Player refresh complete.\n"
            f"Updated: **{updated}**\n"
            f"Not found: **{not_found}**",
            ephemeral=True
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

        match = await asyncio.to_thread(get_next_match)

        if match is None:
            await interaction.edit_original_response(
                content=(
                    "🎰 **TAN CITY SPORTSBOOK**\n\n"
                    "No upcoming CFB match found."
                )
            )
            return

        match_id = match["id"]

        current_market = await asyncio.to_thread(
            execute_query,
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

        wagers = await asyncio.to_thread(
            execute_query,
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

        latest_wager_rows = await asyncio.to_thread(
            execute_query,
            """
            SELECT MAX(w.wagered_at) AS latest_wager
            FROM wagers w
            JOIN market_prices mp
                ON w.market_price_id = mp.market_price_id
            WHERE mp.match_id = %s
            """,
            (match_id,)
        )

        latest_wager = latest_wager_rows[0]["latest_wager"]

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
            for market in current_market:
                lines.append(
                    f"**{market['player_name']}** — "
                    f"{format_odds(market['odds_american'])}"
                )
        else:
            lines.append("No current market.")

        lines.extend([
            "",
            "**WAGERED**"
        ])

        if wagers:
            current_player = None

            for wager in wagers:
                player_name = wager["player_name"]

                if player_name != current_player:
                    if current_player is not None:
                        lines.append("")

                    lines.append(f"**{player_name}**")
                    current_player = player_name

                lines.append(
                    f"• ${wager['total_wagered']:,.2f} @ "
                    f"{format_odds(wager['odds_american'])}"
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

        match = await asyncio.to_thread(get_next_match)

        if match is None:
            await interaction.response.send_message(
                "There are no upcoming CFB matches scheduled."
            )
            return

        availability = await asyncio.to_thread(
            get_player_availability,
            match["id"]
        )

        rows = availability["players"]

        match_date = match["match_date"]

        in_count = sum(
            row["status"] == "in"
            for row in rows
        )

        spots_available = availability["available_spots"]

        groups = {
            "in": [],
            "out": [],
            "maybe": [],
            "unknown": []
        }

        for row in rows:
            groups[row["status"]].append(row["player_name"])

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
            (
                match_data,
                player_notes,
                david_gambling
            ) = await asyncio.to_thread(
                get_wrapup_data
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