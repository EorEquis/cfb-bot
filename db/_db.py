###################
# Created : 2026-09-19 GB
# Purpose : Provides shared database access for the CFB Bot.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Chat 8
#           OpenAI model/version: GPT-5.6 Sol
###################

import mysql.connector
import os


MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")


def execute_query(query, params=None):
    connection = mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params or ())

        return cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()

# Used for any write operation.  INSERT, UPDATE, ON DUPLICATE KEY
def execute_upsert(query, params=None):
    connection = mysql.connector.connect(
        connection_timeout=5,
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )

    cursor = None

    try:
        cursor = connection.cursor()
        cursor.execute(query, params or ())
        connection.commit()

        return cursor.rowcount

    except Exception:
        connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        connection.close()