"""
config.py — Central configuration.
All env vars and app-wide constants live here.
Add new settings here; import from other modules.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")

# ── Models ────────────────────────────────────────────────────────────────────
WHISPER_MODEL   = "whisper-large-v3"
SUMMARIZER_MODEL = "deepseek/deepseek-chat"

# ── Paths ─────────────────────────────────────────────────────────────────────
# On Railway: set VOICE_MEMOS_DIR=/data/voice_memos and DB_PATH=/data/memos.db
# so they persist on the mounted volume. Defaults to local paths for dev.
BASE_DIR        = os.path.dirname(__file__)
VOICE_MEMOS_DIR = os.getenv("VOICE_MEMOS_DIR", os.path.join(BASE_DIR, "voice_memos"))
DB_PATH         = os.getenv("DB_PATH", os.path.join(BASE_DIR, "memos.db"))

# ── Audio ─────────────────────────────────────────────────────────────────────
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".webm", ".mp4", ".caf", ".aac", ".flac"}
GROQ_MAX_BYTES   = 20 * 1024 * 1024   # 20 MB — safely under Groq's 25 MB limit

# ── Apple Notes ───────────────────────────────────────────────────────────────
APPLE_NOTES_FOLDER = "Voice Notes"

# ── Flask ─────────────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
PORT             = int(os.getenv("PORT", 5000))

# ── Platform ──────────────────────────────────────────────────────────────────
import sys
IS_MACOS = sys.platform == "darwin"   # Apple Notes only works on macOS

# ── Auth ──────────────────────────────────────────────────────────────────────
# Set APP_PASSWORD in env to enable password protection.
# Leave empty (or unset) to run without auth — useful for local dev.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
# SECRET_KEY signs Flask session cookies. Always set this in production.
# A random key is generated per process if not set (clears sessions on restart).
SECRET_KEY   = os.getenv("SECRET_KEY", os.urandom(32).hex())
