###################
# Created : 2026-09-02 GB
# Purpose : Reads CFB match and player data from Google Sheets and transforms
#           it into structured data used by bot commands and AI-generated
#           previews, power rankings, player profiles, and match wrapups.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import os
import pandas as pd

from datetime import date


# Read the Google Sheets document ID from environment configuration.
SPREADSHEET_ID = os.getenv("CFB_SHEET_ID")

# Read the Matches worksheet as a pandas DataFrame.
def get_matches():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/"
        f"gviz/tq?tqx=out:csv&sheet=Matches"
    )

    df = pd.read_csv(url)

    # Drop completely empty columns
    df = df.dropna(axis=1, how="all")

    return df


# Read the Players worksheet as a pandas DataFrame.
def get_players():
    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet=Players"
    )

    return pd.read_csv(url)


