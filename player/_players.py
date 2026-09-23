###################
# Created : 2026-09-20 GB
# Purpose : Provides shared internal functionality for CFB players.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 9
#           OpenAI model/version: GPT-5.6 Sol
###################

from db._db import execute_query


def get_current_cfb_holder():
    rows = execute_query(
        """
        SELECT player_name
        FROM vw_completed_match_results
        WHERE match_winner = 1
        ORDER BY match_date DESC, match_id DESC
        LIMIT 1
        """
    )

    return rows[0]["player_name"] if rows else None


def get_player_availability(match_id):
    match_rows = execute_query(
        """
        SELECT
            tee_time_1,
            tee_time_2,
            tee_time_3,
            tee_time_4
        FROM matches
        WHERE id = %s
        LIMIT 1
        """,
        (match_id,)
    )

    if not match_rows:
        return None

    match = match_rows[0]

    player_rows = execute_query(
        """
        SELECT
            p.id AS player_id,
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

    max_spots = sum(
        tee_time is not None
        for tee_time in (
            match["tee_time_1"],
            match["tee_time_2"],
            match["tee_time_3"],
            match["tee_time_4"]
        )
    ) * 4

    in_count = sum(
        row["status"] == "in"
        for row in player_rows
    )

    return {
        "players": player_rows,
        "max_spots": max_spots,
        "available_spots": max_spots - in_count
    }
    
    
def get_player_profile():
    return execute_query(
        """
        SELECT
            p.id AS player_id,
            p.player_name,
            p.discord_display_name,
            s.quote,
            s.normalized_cfb_index,
            s.matches_played,
            s.total_points,
            s.group_wins,
            s.match_wins,
            CASE
                WHEN p.id = (
                    SELECT r.player_id
                    FROM vw_completed_match_results r
                    WHERE r.match_winner = 1
                    ORDER BY r.match_date DESC, r.match_id DESC
                    LIMIT 1
                )
                THEN 1
                ELSE 0
            END AS current_cfb,
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
        ORDER BY p.player_name
        """
    )


def get_player_recent_performances(player_id):
    return execute_query(
        """
        SELECT match_performance
        FROM vw_completed_match_results
        WHERE player_id = %s
        ORDER BY match_date DESC, match_id DESC
        LIMIT 3
        """,
        (player_id,)
    )