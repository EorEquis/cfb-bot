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
import queue
import threading

from db._db import execute_upsert

def write_log(
    severity,
    message,
    source=None
):
    execute_upsert(
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

class DatabaseLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()

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
                    severity,
                    message,
                    source
                )
            except Exception as e:
                print(f"LOGGING ERROR: {e}")
        
    def emit(self, record):
        try:
            message = self.format(record)

            self.log_queue.put(
                (
                    record.levelname,
                    message,
                    record.name
                )
            )
        except Exception as e:
            print(f"LOGGING ERROR: {e}")