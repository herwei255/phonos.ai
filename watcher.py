"""
watcher.py — iCloud / folder auto-watch for Phonos.ai

Monitors a folder (default: iCloud Voice Memos recordings) for new audio
files. When one appears and is fully written, it is copied into VOICE_MEMOS_DIR
and automatically transcribed + summarised — zero clicks needed.

Usage:
    import watcher
    watcher.start()   # called once at app startup
    watcher.stop()    # called at app shutdown (optional)
    watcher.status()  # returns current state dict for the UI
"""

import logging
import os
import shutil
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Internal state ────────────────────────────────────────────────────────────

_observer   = None
_state      = {
    "active":        False,
    "folder":        None,
    "last_filename": None,
    "last_at":       None,   # ISO timestamp
    "total":         0,      # files processed this session
}
_state_lock = threading.Lock()


def status() -> dict:
    """Return a copy of the current watcher state (safe to serialise as JSON)."""
    with _state_lock:
        return dict(_state)


# ── File handler ──────────────────────────────────────────────────────────────

class _AudioHandler:
    """Minimal watchdog-compatible event handler that avoids the full import
    until watchdog is confirmed available."""

    AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".ogg", ".webm", ".mp4", ".caf", ".aac", ".flac"}

    def __init__(self, dest_dir: str):
        self.dest_dir = dest_dir
        self._seen: set[str] = set()

    # watchdog calls dispatch() → on_created / on_moved
    def dispatch(self, event):
        path = getattr(event, "dest_path", None) or getattr(event, "src_path", "")
        if not event.is_directory and self._is_audio(path):
            if path not in self._seen:
                self._seen.add(path)
                threading.Thread(target=self._handle, args=(path,), daemon=True).start()

    def _is_audio(self, path: str) -> bool:
        _, ext = os.path.splitext(path.lower())
        return ext in self.AUDIO_EXTS

    def _handle(self, src_path: str):
        """Wait for the file to finish writing, copy it, then process it."""
        filename = os.path.basename(src_path)
        logger.info(f"[Watcher] Detected: {filename}")

        # iCloud may create a placeholder (.icloud) before the real file lands.
        # Wait up to 60 s for it to appear and stabilise.
        if not self._wait_for_file(src_path, timeout=60):
            logger.warning(f"[Watcher] Timed out waiting for {filename}")
            return

        dest_path = os.path.join(self.dest_dir, filename)
        if os.path.exists(dest_path):
            logger.info(f"[Watcher] Already in voice_memos, skipping: {filename}")
            return

        try:
            shutil.copy2(src_path, dest_path)
            logger.info(f"[Watcher] Copied {filename} → voice_memos/")
        except Exception as exc:
            logger.error(f"[Watcher] Copy failed for {filename}: {exc}")
            return

        with _state_lock:
            _state["last_filename"] = filename
            _state["last_at"]       = datetime.now().isoformat(timespec="seconds")
            _state["total"]        += 1

        self._process(filename, dest_path)

    def _wait_for_file(self, path: str, timeout: int = 60, interval: float = 1.5) -> bool:
        """Poll until the file exists and its size has been stable for 2 checks."""
        elapsed   = 0.0
        prev_size = -1
        stable    = 0

        while elapsed < timeout:
            time.sleep(interval)
            elapsed += interval
            try:
                size = os.path.getsize(path)
            except OSError:
                continue  # file not yet flushed / iCloud placeholder
            if size == prev_size and size > 0:
                stable += 1
                if stable >= 2:
                    return True
            else:
                stable = 0
            prev_size = size
        return False

    def _process(self, filename: str, fpath: str):
        """Transcribe and summarise the new file directly (no HTTP round-trip)."""
        try:
            import db
            import transcriber as tr
            import summarizer  as sm

            existing = db.get_memo(filename)
            if existing and existing.get("summary"):
                logger.info(f"[Watcher] Already processed: {filename}")
                return

            logger.info(f"[Watcher] Transcribing {filename}…")
            file_date      = datetime.fromtimestamp(os.stat(fpath).st_mtime).isoformat()
            result         = tr.transcribe(fpath)
            transcript     = result["text"]
            segments       = result["segments"]

            logger.info(f"[Watcher] Generating notes for {filename}…")
            summary = sm.generate(transcript, "standard")

            db.save_memo(filename, fpath, file_date, transcript, summary, "standard", False,
                         segments=segments)
            logger.info(f"[Watcher] ✓ Done: {filename}")

        except Exception as exc:
            logger.error(f"[Watcher] Processing failed for {filename}: {exc}")


# ── Public API ────────────────────────────────────────────────────────────────

def start(watch_folder: str | None = None) -> bool:
    """Start the background folder watcher.

    Args:
        watch_folder: Path to monitor. Falls back to config.WATCH_FOLDER.

    Returns:
        True if the watcher started successfully, False otherwise.
    """
    global _observer

    # Resolve folder
    if watch_folder is None:
        from config import WATCH_FOLDER
        watch_folder = WATCH_FOLDER

    if not watch_folder:
        logger.info("[Watcher] No watch folder configured — auto-watch disabled.")
        return False

    watch_folder = os.path.expanduser(watch_folder)

    if not os.path.isdir(watch_folder):
        logger.warning(f"[Watcher] Folder does not exist (yet): {watch_folder}")
        # Don't error out — iCloud folders appear lazily. We'll just not watch.
        return False

    try:
        from watchdog.observers import Observer
        from watchdog.events    import FileSystemEventHandler

        # Wrap our minimal handler in watchdog's base class
        class _WDHandler(FileSystemEventHandler):
            def __init__(self, inner):
                super().__init__()
                self._inner = inner
            def on_created(self, event):
                self._inner.dispatch(event)
            def on_moved(self, event):
                # iCloud sometimes moves the real file into place
                self._inner.dispatch(event)

        from config import VOICE_MEMOS_DIR
        inner   = _AudioHandler(VOICE_MEMOS_DIR)
        handler = _WDHandler(inner)

        _observer = Observer()
        _observer.schedule(handler, watch_folder, recursive=False)
        _observer.start()

        with _state_lock:
            _state["active"] = True
            _state["folder"] = watch_folder

        logger.info(f"[Watcher] Watching: {watch_folder}")
        return True

    except ImportError:
        logger.warning("[Watcher] watchdog not installed — run: pip install watchdog")
        return False
    except Exception as exc:
        logger.error(f"[Watcher] Failed to start: {exc}")
        return False


def stop():
    """Stop the background watcher gracefully."""
    global _observer
    if _observer:
        _observer.stop()
        _observer.join()
        _observer = None
    with _state_lock:
        _state["active"] = False
    logger.info("[Watcher] Stopped.")
