"""
routes.py — All Flask API routes and the main page.
To add a new endpoint: define a function here and decorate it with @bp.route().
"""
import os
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, send_file

import db
import transcriber
import summarizer
import apple_notes
import chat
from config import VOICE_MEMOS_DIR, AUDIO_EXTENSIONS, APP_PASSWORD, IS_MACOS
from prompts import PROMPT_REGISTRY

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
    import json
    # Strip the transcript block from display — users don't need to see "{transcript}"
    display_prompts = {}
    for key, tpl in PROMPT_REGISTRY.items():
        # Cut off at the transcript divider line so the viewer shows the format/rules only
        cutoff = tpl.find("---\nTRANSCRIPT:")
        display_prompts[key] = tpl[:cutoff].strip() if cutoff != -1 else tpl.strip()
    return render_template("index.html", is_macos=IS_MACOS,
                           prompts_json=json.dumps(display_prompts))


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


@bp.route("/api/audio/<path:filename>")
def serve_audio(filename):
    """Stream the original audio file for in-app playback."""
    try:
        fpath = os.path.join(VOICE_MEMOS_DIR, filename)
        if not os.path.isfile(fpath):
            return jsonify({"error": "File not found"}), 404
        return send_file(fpath, conditional=True)
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

        existing = db.get_memo(filename)

        # Return fully cached result only when: same note_type, no custom instructions, no force flag
        if (existing and existing.get("summary") and existing["note_type"] == note_type
                and not force and not custom_instructions):
            if to_notes and not existing["apple_saved"]:
                title                 = os.path.splitext(filename)[0]
                transcript_note_title = title
                transcript_url = apple_notes.save_transcript_note(
                    transcript_note_title, existing["transcript"],
                    source_filename=filename
                )
                summary_url = apple_notes.save_note(
                    title, existing["summary"], transcript_url=transcript_url,
                    source_filename=filename
                )
                if summary_url and transcript_url:
                    apple_notes.update_transcript_note_with_summary_link(
                        transcript_note_title, existing["transcript"], summary_url, title,
                        source_filename=filename
                    )
                if summary_url:
                    db.mark_apple_saved(filename)
                    existing["apple_saved"] = 1
            return jsonify(existing)

        # Reuse existing transcript if available — transcription is slow and expensive.
        # Only re-transcribe when there is genuinely no transcript yet.
        segments = []
        if existing and existing.get("transcript"):
            transcript = existing["transcript"]
            file_date  = existing["file_date"]
            segments   = existing.get("segments") or []
        else:
            file_date       = datetime.fromtimestamp(os.stat(fpath).st_mtime).isoformat()
            result          = transcriber.transcribe(fpath)
            transcript      = result["text"]
            segments        = result["segments"]

        summary = summarizer.generate(transcript, note_type, custom_instructions)

        saved = False
        if to_notes:
            title                 = os.path.splitext(filename)[0]
            transcript_note_title = title

            # Step 1: create transcript note → get its URL
            transcript_url = apple_notes.save_transcript_note(
                transcript_note_title, transcript,
                source_filename=filename
            )
            # Step 2: create summary note with link → get its URL
            summary_url = apple_notes.save_note(
                title, summary, transcript_url=transcript_url,
                source_filename=filename
            )
            saved = summary_url is not None

            # Step 3: update transcript note to add back-link to summary
            if transcript_url and summary_url:
                apple_notes.update_transcript_note_with_summary_link(
                    transcript_note_title, transcript, summary_url, title,
                    source_filename=filename
                )

        db.save_memo(filename, fpath, file_date, transcript, summary, note_type, saved,
                     segments=segments)

        return jsonify({
            "filename":     filename,
            "filepath":     fpath,
            "file_date":    file_date,
            "transcript":   transcript,
            "segments":     segments,
            "summary":      summary,
            "note_type":    note_type,
            "apple_saved":  int(saved),
            "processed_at": datetime.now().isoformat()
        })

    except Exception as e:
        return _error(e)


# ── Rename ───────────────────────────────────────────────────────────────────

@bp.route("/api/memo/<filename>/rename", methods=["POST"])
def rename_memo(filename):
    """Set a display name for a memo (stored in DB, file on disk is untouched)."""
    try:
        body         = request.json or {}
        display_name = body.get("display_name", "").strip()
        if not display_name:
            return jsonify({"error": "display_name is required"}), 400
        if not db.get_memo(filename):
            return jsonify({"error": "Memo not found"}), 404
        db.rename_memo(filename, display_name)
        return jsonify({"ok": True, "filename": filename, "display_name": display_name})
    except Exception as e:
        return _error(e)


# ── Delete ────────────────────────────────────────────────────────────────────

@bp.route("/api/memo/<filename>", methods=["DELETE"])
def delete_memo(filename):
    """Delete a memo from the DB and remove its file from voice_memos/."""
    try:
        fpath = os.path.join(VOICE_MEMOS_DIR, filename)
        db.delete_memo(filename)
        if os.path.isfile(fpath):
            os.remove(fpath)
        return jsonify({"ok": True, "filename": filename})
    except Exception as e:
        return _error(e)


# ── Series ───────────────────────────────────────────────────────────────────

@bp.route("/api/series", methods=["GET"])
def list_series():
    try:
        return jsonify(db.list_series())
    except Exception as e:
        return _error(e)


@bp.route("/api/series", methods=["POST"])
def create_series():
    try:
        name = (request.json or {}).get("name", "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        series_id = db.create_series(name)
        return jsonify({"ok": True, "id": series_id, "name": name})
    except Exception as e:
        return _error(e)


@bp.route("/api/series/<int:series_id>", methods=["GET"])
def get_series(series_id):
    try:
        s = db.get_series_with_memos(series_id)
        if not s:
            return jsonify({"error": "Series not found"}), 404
        return jsonify(s)
    except Exception as e:
        return _error(e)


@bp.route("/api/memo/<filename>/series", methods=["POST"])
def set_memo_series(filename):
    """Assign or unlink a memo from a series. Pass series_id=null to unlink."""
    try:
        body      = request.json or {}
        series_id = body.get("series_id")   # None → unlink
        if series_id is not None:
            series_id = int(series_id)
        db.set_memo_series(filename, series_id)
        return jsonify({"ok": True, "filename": filename, "series_id": series_id})
    except Exception as e:
        return _error(e)


@bp.route("/api/series/<int:series_id>/diff", methods=["POST"])
def generate_diff(series_id):
    """Generate a 'what changed?' comparison brief for all memos in a series."""
    try:
        s = db.get_series_with_memos(series_id)
        if not s:
            return jsonify({"error": "Series not found"}), 404
        processed = [m for m in s["memos"] if m.get("summary")]
        if len(processed) < 2:
            return jsonify({"error": "Need at least 2 processed meetings to compare."}), 400
        diff = summarizer.generate_diff(s["name"], processed)
        return jsonify({"diff": diff, "series_name": s["name"],
                        "n_meetings": len(processed)})
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


@bp.route("/api/watcher/status")
def watcher_status():
    """Return the current auto-watch state for the UI indicator."""
    if not IS_MACOS:
        return jsonify({"active": False, "folder": None,
                        "last_filename": None, "last_at": None, "total": 0})
    import watcher
    return jsonify(watcher.status())


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
            "display_name": row["display_name"] if row and row.get("display_name") else None,
            "filepath":     fpath,
            "file_date":    datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "file_size_mb": round(stat.st_size / 1024 / 1024, 1),
            "processed":    bool(row and row.get("transcript")),
            "note_type":    row["note_type"] if row else None,
            "apple_saved":  bool(row and row.get("apple_saved")),
            "series_id":    row["series_id"] if row and row.get("series_id") else None,
        })

    memos.sort(key=lambda m: m["file_date"], reverse=True)
    return memos


def _error(exc: Exception, status: int = 500):
    import traceback
    traceback.print_exc()
    return jsonify({"error": str(exc)}), status
