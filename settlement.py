###################
# Created : 2026-09-08 GB
# Purpose : Settles Tan City Sportsbook wagers after a completed CFB match
#           appears in the authoritative spreadsheet.
#           Reads the most recent completed match from Google Sheets, matches
#           it to the active database match by date, settles outstanding wagers,
#           credits winning gamblers, and updates the bookie's balance.
# Notes   : Settlement is deterministic and does not use an AI model.
#           Only wagers whose outcome is still NULL are eligible for settlement,
#           making repeated runs safe and idempotent.
###################

from dotenv import load_dotenv
load_dotenv()

import mysql.connector
import os


MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")


# Calculate the total cash returned to a gambler when a wager wins.
# This includes return of the original stake.
def calculate_total_payout(wager_amount, odds):
    wager_amount = float(wager_amount)

    if odds > 0:
        profit = wager_amount * odds / 100
    else:
        profit = wager_amount * 100 / abs(odds)

    return round(wager_amount + profit, 2)


# Open a MariaDB/MySQL connection using the application's .env settings.
def get_db_connection():
    return mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
    )


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


# Run settlement once when this module is executed directly.
def main():
    summaries = run_settlement()

    if not summaries:
        print("No completed Tan City match found to settle.")
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


# Settle wagers for only the most recent completed match.
def run_settlement():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                match_id,
                match_date,
                player_name
            FROM vw_completed_match_results
            WHERE match_winner = 1
            ORDER BY
                match_date DESC,
                match_id DESC
            LIMIT 1
            """
        )

        completed_match = cursor.fetchone()

    finally:
        cursor.close()

    try:
        if completed_match is None:
            return []

        summary = settle_match(
            connection,
            completed_match["match_id"],
            str(completed_match["match_date"]),
            completed_match["player_name"],
        )

        return [summary]

    finally:
        connection.close()
        

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

        # Stakes have already been removed from gambler bankrolls, but wager
        # placement does not credit those stakes to the bookie.
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


if __name__ == "__main__":
    main()