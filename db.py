"""
db.py — SQLite database layer.
All reads/writes go through these functions. Swap to Postgres etc. by only editing here.
"""
import json
import os
import sqlite3
from datetime import datetime
from config import DB_PATH, VOICE_MEMOS_DIR


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create DB and voice_memos folder if they don't exist yet.
    Also runs any schema migrations needed for existing databases.
    """
    os.makedirs(VOICE_MEMOS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            created_at TEXT
        )
    """)

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
            processed_at TEXT,
            display_name TEXT,
            series_id    INTEGER REFERENCES series(id)
        )
    """)

    # Migrations for existing databases
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(memos)")}
    for col, defn in [
        ("display_name", "TEXT"),
        ("series_id",    "INTEGER REFERENCES series(id)"),
        ("segments",     "TEXT"),   # JSON array of {id, start, end, text} from Whisper
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE memos ADD COLUMN {col} {defn}")

    conn.commit()
    conn.close()


# ── Memos ─────────────────────────────────────────────────────────────────────

def get_memo(filename: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM memos WHERE filename = ?", (filename,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    # Deserialise segments JSON → list (or empty list for old memos)
    if d.get("segments"):
        try:
            d["segments"] = json.loads(d["segments"])
        except (json.JSONDecodeError, TypeError):
            d["segments"] = []
    else:
        d["segments"] = []
    return d


def save_memo(filename: str, filepath: str, file_date: str,
              transcript: str, summary: str,
              note_type: str, apple_saved: bool,
              segments: list | None = None) -> None:
    segments_json = json.dumps(segments) if segments else None
    conn = _connect()
    conn.execute("""
        INSERT INTO memos
            (filename, filepath, file_date, transcript, summary,
             note_type, apple_saved, processed_at, segments)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            transcript   = excluded.transcript,
            summary      = excluded.summary,
            note_type    = excluded.note_type,
            apple_saved  = excluded.apple_saved,
            processed_at = excluded.processed_at,
            segments     = excluded.segments
    """, (filename, filepath, file_date, transcript, summary,
          note_type, int(apple_saved), datetime.now().isoformat(),
          segments_json))
    conn.commit()
    conn.close()


def rename_memo(filename: str, display_name: str) -> None:
    conn = _connect()
    conn.execute("UPDATE memos SET display_name = ? WHERE filename = ?",
                 (display_name.strip() or None, filename))
    conn.commit()
    conn.close()


def delete_memo(filename: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM memos WHERE filename = ?", (filename,))
    conn.commit()
    conn.close()


def mark_apple_saved(filename: str) -> None:
    conn = _connect()
    conn.execute("UPDATE memos SET apple_saved = 1 WHERE filename = ?", (filename,))
    conn.commit()
    conn.close()


def list_memos() -> list[dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM memos ORDER BY file_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_memo_series(filename: str, series_id: int | None) -> None:
    """Assign a memo to a series, or pass None to unlink it."""
    conn = _connect()
    conn.execute("UPDATE memos SET series_id = ? WHERE filename = ?",
                 (series_id, filename))
    conn.commit()
    conn.close()


# ── Series ────────────────────────────────────────────────────────────────────

def create_series(name: str) -> int:
    """Create a new series and return its id. Raises if name already exists."""
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO series (name, created_at) VALUES (?, ?)",
        (name.strip(), datetime.now().isoformat())
    )
    series_id = cur.lastrowid
    conn.commit()
    conn.close()
    return series_id


def list_series() -> list[dict]:
    """Return all series with a count of how many memos belong to each."""
    conn = _connect()
    rows = conn.execute("""
        SELECT s.id, s.name, s.created_at,
               COUNT(m.id) AS memo_count
        FROM series s
        LEFT JOIN memos m ON m.series_id = s.id
        GROUP BY s.id
        ORDER BY s.name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_series_with_memos(series_id: int) -> dict | None:
    """Return a series dict with a 'memos' list sorted by file_date ascending."""
    conn = _connect()
    s = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if not s:
        conn.close()
        return None
    memos = conn.execute(
        "SELECT * FROM memos WHERE series_id = ? ORDER BY file_date ASC",
        (series_id,)
    ).fetchall()
    conn.close()
    result = dict(s)
    result["memos"] = [dict(m) for m in memos]
    return result
