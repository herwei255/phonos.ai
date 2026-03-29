"""
routes.py — All Flask API routes and the main page.
To add a new endpoint: define a function here and decorate it with @bp.route().
"""
import os
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for

import db
import transcriber
import summarizer
import apple_notes
import chat
from config import VOICE_MEMOS_DIR, AUDIO_EXTENSIONS, APP_PASSWORD, IS_MACOS

bp = Blueprint("main", __name__)


# ── Auth middleware ────────────────────────────────────────────────────────────

@bp.before_request
def require_login():
    """Redirect to /login if APP_PASSWORD is set and user is not authenticated."""
    if not APP_PASSWORD:
        return  # Auth disabled — local dev mode
    exempt = {"main.login", "main.logout"}
    if request.endpoint in exempt:
        return
    if not session.get("authenticated"):
        return redirect(url_for("main.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("main.index"))
        return render_template("login.html", error="Incorrect password — try again.")
    return render_template("login.html", error=None)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ── Page ──────────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return render_template("index.html", is_macos=IS_MACOS)


# ── Memo list ─────────────────────────────────────────────────────────────────

@bp.route("/api/memos")
def list_memos():
    """Return all audio files in VOICE_MEMOS_DIR with their DB status."""
    try:
        memos = _scan_memos()
        return jsonify(memos)
    except Exception as e:
        return _error(e)


# ── Single memo detail ────────────────────────────────────────────────────────

@bp.route("/api/memo/<filename>")
def get_memo(filename):
    """Return the DB record for a processed memo."""
    try:
        row = db.get_memo(filename)
        if not row:
            return jsonify({"error": "Not processed yet"}), 404
        return jsonify(row)
    except Exception as e:
        return _error(e)


# ── Process a memo ────────────────────────────────────────────────────────────

@bp.route("/api/process/<filename>", methods=["POST"])
def process_memo(filename):
    """Transcribe and summarise a memo. Skips transcription if already in DB
    with the same note_type (unless force=true is passed).
    """
    try:
        body                 = request.json or {}
        note_type            = body.get("note_type", "standard")
        to_notes             = body.get("add_to_notes", False)
        force                = body.get("force", False)
        custom_instructions  = body.get("custom_instructions", "").strip()

        fpath = os.path.join(VOICE_MEMOS_DIR, filename)
        if not os.path.isfile(fpath):
            return jsonify({"error": "File not found in voice_memos folder"}), 404

        # Return cached result if already processed with same note_type
        existing = db.get_memo(filename)
        if existing and existing["transcript"] and existing["note_type"] == note_type and not force:
            if to_notes and not existing["apple_saved"]:
                title = summarizer.extract_title(existing["summary"], note_type)
                if apple_notes.save_note(title, existing["summary"]):
                    db.mark_apple_saved(filename)
                    existing["apple_saved"] = 1
            return jsonify(existing)

        # Fresh process
        file_date  = datetime.fromtimestamp(os.stat(fpath).st_mtime).isoformat()
        transcript = transcriber.transcribe(fpath)
        summary    = summarizer.generate(transcript, note_type, custom_instructions)

        saved = False
        if to_notes:
            title = summarizer.extract_title(summary, note_type)
            saved = apple_notes.save_note(title, summary)

        db.save_memo(filename, fpath, file_date, transcript, summary, note_type, saved)

        return jsonify({
            "filename":     filename,
            "filepath":     fpath,
            "file_date":    file_date,
            "transcript":   transcript,
            "summary":      summary,
            "note_type":    note_type,
            "apple_saved":  int(saved),
            "processed_at": datetime.now().isoformat()
        })

    except Exception as e:
        return _error(e)


# ── Upload ────────────────────────────────────────────────────────────────────

@bp.route("/api/upload", methods=["POST"])
def upload_memo():
    """Accept a file upload and drop it into VOICE_MEMOS_DIR."""
    try:
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        f = request.files["audio"]
        if not f.filename:
            return jsonify({"error": "No filename"}), 400
        os.makedirs(VOICE_MEMOS_DIR, exist_ok=True)
        f.save(os.path.join(VOICE_MEMOS_DIR, f.filename))
        return jsonify({"ok": True, "filename": f.filename})
    except Exception as e:
        return _error(e)


# ── Chat ─────────────────────────────────────────────────────────────────────

@bp.route("/api/chat", methods=["POST"])
def chat_with_notes():
    """Answer a question grounded in all stored meeting notes."""
    try:
        body     = request.json or {}
        question = body.get("question", "").strip()
        history  = body.get("history", [])
        if not question:
            return jsonify({"error": "No question provided"}), 400
        answer = chat.answer(question, history)
        return jsonify({"answer": answer})
    except Exception as e:
        return _error(e)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scan_memos() -> list[dict]:
    """Scan VOICE_MEMOS_DIR and merge with DB status."""
    if not os.path.isdir(VOICE_MEMOS_DIR):
        return []

    memos = []
    for fname in os.listdir(VOICE_MEMOS_DIR):
        if os.path.splitext(fname)[1].lower() not in AUDIO_EXTENSIONS:
            continue
        fpath = os.path.join(VOICE_MEMOS_DIR, fname)
        stat  = os.stat(fpath)
        row   = db.get_memo(fname)
        memos.append({
            "filename":     fname,
            "filepath":     fpath,
            "file_date":    datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "file_size_mb": round(stat.st_size / 1024 / 1024, 1),
            "processed":    bool(row and row.get("transcript")),
            "note_type":    row["note_type"] if row else None,
            "apple_saved":  bool(row and row.get("apple_saved")),
        })

    memos.sort(key=lambda m: m["file_date"], reverse=True)
    return memos


def _error(exc: Exception, status: int = 500):
    import traceback
    traceback.print_exc()
    return jsonify({"error": str(exc)}), status
