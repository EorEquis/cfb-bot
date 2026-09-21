###################
# Created : 2026-09-19 GB
# Purpose : Provides shared internal functionality for CFB match broadcasts.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 8
#           OpenAI model/version: GPT-5.6 Sol
###################

from db._db import execute_query
from openai import AsyncOpenAI


client = AsyncOpenAI()


async def generate_match_broadcast(model, prompt):
    response = await client.responses.create(
        model=model,
        input=prompt
    )

    if response.usage:
        return {
            "text": response.output_text,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens
        }

    return response.output_text


def get_active_matches():
    return execute_query(
        """
        SELECT
            *
        FROM matches
        WHERE active = TRUE
        ORDER BY match_date DESC
        """
    )
    
def get_last_match():
    rows = execute_query(
        """
        SELECT
            m.*
        FROM matches m
        WHERE m.active = TRUE
          AND EXISTS (
                SELECT 1
                FROM vw_completed_match_results cmr
                WHERE cmr.match_id = m.match_id
              )
        ORDER BY
            m.match_date DESC,
            m.match_id DESC
        LIMIT 1
        """
    )

    return rows[0] if rows else None


def get_next_match():
    matches = get_upcoming_matches()

    return matches[0] if matches else None


def get_upcoming_matches():
    return execute_query(
        """
        SELECT
            *
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
        """
    )


def get_wrapup_data():
    latest_matches = execute_query(
        """
        SELECT
            match_id,
            match_date
        FROM vw_completed_match_results
        ORDER BY match_date DESC, match_id DESC
        LIMIT 1
        """
    )

    if not latest_matches:
        raise RuntimeError(
            "No completed CFB matches found."
        )

    latest_match = latest_matches[0]
    match_id = latest_match["match_id"]
    match_date = latest_match["match_date"]

    match_rows = execute_query(
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

    groups_by_id = {}
    current_player_ids = []

    for row in match_rows:
        group_id = row["group_id"]
        player_id = row["player_id"]

        current_player_ids.append(player_id)

        if group_id not in groups_by_id:
            groups_by_id[group_id] = {
                "Group": int(group_id),
                "Players in Group": int(row["players_in_group"]),
                "Total Points": int(row["total_points"]),
                "Ending Hole": int(row["ending_hole"]),
                "Players": []
            }

        groups_by_id[group_id]["Players"].append({
            "Player": row["player_name"],
            "Player ID": player_id,
            "Points": int(row["player_points"]),
            "Pre-Match Index": float(row["pre_match_index"]),
            "Match Performance": float(row["match_performance"]),
            "Group Winner": bool(row["group_winner"]),
            "Match Winner": bool(row["match_winner"]),
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
        history_rows = execute_query(
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

        for row in history_rows:
            history_by_player.setdefault(
                row["player_id"],
                []
            ).append({
                "Match Performance": float(row["match_performance"]),
                "Group Winner": bool(row["group_winner"]),
                "Match Winner": bool(row["match_winner"])
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

    note_rows = execute_query(
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
        row["player_name"]: row["notes"]
        for row in note_rows
    }

    david_rows = execute_query(
        """
        SELECT
            gambler_id,
            current_balance
        FROM gamblers
        WHERE is_david = TRUE
        LIMIT 1
        """
    )

    david_gambling = None

    if david_rows:
        david = david_rows[0]
        david_gambler_id = david["gambler_id"]
        current_balance = david["current_balance"]

        wager_rows = execute_query(
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

        if wager_rows:
            david_wagers = [
                {
                    "Player": row["player_name"],
                    "Odds": row["odds_american"],
                    "Wager Amount": float(row["wager_amount"]),
                    "Outcome": row["outcome"],
                    "Payout": float(row["payout"] or 0)
                }
                for row in wager_rows
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