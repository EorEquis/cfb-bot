###################
# Created : 2026-09-03 GB
# Purpose : Provides database-backed logging for the CFB Bot.
#           Writes application log messages to the MariaDB bot_log table
#           and provides a logging.Handler for use with Python logging.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: CFB Index
#           OpenAI model/version: GPT-5.6 Sol
###################

import logging
import mysql.connector
import queue
import threading


def write_log(
    mysql_host,
    mysql_port,
    mysql_database,
    mysql_user,
    mysql_password,
    severity,
    message,
    source=None
):
    
    conn = mysql.connector.connect(
        connection_timeout=5,
        host=mysql_host,
        port=mysql_port,
        database=mysql_database,
        user=mysql_user,
        password=mysql_password
    )

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO bot_log
            (severity, source, message)
        VALUES (%s, %s, %s)
        """,
        (
            severity,
            source,
            message
        )
    )

    conn.commit()
    cursor.close()
    conn.close()


class DatabaseLogHandler(logging.Handler):
    def __init__(
        self,
        mysql_host,
        mysql_port,
        mysql_database,
        mysql_user,
        mysql_password
    ):
        super().__init__()

        self.mysql_host = mysql_host
        self.mysql_port = mysql_port
        self.mysql_database = mysql_database
        self.mysql_user = mysql_user
        self.mysql_password = mysql_password

        self.log_queue = queue.SimpleQueue()
        self.worker = threading.Thread(
            target=self._write_queued_logs,
            daemon=True,
            name="cfb-database-logger"
        )
        self.worker.start()

    def _write_queued_logs(self):
        while True:
            severity, message, source = self.log_queue.get()

            try:
                write_log(
                    self.mysql_host,
                    self.mysql_port,
                    self.mysql_database,
                    self.mysql_user,
                    self.mysql_password,
                    severity,
                    message,
                    source
                )
            except Exception as e:
                print(f"LOGGING ERROR: {e}")
        
    def emit(self, record):
        try:
            self.log_queue.put(
                (
                    record.levelname,
                    record.getMessage(),
                    record.name
                )
            )
        except Exception as e:
            print(f"LOGGING ERROR: {e}")