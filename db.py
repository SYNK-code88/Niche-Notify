# db.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    """
    Returns a new psycopg2 connection using DATABASE_URL env variable.
    """
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment")
    return psycopg2.connect(DATABASE_URL)

def create_schema():
    """
    Creates the monitors table if it doesn't exist.
    Run this once from worker.py when you start locally.
    """
    create_sql = """
    CREATE TABLE IF NOT EXISTS monitors (
        id SERIAL PRIMARY KEY,
        url TEXT NOT NULL,
        css_selector TEXT NOT NULL,
        user_email TEXT NOT NULL,
        last_content TEXT,
        last_checked_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(create_sql)
    conn.commit()
    cur.close()
    conn.close()

def get_all_monitors():
    """
    Returns a list of monitors as dicts:
    [{id, url, css_selector, user_email, last_content, last_checked_at}, ...]
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM monitors")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_monitor_content(monitor_id, new_content):
    """
    Update last_content and last_checked_at for a monitor.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE monitors SET last_content = %s, last_checked_at = NOW() WHERE id = %s",
        (new_content, monitor_id)
    )
    conn.commit()
    cur.close()
    conn.close()
