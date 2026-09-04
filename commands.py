import mysql.connector
import discord
import logging
from discord import app_commands
from sheets import get_latest_match_with_history, get_preview_data, get_player_profile, get_power_data
from wrapup import generate_wrapup
from preview import generate_preview
from weather import get_forecast, weather_emoji, format_time
from power import generate_power
from datetime import datetime

logger = logging.getLogger(__name__)

def register_commands(
    bot,
    bot_version,
    dev_guild,
    admin_discord_id,
    mysql_host,
    mysql_port,
    mysql_user,
    mysql_password,
    mysql_database
):

    async def active_match_autocomplete(
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
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
    
    async def player_autocomplete(
        interaction: discord.Interaction,
        current: str
    ):
        conn = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
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

    def log_bot_usage(
        command_name,
        discord_user_id
    ):
        conn = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
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
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
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


    def update_bot_usage_tokens(
        usage_id,
        input_tokens,
        output_tokens
    ):
        conn = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
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


    def admin_only(func):
        func.admin_only = True
        return func

    def bot_admin_only(interaction: discord.Interaction):
        # Permanent/bootstrap admin from .env
        if interaction.user.id == admin_discord_id:
            return True

        # Discord Admins role
        if any(role.name == "Admins" for role in interaction.user.roles):
            return True

        return False

    def dev_channel_only(interaction: discord.Interaction) -> bool:
        return True

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
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
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
        tee_time_4="Fourth tee time in HH:MM format"
    )
    async def addmatch(
        interaction: discord.Interaction,
        match_date: str,
        location: str,
        tee_time_1: str,
        tee_time_2: str | None = None,
        tee_time_3: str | None = None,
        tee_time_4: str | None = None
    ):
        log_bot_usage(
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

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = connection.cursor()

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
        
        existing_match = cursor.fetchone()

        if existing_match:
            cursor.close()
            connection.close()

            await interaction.response.send_message(
                f"A match already exists on **{match_date}**.",
                ephemeral=True
            )
            return
        
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
                    active
                )
            VALUES
                (%s, %s, %s, %s, %s, %s, TRUE)
            """,
            (
                match_date,
                location,
                tee_time_1,
                tee_time_2,
                tee_time_3,
                tee_time_4
            )
        )

        connection.commit()

        cursor.close()
        connection.close()

        await interaction.response.send_message(
            f"Match added for **{match_date}** at **{location}**.",
            ephemeral=True
        )

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
        log_bot_usage(
            "deletematch",
            interaction.user.id
        )

        if not bot_admin_only(interaction):
            await interaction.response.send_message(
                "You are not authorized to use this command.",
                ephemeral=True
            )
            return

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = connection.cursor()

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
            cursor.close()
            connection.close()

            await interaction.response.send_message(
                f"No active match found for **{match_date}**.",
                ephemeral=True
            )
            return

        location = match[0]

        cursor.execute(
            """
            UPDATE matches
            SET active = FALSE
            WHERE match_date = %s
              AND active = TRUE
            """,
            (match_date,)
        )

        connection.commit()

        cursor.close()
        connection.close()

        await interaction.response.send_message(
            f"Deleted match for **{match_date}** at **{location}**.",
            ephemeral=True
        )

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
        log_bot_usage(
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

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = connection.cursor()

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

        if cursor.rowcount == 0:
            connection.rollback()
            cursor.close()
            connection.close()

            await interaction.response.send_message(
                f"No active match found for **{match_date}**.",
                ephemeral=True
            )
            return

        connection.commit()

        cursor.close()
        connection.close()

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
                                            
    @bot.tree.command(
        name="helpbot",
        description="Show available CFB Bot commands",
        guild=dev_guild
    )
    async def helpbot(interaction: discord.Interaction):
        log_bot_usage(
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


    @bot.tree.command(
        name="in",
        description="Mark yourself as playing in the next CFB match",
        guild=dev_guild
    )
    async def playing_in(interaction: discord.Interaction):
        await set_availability(interaction, "in")


    @bot.tree.command(
        name="index",
        description="View the CFB Index spreadsheet",
        guild=dev_guild
    )
    async def index(interaction: discord.Interaction):
        log_bot_usage(
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
        log_bot_usage(
            "match",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = connection.cursor()

        show_all = show is not None and show.value == "all"

        if show_all:
            cursor.execute(
                """
                SELECT
                    match_date,
                    location,
                    tee_time_1,
                    tee_time_2,
                    tee_time_3,
                    tee_time_4,
                    notes
                FROM matches
                WHERE active = TRUE
                  AND match_date >= CURDATE()
                ORDER BY match_date
                """
            )

            matches = cursor.fetchall()

        else:
            cursor.execute(
                """
                SELECT
                    match_date,
                    location,
                    tee_time_1,
                    tee_time_2,
                    tee_time_3,
                    tee_time_4,
                    notes
                FROM matches
                WHERE active = TRUE
                  AND match_date >= CURDATE()
                ORDER BY match_date
                LIMIT 1
                """
            )

            match_row = cursor.fetchone()
            matches = [match_row] if match_row else []

        cursor.close()
        connection.close()

        if not matches:
            await interaction.response.send_message(
                "There are no upcoming CFB matches scheduled."
            )
            return

        def format_tee_time(t):
            total_seconds = int(t.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            suffix = "AM" if hours < 12 else "PM"
            display_hour = hours % 12

            if display_hour == 0:
                display_hour = 12

            return f"{display_hour}:{minutes:02d} {suffix}"

        blocks = []

        for (
            match_date,
            location,
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4,
            notes
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
            match_date, location, tee_time_1, _, _, _, _ = matches[0]

            if tee_time_1 is not None:
                try:
                    forecast_data = get_forecast(
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

                message += (
                    f"\n\n🌤️ **MATCH FORECAST**\n\n"

                    f"**{start_emoji} START — {format_time(start['time'])}**\n"
                    f"🌡️ Temp: **{start['temperature']}°F**\n"
                    f"💧 Humidity: **{start['humidity']}%**\n"
                    f"🥵 Feels Like: **{start['heat_index']}°F**\n"
                    f"🌧️ Rain: **{start['rain_chance']}%**\n"
                    f"☁️ Cloud Cover: **{start['cloud_cover']}%**\n"
                    f"💨 Wind: **{start['wind_direction']} {start['wind_speed']} mph** "
                    f"(gusts {start['wind_gusts']} mph)\n\n"

                    f"**{end_emoji} END — {format_time(end['time'])}**\n"
                    f"🌡️ Temp: **{end['temperature']}°F**\n"
                    f"💧 Humidity: **{end['humidity']}%**\n"
                    f"🥵 Feels Like: **{end['heat_index']}°F**\n"
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
                            
        await interaction.response.send_message(message)


    @bot.tree.command(
        name="maybe",
        description="Mark yourself as maybe playing in the next CFB match",
        guild=dev_guild
    )
    async def playing_maybe(interaction: discord.Interaction):
        await set_availability(interaction, "maybe")


    @bot.tree.command(
        name="out",
        description="Mark yourself as not playing in the next CFB match",
        guild=dev_guild
    )
    async def playing_out(interaction: discord.Interaction):
        await set_availability(interaction, "out")


    @bot.tree.command(
        name="ping",
        description="Make sure CFB Bot is alive",
        guild=dev_guild
    )
    async def ping(interaction: discord.Interaction):
        log_bot_usage(
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
        log_bot_usage(
            "player",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        conn = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = conn.cursor()

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

        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row is None:
            await interaction.response.send_message(
                f'No active CFB player found for "{player}".',
                ephemeral=True
            )
            return

        player_name, display_name, quote = row
        
        profile = get_player_profile(player_name)

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

        await interaction.response.send_message(
            message
        )

    @bot.tree.command(
        name="power",
        description="Show the latest CFB Sports Network power rankings",
        guild=dev_guild
    )
    @admin_only
    async def power(interaction: discord.Interaction):
        usage_id = log_bot_usage(
            "power",
            interaction.user.id
        )

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

        conn = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT player_name
            FROM players
            WHERE active = TRUE
            ORDER BY player_name
            """
        )

        player_names = [
            row[0]
            for row in cursor.fetchall()
        ]

        cursor.close()
        conn.close()

        power_data = get_power_data(player_names)

        try:
            mark_bot_usage_api_call(usage_id)

            result = await generate_power(power_data)

            update_bot_usage_tokens(
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

    @bot.tree.command(
        name="preview",
        description="Get the CFB Sports Network preview for the next match",
        guild=dev_guild
    )
    @admin_only
    async def preview(interaction: discord.Interaction):
        usage_id = log_bot_usage(
            "preview",
            interaction.user.id
        )

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

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                m.id,
                m.match_date,
                m.location,
                m.tee_time_1,
                m.tee_time_2,
                m.tee_time_3,
                m.tee_time_4
            FROM matches m
            WHERE m.active = TRUE
            AND m.match_date >= CURDATE()
            ORDER BY m.match_date
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

        (
            match_id,
            match_date,
            location,
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4
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

        cursor.execute(
            """
            SELECT p.player_name
            FROM availability a
            JOIN players p
                ON p.id = a.player_id
            WHERE a.match_id = %s
            AND a.status = 'in'
            AND p.active = TRUE
            ORDER BY p.player_name
            """,
            (match_id,)
        )

        player_names = [
            row[0]
            for row in cursor.fetchall()
        ]

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

        cursor.close()
        connection.close()

        if not player_names:
            await interaction.response.send_message(
                "Nobody is currently marked IN for the next CFB match.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "📡 **CFB Sports Network is examining the field "
            "and manufacturing irresponsible expectations...**"
        )

        try:
            preview_data = get_preview_data(
                player_names,
                match_date,
                location,
                tee_times
            )

            preview_data["Player Notes"] = player_notes

            mark_bot_usage_api_call(usage_id)

            result = await generate_preview(preview_data)

            update_bot_usage_tokens(
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
        log_bot_usage(
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

        conn = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = conn.cursor()

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

        updated = cursor.rowcount

        conn.commit()
        cursor.close()
        conn.close()

        if updated == 0:
            await interaction.response.send_message(
                "I couldn't find an active CFB player linked to your Discord account.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f'💬 **Favorite quote updated:** *"{quote}"*'
        )

    @bot.tree.command(
        name="refresh",
        description="Refresh Discord names for CFB players",
        guild=dev_guild
    )
    @admin_only
    async def refresh(interaction: discord.Interaction):
        log_bot_usage(
            "refresh",
            interaction.user.id
        )

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

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id, discord_user_id
            FROM players
            WHERE discord_user_id IS NOT NULL
              AND active = TRUE
            """
        )

        players = cursor.fetchall()

        updated = 0
        not_found = 0

        for player_id, discord_user_id in players:
            try:
                member = await interaction.guild.fetch_member(
                    discord_user_id
                )
            except discord.NotFound:
                not_found += 1
                continue

            cursor.execute(
                """
                UPDATE players
                SET discord_username = %s,
                    discord_display_name = %s
                WHERE id = %s
                """,
                (
                    member.name,
                    member.display_name,
                    player_id
                )
            )

            updated += 1

        connection.commit()
        cursor.close()
        connection.close()

        await interaction.response.send_message(
            f"🔄 Player refresh complete.\n"
            f"Updated: **{updated}**\n"
            f"Not found: **{not_found}**",
            ephemeral=True
        )


    @bot.tree.command(
        name="rules",
        description="Get the official CFB rules",
        guild=dev_guild
    )
    async def rules(interaction: discord.Interaction):
        log_bot_usage(
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


    @bot.tree.command(
        name="who",
        description="Show who's in, out, maybe, or unknown for the next CFB match",
        guild=dev_guild
    )
    async def who(interaction: discord.Interaction):
        log_bot_usage(
            "who",
            interaction.user.id
        )

        if not dev_channel_only(interaction):
            await interaction.response.send_message(
                "CFB Bot is currently restricted to #cfb-bot-dev.",
                ephemeral=True
            )
            return

        connection = mysql.connector.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database
        )

        cursor = connection.cursor()

        # Find next active match
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
            (match_id,)
        )

        rows = cursor.fetchall()

        in_count = sum(
            status == "in"
            for _, status in rows
        )

        spots_available = capacity - in_count

        cursor.close()
        connection.close()

        groups = {
            "in": [],
            "out": [],
            "maybe": [],
            "unknown": []
        }

        for player_name, status in rows:
            groups[status].append(player_name)

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


    @bot.tree.command(
        name="wrapup",
        description="Get the latest CFB Sports Network match recap",
        guild=dev_guild
    )
    @admin_only
    async def wrapup(interaction: discord.Interaction):
        usage_id = log_bot_usage(
            "wrapup",
            interaction.user.id
        )

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

        try:
            match_data = get_latest_match_with_history()

            conn = mysql.connector.connect(
                host=mysql_host,
                port=mysql_port,
                user=mysql_user,
                password=mysql_password,
                database=mysql_database
            )

            cursor = conn.cursor()

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

            cursor.close()
            conn.close()

            match_data["Player Notes"] = player_notes            

            mark_bot_usage_api_call(usage_id)

            result = await generate_wrapup(match_data)

            recap = result["text"]

            update_bot_usage_tokens(
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