"""
voice_memo_metadata.py — Extract human-readable display names from Apple's
VoiceMemos SQLite database.

iPhone Voice Memos synced via iCloud arrive as files with machine-generated
names like "20260329 230125-6587917D.qta". Apple stores the real display
name (e.g. "Meeting with David") in a CoreData SQLite database at:

    ~/Library/Group Containers/group.com.apple.VoiceMemos.shared/VoiceMemos.sqlite

This module queries that DB to resolve the friendly name for a given filename.
Falls back to a cleaned-up version of the filename if the DB isn't accessible
or the recording isn't found.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

_VM_DB = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/VoiceMemos.sqlite"
)


# ── Public API ────────────────────────────────────────────────────────────────

def get_display_name(filename: str) -> str | None:
    """Return the human-readable label for a voice memo file.

    Lookup order:
      1. ZCUSTOMLABEL in VoiceMemos.sqlite (user-given name in the Voice Memos app)
      2. Clean version of the filename (strips date prefix + hex suffix + extension)
         e.g. "20260329 230125-6587917D.qta" → "New Recording"  (generic fallback)

    Args:
        filename: The base filename, e.g. "20260329 230125-6587917D.qta"

    Returns:
        A non-empty string display name, or None if we truly cannot infer anything.
    """
    # Try the SQLite lookup first
    name = _lookup_in_db(filename)
    if name:
        return name

    # Fallback: make the filename a bit friendlier
    return _friendly_filename(filename)


# ── SQLite lookup ─────────────────────────────────────────────────────────────

def _lookup_in_db(filename: str) -> str | None:
    """Query VoiceMemos.sqlite for the custom label matching this filename.

    Apple CoreData stores the UUID/unique-id for each recording in ZUNIQUEID.
    The unique-id fragment appears as the hex suffix in the filename:
      "20260329 230125-6587917D.qta"  →  fragment = "6587917D"

    We try several match strategies in order:
      a) ZUNIQUEID LIKE '%<fragment>%'          (partial UUID match)
      b) ZUNIQUEID = '<fragment>'               (exact short ID)
      c) Date-based match using the filename timestamp

    Returns the ZCUSTOMLABEL if set (user gave the memo a name), otherwise
    the system-generated title stored in ZTITLE (if the column exists), or None.
    """
    if not os.path.isfile(_VM_DB):
        logger.debug("[VoiceMetadata] VoiceMemos.sqlite not found — skipping DB lookup")
        return None

    fragment = _extract_uuid_fragment(filename)
    date_str  = _extract_date_str(filename)

    try:
        # VoiceMemos.sqlite is a WAL-mode CoreData DB; open read-only.
        conn = sqlite3.connect(f"file:{_VM_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Discover available columns (schema varies between macOS versions)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(ZRECORDING)")}

        label_col = "ZCUSTOMLABEL" if "ZCUSTOMLABEL" in cols else None
        title_col  = "ZTITLE"       if "ZTITLE"       in cols else None

        if not label_col and not title_col:
            logger.debug("[VoiceMetadata] Neither ZCUSTOMLABEL nor ZTITLE found in ZRECORDING")
            conn.close()
            return None

        select = ", ".join(c for c in [label_col, title_col] if c)

        # Strategy a: partial UUID match
        if fragment:
            row = conn.execute(
                f"SELECT {select} FROM ZRECORDING WHERE ZUNIQUEID LIKE ? LIMIT 1",
                (f"%{fragment}%",)
            ).fetchone()
            if row:
                name = _best_name(row, label_col, title_col)
                conn.close()
                if name:
                    logger.info(f"[VoiceMetadata] Resolved '{filename}' → '{name}' (UUID match)")
                    return name

        # Strategy b: date-based match (fallback when UUID doesn't match)
        if date_str and "ZDATE" in cols:
            # ZDATE is seconds since 2001-01-01 (CoreData epoch).
            # Parse the filename date and convert to CoreData epoch range.
            ts = _filename_date_to_coredata(date_str)
            if ts is not None:
                row = conn.execute(
                    f"SELECT {select} FROM ZRECORDING WHERE ABS(ZDATE - ?) < 60 LIMIT 1",
                    (ts,)
                ).fetchone()
                if row:
                    name = _best_name(row, label_col, title_col)
                    conn.close()
                    if name:
                        logger.info(f"[VoiceMetadata] Resolved '{filename}' → '{name}' (date match)")
                        return name

        conn.close()

    except Exception as exc:
        logger.warning(f"[VoiceMetadata] DB lookup failed: {exc}")

    return None


def _best_name(row, label_col, title_col) -> str | None:
    """Pick the best non-empty name from a DB row."""
    for col in [label_col, title_col]:
        if col:
            val = row[col]
            if val and val.strip():
                return val.strip()
    return None


# ── Filename parsing helpers ───────────────────────────────────────────────────

# Matches: 20260329 230125-6587917D.qta
#   group 1 = "20260329 230125"  (date+time)
#   group 2 = "6587917D"         (hex fragment / UUID suffix)
_FILENAME_RE = re.compile(
    r"^(\d{8}\s+\d{6})-([0-9A-Fa-f]{6,})",
    re.IGNORECASE
)


def _extract_uuid_fragment(filename: str) -> str | None:
    """Extract the hex UUID fragment from an iCloud Voice Memo filename."""
    base = os.path.splitext(os.path.basename(filename))[0]
    m = _FILENAME_RE.match(base)
    return m.group(2).upper() if m else None


def _extract_date_str(filename: str) -> str | None:
    """Extract the 'YYYYMMDD HHMMSS' date string from the filename."""
    base = os.path.splitext(os.path.basename(filename))[0]
    m = _FILENAME_RE.match(base)
    return m.group(1) if m else None


def _filename_date_to_coredata(date_str: str) -> float | None:
    """Convert '20260329 230125' → seconds since CoreData epoch (2001-01-01)."""
    try:
        from datetime import datetime, timezone
        dt = datetime.strptime(date_str.strip(), "%Y%m%d %H%M%S")
        # CoreData epoch: 2001-01-01 00:00:00 UTC
        coredata_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
        # Assume local time for the filename timestamp
        import calendar
        unix_ts = calendar.timegm(dt.timetuple())  # treat as UTC (close enough for ±60s window)
        coredata_epoch_unix = 978307200            # 2001-01-01 00:00:00 UTC in Unix time
        return float(unix_ts - coredata_epoch_unix)
    except Exception:
        return None


# ── Friendly filename fallback ─────────────────────────────────────────────────

def _friendly_filename(filename: str) -> str | None:
    """Turn '20260329 230125-6587917D.qta' into something slightly nicer.

    If the file has the iCloud auto-generated format, return None so the
    caller can show the raw filename rather than a misleading 'cleaned' name.
    We only return a value when there's genuinely user-readable content.
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    if _FILENAME_RE.match(base):
        # Looks fully machine-generated — don't manufacture a fake friendly name
        return None
    # Has actual words — clean up underscores/hyphens
    return re.sub(r"[_\-]+", " ", base).strip() or None
