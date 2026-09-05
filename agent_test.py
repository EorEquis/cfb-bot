import os

import discord
import mysql.connector
from dotenv import load_dotenv
from openai import OpenAI
from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.row_event import WriteRowsEvent

from cfb_voice import CFB_VOICE

load_dotenv()

client = OpenAI()

DEV_CHANNEL_ID = int(os.getenv("DEV_CHANNEL_ID"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE")
    )


def get_history():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            situation,
            decision,
            response,
            spoken_at
        FROM agent_test_history
        ORDER BY spoken_at
        """
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def remember_observation(situation, decision, response=None):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO agent_test_history
            (situation, decision, response)
        VALUES
            (%s, %s, %s)
        """,
        (situation, decision, response)
    )

    conn.commit()

    cursor.close()
    conn.close()


def evaluate_situation(situation, history):
    if history:
        history_parts = []

        for number, row in enumerate(history, start=1):
            previous_situation, decision, response, spoken_at = row

            history_parts.append(
                f"""
Observation {number}:
Situation: {previous_situation}
Decision: {decision or "UNKNOWN"}
Response: {response or "None"}
"""
            )

        history_text = "\n".join(history_parts)

    else:
        history_text = "No previous observations."

    response = client.responses.create(
        model="gpt-5.6-sol",
        input=f"""
{CFB_VOICE}

CURRENT SITUATION:

{situation}

OBSERVATION HISTORY:

{history_text}

Your task is to decide whether CFB Sports Network should make an announcement
about the current situation.

Use the observation history as context.

Consider:
- whether this is the same event as something already observed
- whether this kind of event has become common or routine
- whether new information makes an existing situation meaningfully different
- whether the current situation is unusual, important, or interesting enough
  to warrant coverage

A situation that was once unusual may become routine if similar observations
occur repeatedly.

If no announcement is warranted, reply exactly:

SILENT

If an announcement is warranted, reply:

SPEAK
<one short CFB Sports Network announcement>
"""
    )

    return response.output_text.strip()


async def post_to_dev_channel(message):
    intents = discord.Intents.default()

    bot = discord.Client(intents=intents)

    @bot.event
    async def on_ready():
        try:
            channel = bot.get_channel(DEV_CHANNEL_ID)

            if channel is None:
                print(f"Could not find dev channel {DEV_CHANNEL_ID}.")
                return

            await channel.send(message)
            print(f"Posted to dev channel: {channel.name}")

        finally:
            await bot.close()

    await bot.start(DISCORD_TOKEN)


def process_situation(situation):
    history = get_history()

    print()
    print(f"Situation: {situation}")
    print(f"Previous observations: {len(history)}")

    decision = evaluate_situation(situation, history)

    print()
    print(decision)

    if decision == "SILENT":
        remember_observation(
            situation=situation,
            decision="SILENT"
        )

        print()
        print("Silent observation added to agent history.")
        return

    if not decision.startswith("SPEAK"):
        print("Unexpected model response. Nothing recorded or posted.")
        return

    message = decision.removeprefix("SPEAK").strip()

    if not message:
        print("Agent chose SPEAK but supplied no message.")
        return

    import asyncio

    asyncio.run(post_to_dev_channel(message))

    remember_observation(
        situation=situation,
        decision="SPEAK",
        response=message
    )

    print("Spoken observation added to agent history.")

CHECKPOINT_FILE = "agent_binlog_checkpoint.txt"


def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return None, None

    with open(CHECKPOINT_FILE, "r") as f:
        line = f.read().strip()

    if not line:
        return None, None

    log_file, log_pos = line.split("|")

    return log_file, int(log_pos)


def save_checkpoint(log_file, log_pos):
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(f"{log_file}|{log_pos}")

def listen_for_agent_events():
    mysql_settings = {
        "host": os.getenv("MYSQL_HOST"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "passwd": os.getenv("MYSQL_PASSWORD")
    }

    log_file, log_pos = load_checkpoint()

    if log_file and log_pos:
        print(f"Resuming from {log_file} position {log_pos}")
    else:
        print("No checkpoint found. Starting from current binlog position.")

    stream = BinLogStreamReader(
        connection_settings=mysql_settings,
        server_id=1001,
        blocking=True,
        resume_stream=True,
        log_file=log_file,
        log_pos=log_pos,
        only_events=[WriteRowsEvent],
        only_schemas=[os.getenv("MYSQL_DATABASE")],
        only_tables=["agent_test"]
    )

    print("Listening for inserts into agent_test...")

    try:
        for binlog_event in stream:
            for row in binlog_event.rows:
                values = row["values"]

                print("BINLOG EVENT:", values)

                situation = values.get("UNKNOWN_COL1")

                if situation:
                    process_situation(situation)

            save_checkpoint(stream.log_file, stream.log_pos)

    finally:
        stream.close()

if __name__ == "__main__":
    listen_for_agent_events()