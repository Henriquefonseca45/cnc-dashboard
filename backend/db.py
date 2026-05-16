import sqlite3
from pathlib import Path
import os

DB_PATH = Path(os.environ.get("CNC_DB_PATH", Path(__file__).resolve().parent.parent / "cnc.db"))

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
