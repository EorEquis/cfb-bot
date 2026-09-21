###################
# Created : 2026-09-20 GB
# Purpose : Provides shared internal functionality for CFB players.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 9
#           OpenAI model/version: GPT-5.6 Sol
###################

from db._db import execute_query


def get_player_profile(player):
    rows = execute_query(
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

    return rows[0] if rows else None