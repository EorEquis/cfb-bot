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
    rows = execute_query(
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
        ORDER BY
            match_date,
            GREATEST(
                COALESCE(tee_time_1, '00:00:00'),
                COALESCE(tee_time_2, '00:00:00'),
                COALESCE(tee_time_3, '00:00:00'),
                COALESCE(tee_time_4, '00:00:00')
            )
        LIMIT 1
        """
    )

    return rows[0] if rows else None


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