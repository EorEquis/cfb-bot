import mysql.connector
import logging


def write_log(
    mysql_host,
    mysql_port,
    mysql_user,
    mysql_password,
    mysql_database,
    severity,
    message,
    source=None
):
    
    conn = mysql.connector.connect(
        host=mysql_host,
        port=mysql_port,
        user=mysql_user,
        password=mysql_password,
        database=mysql_database
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
        mysql_user,
        mysql_password,
        mysql_database
    ):
        super().__init__()

        self.mysql_host = mysql_host
        self.mysql_port = mysql_port
        self.mysql_user = mysql_user
        self.mysql_password = mysql_password
        self.mysql_database = mysql_database

def emit(self, record):
    try:
        write_log(
            self.mysql_host,
            self.mysql_port,
            self.mysql_user,
            self.mysql_password,
            self.mysql_database,
            record.levelname,
            record.getMessage(),
            record.name
        )
    except Exception as e:
        print(f"LOGGING ERROR: {e}")