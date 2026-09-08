###################
# Created : 2026-09-08 GB
# Purpose : Development test harness for settling Tan City wagers after a
#           completed CFB match appears in the authoritative spreadsheet.
# Notes   : Reads completed results from sheets.py and settles only wagers
#           whose outcome is still NULL.
###################

from dotenv import load_dotenv
load_dotenv()

import os

import mysql.connector

import sheets


MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")


# Open a MariaDB/MySQL connection using the bot's existing .env settings.
def get_db_connection():
    return mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )


# Calculate the total cash returned to a gambler when a wager wins.
# This includes return of the original stake.
def calculate_total_payout(wager_amount, odds):
    wager_amount = float(wager_amount)

    if odds > 0:
        profit = wager_amount * odds / 100
    else:
        profit = wager_amount * 100 / abs(odds)

    return round(wager_amount + profit, 2)


# Return unsettled wagers for one database match.
def get_unsettled_wagers(cursor, match_id):
    cursor.execute(
        """
        SELECT
            w.wager_id,
            w.gambler_id,
            w.wager_amount,
            mp.odds_american,
            p.player_name
        FROM wagers w
        INNER JOIN market_prices mp
            ON mp.market_price_id = w.market_price_id
        INNER JOIN players p
            ON p.id = mp.player_id
        WHERE mp.match_id = %s
          AND w.outcome IS NULL
        ORDER BY w.wager_id
        """,
        (match_id,),
    )

    return cursor.fetchall()


# Settle every currently unsettled wager for one completed match.
def settle_match(connection, match_id, match_date, winner_name):
    cursor = connection.cursor(dictionary=True)

    try:
        wagers = get_unsettled_wagers(
            cursor,
            match_id,
        )

        if not wagers:
            return {
                "match_id": match_id,
                "match_date": match_date,
                "winner": winner_name,
                "settled": 0,
                "wins": 0,
                "losses": 0,
                "total_staked": 0.0,
                "total_payout": 0.0,
                "bookie_net": 0.0,
            }

        settled = 0
        wins = 0
        losses = 0
        total_staked = 0.0
        total_payout = 0.0

        for wager in wagers:
            wager_id = wager["wager_id"]
            gambler_id = wager["gambler_id"]
            wager_amount = float(wager["wager_amount"])
            odds = wager["odds_american"]
            player_name = wager["player_name"].strip()

            total_staked += wager_amount

            won = (
                player_name.lower()
                == winner_name.lower()
            )

            if won:
                outcome = "win"

                payout = calculate_total_payout(
                    wager_amount,
                    odds,
                )

                # Return the original stake plus winnings to the gambler.
                cursor.execute(
                    """
                    UPDATE gamblers
                    SET current_balance = current_balance + %s
                    WHERE gambler_id = %s
                    """,
                    (
                        payout,
                        gambler_id,
                    ),
                )

                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"Gambler {gambler_id} balance was not updated exactly once."
                    )

                wins += 1
                total_payout += payout

            else:
                outcome = "loss"
                payout = 0.0
                losses += 1

            # Store the final wager result.
            cursor.execute(
                """
                UPDATE wagers
                SET
                    outcome = %s,
                    payout = %s
                WHERE wager_id = %s
                  AND outcome IS NULL
                """,
                (
                    outcome,
                    payout,
                    wager_id,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Wager {wager_id} was not settled exactly once."
                )

            settled += 1

        # Stakes have already been removed from gambler bankrolls, but the
        # current wager-placement code does not credit them to the bookie.
        #
        # Settle the bookie in one net movement:
        #
        #     all stakes received - all winning payouts paid
        #
        # Losing wagers therefore increase the bookie's balance by their stake.
        # Winning wagers reduce the bookie's balance by the bettor's profit.
        bookie_net = round(
            total_staked - total_payout,
            2,
        )

        cursor.execute(
            """
            UPDATE bookie_balance
            SET current_balance = current_balance + %s
            """,
            (bookie_net,),
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                "Bookie balance row was not updated exactly once."
            )

        connection.commit()

        return {
            "match_id": match_id,
            "match_date": match_date,
            "winner": winner_name,
            "settled": settled,
            "wins": wins,
            "losses": losses,
            "total_staked": round(total_staked, 2),
            "total_payout": round(total_payout, 2),
            "bookie_net": bookie_net,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()

# Settle wagers for only the most recent completed match in the authoritative
# spreadsheet. Older completed matches are intentionally ignored.
def settle_completed_matches():
    latest_match = sheets.get_latest_match()

    if latest_match is None or latest_match.empty:
        return []

    winner_rows = latest_match[
        latest_match["Match Winner"] == 1
    ]

    if len(winner_rows) != 1:
        raise RuntimeError(
            "Latest completed match does not have exactly one Match Winner."
        )

    winner_row = winner_rows.iloc[0]

    match_date = str(winner_row["Match Date"])
    winner_name = str(winner_row["Player"]).strip()

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                id,
                match_date
            FROM matches
            WHERE match_date = %s
              AND active = TRUE
            LIMIT 1
            """,
            (match_date,),
        )

        db_match = cursor.fetchone()

    finally:
        cursor.close()

    try:
        if db_match is None:
            return []

        summary = settle_match(
            connection,
            db_match["id"],
            str(db_match["match_date"]),
            winner_name,
        )

        return [summary]

    finally:
        connection.close()


def main():
    summaries = settle_completed_matches()

    if not summaries:
        print("No completed database matches found to settle.")
        return

    for summary in summaries:
        print(
            f"{summary['match_date']} | "
            f"Winner: {summary['winner']} | "
            f"Settled: {summary['settled']} | "
            f"Wins: {summary['wins']} | "
            f"Losses: {summary['losses']} | "
            f"Total payout: ${summary['total_payout']:.2f}"
        )


if __name__ == "__main__":
    main()