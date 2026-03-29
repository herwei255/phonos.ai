"""
db.py — SQLite database layer.
All reads/writes go through these functions. Swap to Postgres etc. by only editing here.
"""
import os
import sqlite3
from datetime import datetime
from config import DB_PATH, VOICE_MEMOS_DIR


def init_db() -> None:
    """Create DB and voice_memos folder if they don't exist yet."""
    os.makedirs(VOICE_MEMOS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT UNIQUE NOT NULL,
            filepath     TEXT NOT NULL,
            file_date    TEXT,
            transcript   TEXT,
            summary      TEXT,
            note_type    TEXT DEFAULT 'standard',
            apple_saved  INTEGER DEFAULT 0,
            processed_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_memo(filename: str) -> dict | None:
    """Fetch a single memo row by filename. Returns None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM memos WHERE filename = ?", (filename,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_memo(filename: str, filepath: str, file_date: str,
              transcript: str, summary: str,
              note_type: str, apple_saved: bool) -> None:
    """Insert or update a memo record."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO memos
            (filename, filepath, file_date, transcript, summary,
             note_type, apple_saved, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            transcript   = excluded.transcript,
            summary      = excluded.summary,
            note_type    = excluded.note_type,
            apple_saved  = excluded.apple_saved,
            processed_at = excluded.processed_at
    """, (filename, filepath, file_date, transcript, summary,
          note_type, int(apple_saved), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def mark_apple_saved(filename: str) -> None:
    """Flag a memo as saved to Apple Notes."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE memos SET apple_saved = 1 WHERE filename = ?", (filename,)
    )
    conn.commit()
    conn.close()


def list_memos() -> list[dict]:
    """Return all memo rows ordered by file_date descending."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM memos ORDER BY file_date DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
