###################
# Created : 2026-09-20 GB
# Purpose : Provides shared internal functionality for CFB players.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 9
#           OpenAI model/version: GPT-5.6 Sol
###################

from db._db import execute_query


def get_active_player_career_stats():
    return execute_query(
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