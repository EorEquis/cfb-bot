###################
# Created : 2026-09-19 GB
# Purpose : Provides shared internal functionality for CFB match broadcasts.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 8
#           OpenAI model/version: GPT-5.6 Sol
###################

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