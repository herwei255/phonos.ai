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

    AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".ogg", ".webm", ".mp4", ".caf", ".aac", ".flac", ".qta"}

    def __init__(self, dest_dir: str):
        self.dest_dir = dest_dir
        self._seen: set[str] = set()

    # watchdog calls dispatch() → on_created / on_moved
    def dispatch(self, event):
        path = getattr(event, "dest_path", None) or getattr(event, "src_path", "")
        if event.is_directory:
            return

        # iCloud syncs from iPhone arrive as invisible placeholders first:
        #   .Recording.m4a.icloud  →  real file not yet downloaded
        # Detect these and trigger the download so the real .m4a appears.
        if os.path.basename(path).startswith(".") and path.endswith(".icloud"):
            self._trigger_icloud_download(path)
            return

        if self._is_audio(path):
            if path not in self._seen:
                self._seen.add(path)
                threading.Thread(target=self._handle, args=(path,), daemon=True).start()

    def _trigger_icloud_download(self, icloud_path: str):
        """Call brctl download to force iCloud to pull down a placeholder file.

        iCloud placeholder naming: .Recording.m4a.icloud
        Real file path:             Recording.m4a   (same dir, no dot, no .icloud)
        """
        import subprocess
        basename  = os.path.basename(icloud_path)           # .Recording.m4a.icloud
        real_name = basename[1:][:-len(".icloud")]           # Recording.m4a
        real_path = os.path.join(os.path.dirname(icloud_path), real_name)
        logger.info(f"[Watcher] iCloud placeholder detected → triggering download: {real_name}")
        try:
            subprocess.run(["brctl", "download", real_path],
                           capture_output=True, timeout=10)
        except Exception as exc:
            logger.warning(f"[Watcher] brctl download failed: {exc}")

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
            import voice_memo_metadata as vmm

            LOCAL_USER_ID = 1  # Watcher only runs in single-user macOS mode
            existing = db.get_memo(filename, LOCAL_USER_ID)
            if existing and existing.get("summary"):
                logger.info(f"[Watcher] Already processed: {filename}")
                return

            # Resolve human-readable display name from VoiceMemos.sqlite
            display_name = vmm.get_display_name(filename)
            if display_name:
                logger.info(f"[Watcher] Display name: '{display_name}'")

            logger.info(f"[Watcher] Transcribing {filename}…")
            file_date      = datetime.fromtimestamp(os.stat(fpath).st_mtime).isoformat()
            result         = tr.transcribe(fpath)
            transcript     = result["text"]
            segments       = result["segments"]

            logger.info(f"[Watcher] Generating notes for {filename}…")
            summary = sm.generate(transcript, "general")

            # Use AI-extracted title as display name if VMM lookup didn't find one
            if not display_name:
                display_name = sm.extract_title(summary, "general")
                logger.info(f"[Watcher] AI title: '{display_name}'")

            db.save_memo(filename, fpath, file_date, transcript, summary, "general", False,
                         user_id=LOCAL_USER_ID, segments=segments, display_name=display_name)

            from config import AUDIO_KEEP_MAX_MB
            if AUDIO_KEEP_MAX_MB > 0:
                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                if size_mb > AUDIO_KEEP_MAX_MB:
                    os.remove(fpath)
                    logger.info(f"[Watcher] Deleted audio (>{AUDIO_KEEP_MAX_MB} MB): {filename}")

            logger.info(f"[Watcher] ✓ Done: {filename}")

        except Exception as exc:
            logger.error(f"[Watcher] Processing failed for {filename}: {exc}")


# ── Public API ────────────────────────────────────────────────────────────────

POLL_INTERVAL = 20   # seconds between folder scans (backup for missed FSEvents)


def _polling_loop(watch_folder: str, handler: "_AudioHandler") -> None:
    """Scan the watch folder every POLL_INTERVAL seconds.

    This is the primary detection mechanism for iPhone recordings synced via
    iCloud. FSEvents (used by watchdog) often misses creation events in
    iCloud-managed Group Containers folders, so we poll as a reliable fallback.

    For each scan:
      • Hidden .icloud placeholders  → call brctl download to pull the real file
      • Real audio files not yet seen → queue for copy + process
    """
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            for entry in os.scandir(watch_folder):
                name = entry.name
                # iCloud placeholder: .Recording.m4a.icloud
                if name.startswith(".") and name.endswith(".icloud"):
                    handler._trigger_icloud_download(entry.path)
                # Real audio file not yet queued
                elif handler._is_audio(entry.path) and entry.path not in handler._seen:
                    handler._seen.add(entry.path)
                    threading.Thread(
                        target=handler._handle, args=(entry.path,), daemon=True
                    ).start()
        except Exception as exc:
            logger.warning(f"[Watcher] Poll error: {exc}")


def start(watch_folder: str | None = None) -> bool:
    """Start the background folder watcher.

    Runs two mechanisms in parallel:
      1. watchdog FSEvents observer — catches macOS-local recordings immediately.
      2. Polling thread every {POLL_INTERVAL}s — reliably catches iPhone recordings
         synced via iCloud (FSEvents misses these in Group Containers folders).

    Args:
        watch_folder: Path to monitor. Falls back to config.WATCH_FOLDER.

    Returns:
        True if at least the polling thread started, False on hard failure.
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
        logger.warning(f"[Watcher] Folder does not exist: {watch_folder}")
        return False

    from config import VOICE_MEMOS_DIR
    inner = _AudioHandler(VOICE_MEMOS_DIR)

    # ── 1. Polling thread (primary for iCloud) ────────────────────────────────
    poll_thread = threading.Thread(
        target=_polling_loop, args=(watch_folder, inner), daemon=True
    )
    poll_thread.start()
    logger.info(f"[Watcher] Polling every {POLL_INTERVAL}s: {watch_folder}")

    # ── 2. watchdog observer (fast path for local recordings) ─────────────────
    try:
        from watchdog.observers import Observer
        from watchdog.events    import FileSystemEventHandler

        class _WDHandler(FileSystemEventHandler):
            def __init__(self, handler):
                super().__init__()
                self._h = handler
            def on_created(self, event):
                self._h.dispatch(event)
            def on_moved(self, event):
                self._h.dispatch(event)

        _observer = Observer()
        _observer.schedule(_WDHandler(inner), watch_folder, recursive=False)
        _observer.start()
        logger.info(f"[Watcher] FSEvents observer active: {watch_folder}")

    except ImportError:
        logger.warning("[Watcher] watchdog not installed — FSEvents disabled, polling only.")
    except Exception as exc:
        logger.warning(f"[Watcher] FSEvents observer failed ({exc}) — polling only.")

    with _state_lock:
        _state["active"] = True
        _state["folder"] = watch_folder

    return True


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
