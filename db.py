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
    """Create DB and tables if they don't exist. Runs schema migrations."""
    os.makedirs(VOICE_MEMOS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    # ── Users ──────────────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id  TEXT UNIQUE NOT NULL,
            email      TEXT NOT NULL,
            name       TEXT,
            picture    TEXT,
            created_at TEXT
        )
    """)

    # Local fallback user (id=1) — used in password-auth / single-user mode.
    conn.execute("""
        INSERT OR IGNORE INTO users (id, google_id, email, name, created_at)
        VALUES (1, 'local', 'local@phonos.ai', 'Local User', ?)
    """, (datetime.now().isoformat(),))

    # ── Series ─────────────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER REFERENCES users(id),
            name       TEXT NOT NULL,
            created_at TEXT,
            UNIQUE(user_id, name)
        )
    """)

    # ── Glossary (global — shared hedge-fund terminology across all users) ──────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS glossary (
            term       TEXT NOT NULL,
            definition TEXT NOT NULL,
            note_type  TEXT NOT NULL DEFAULT 'hedge_fund',
            created_at TEXT,
            PRIMARY KEY (term, note_type)
        )
    """)

    # ── Chat history ───────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER REFERENCES users(id),
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # ── Memos ──────────────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id),
            filename     TEXT NOT NULL,
            filepath     TEXT NOT NULL,
            file_date    TEXT,
            transcript   TEXT,
            summary      TEXT,
            note_type    TEXT DEFAULT 'standard',
            apple_saved  INTEGER DEFAULT 0,
            processed_at TEXT,
            display_name TEXT,
            series_id    INTEGER REFERENCES series(id),
            segments     TEXT,
            UNIQUE(user_id, filename)
        )
    """)

    # ── Migrations for existing databases ──────────────────────────────────────

    # memos: if user_id missing, recreate table with correct schema and migrate data
    memos_cols = {row[1] for row in conn.execute("PRAGMA table_info(memos)")}
    if "user_id" not in memos_cols:
        conn.execute("ALTER TABLE memos RENAME TO _memos_v1")
        conn.execute("""
            CREATE TABLE memos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER REFERENCES users(id),
                filename     TEXT NOT NULL,
                filepath     TEXT NOT NULL,
                file_date    TEXT,
                transcript   TEXT,
                summary      TEXT,
                note_type    TEXT DEFAULT 'standard',
                apple_saved  INTEGER DEFAULT 0,
                processed_at TEXT,
                display_name TEXT,
                series_id    INTEGER REFERENCES series(id),
                segments     TEXT,
                UNIQUE(user_id, filename)
            )
        """)
        # Assign all legacy memos to the local user (id=1)
        conn.execute("""
            INSERT INTO memos
                (id, user_id, filename, filepath, file_date, transcript, summary,
                 note_type, apple_saved, processed_at, display_name, series_id, segments)
            SELECT id, 1, filename, filepath, file_date, transcript, summary,
                   note_type, apple_saved, processed_at, display_name,
                   series_id,
                   CASE WHEN typeof(segments) = 'text' THEN segments ELSE NULL END
            FROM _memos_v1
        """)
        conn.execute("DROP TABLE _memos_v1")

    # chat_history: add user_id if missing; assign legacy rows to local user
    chat_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_history)")}
    if "user_id" not in chat_cols:
        conn.execute("ALTER TABLE chat_history ADD COLUMN user_id INTEGER REFERENCES users(id)")
        conn.execute("UPDATE chat_history SET user_id = 1 WHERE user_id IS NULL")

    # series: add user_id if missing; assign legacy rows to local user
    series_cols = {row[1] for row in conn.execute("PRAGMA table_info(series)")}
    if "user_id" not in series_cols:
        conn.execute("ALTER TABLE series ADD COLUMN user_id INTEGER REFERENCES users(id)")
        conn.execute("UPDATE series SET user_id = 1 WHERE user_id IS NULL")

    # memos: add segments column if somehow missing
    memos_cols2 = {row[1] for row in conn.execute("PRAGMA table_info(memos)")}
    if "segments" not in memos_cols2:
        conn.execute("ALTER TABLE memos ADD COLUMN segments TEXT")

    conn.commit()
    conn.close()


# ── Users ──────────────────────────────────────────────────────────────────────

def get_or_create_user(google_id: str, email: str,
                        name: str | None = None,
                        picture: str | None = None) -> dict:
    """Return existing user or create new one. Updates name/picture on each login."""
    conn = _connect()
    conn.execute("""
        INSERT INTO users (google_id, email, name, picture, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET
            email   = excluded.email,
            name    = excluded.name,
            picture = excluded.picture
    """, (google_id, email, name, picture, datetime.now().isoformat()))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
    conn.close()
    return dict(row)


def get_user(user_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Memos ──────────────────────────────────────────────────────────────────────

def get_memo(filename: str, user_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM memos WHERE filename = ? AND user_id = ?",
        (filename, user_id)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
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
              user_id: int,
              segments: list | None = None,
              display_name: str | None = None) -> None:
    segments_json = json.dumps(segments) if segments else None
    conn = _connect()
    conn.execute("""
        INSERT INTO memos
            (user_id, filename, filepath, file_date, transcript, summary,
             note_type, apple_saved, processed_at, segments, display_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, filename) DO UPDATE SET
            transcript   = excluded.transcript,
            summary      = excluded.summary,
            note_type    = excluded.note_type,
            apple_saved  = excluded.apple_saved,
            processed_at = excluded.processed_at,
            segments     = excluded.segments,
            display_name = COALESCE(excluded.display_name, memos.display_name)
    """, (user_id, filename, filepath, file_date, transcript, summary,
          note_type, int(apple_saved), datetime.now().isoformat(),
          segments_json, display_name))
    conn.commit()
    conn.close()


def rename_memo(filename: str, display_name: str, user_id: int) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE memos SET display_name = ? WHERE filename = ? AND user_id = ?",
        (display_name.strip() or None, filename, user_id)
    )
    conn.commit()
    conn.close()


def delete_memo(filename: str, user_id: int) -> None:
    conn = _connect()
    conn.execute("DELETE FROM memos WHERE filename = ? AND user_id = ?", (filename, user_id))
    conn.commit()
    conn.close()


def mark_apple_saved(filename: str, user_id: int) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE memos SET apple_saved = 1 WHERE filename = ? AND user_id = ?",
        (filename, user_id)
    )
    conn.commit()
    conn.close()


def list_memos(user_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM memos WHERE user_id = ? ORDER BY file_date DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Glossary ──────────────────────────────────────────────────────────────────

def get_glossary(note_type: str = "hedge_fund") -> list[dict]:
    """Return all dynamic glossary terms for the given note_type."""
    conn = _connect()
    rows = conn.execute(
        "SELECT term, definition, created_at FROM glossary WHERE note_type = ? ORDER BY term",
        (note_type,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_glossary_term(term: str, definition: str, note_type: str = "hedge_fund") -> None:
    conn = _connect()
    conn.execute("""
        INSERT INTO glossary (term, definition, note_type, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(term, note_type) DO UPDATE SET
            definition = excluded.definition,
            created_at = excluded.created_at
    """, (term.strip(), definition.strip(), note_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def delete_glossary_term(term: str, note_type: str = "hedge_fund") -> None:
    conn = _connect()
    conn.execute("DELETE FROM glossary WHERE term = ? AND note_type = ?", (term, note_type))
    conn.commit()
    conn.close()


# ── Series ────────────────────────────────────────────────────────────────────

def set_memo_series(filename: str, series_id: int | None, user_id: int) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE memos SET series_id = ? WHERE filename = ? AND user_id = ?",
        (series_id, filename, user_id)
    )
    conn.commit()
    conn.close()


def create_series(name: str, user_id: int) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO series (user_id, name, created_at) VALUES (?, ?, ?)",
        (user_id, name.strip(), datetime.now().isoformat())
    )
    series_id = cur.lastrowid
    conn.commit()
    conn.close()
    return series_id


def list_series(user_id: int) -> list[dict]:
    conn = _connect()
    rows = conn.execute("""
        SELECT s.id, s.name, s.created_at,
               COUNT(m.id) AS memo_count
        FROM series s
        LEFT JOIN memos m ON m.series_id = s.id AND m.user_id = s.user_id
        WHERE s.user_id = ?
        GROUP BY s.id
        ORDER BY s.name
    """, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_series_with_memos(series_id: int, user_id: int) -> dict | None:
    conn = _connect()
    s = conn.execute(
        "SELECT * FROM series WHERE id = ? AND user_id = ?",
        (series_id, user_id)
    ).fetchone()
    if not s:
        conn.close()
        return None
    memos = conn.execute(
        "SELECT * FROM memos WHERE series_id = ? AND user_id = ? ORDER BY file_date ASC",
        (series_id, user_id)
    ).fetchall()
    conn.close()
    result = dict(s)
    result["memos"] = [dict(m) for m in memos]
    return result


# ── Chat history ──────────────────────────────────────────────────────────────

def append_chat_message(role: str, content: str, user_id: int) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO chat_history (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (user_id, role, content, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_chat_history(user_id: int, limit: int = 200) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content, created_at FROM chat_history "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def clear_chat_history(user_id: int) -> None:
    conn = _connect()
    conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
