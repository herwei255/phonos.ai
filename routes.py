"""
routes.py — All Flask API routes and the main page.
To add a new endpoint: define a function here and decorate it with @bp.route().
"""
import os
from datetime import datetime
from flask import (Blueprint, request, jsonify, render_template,
                   session, redirect, url_for, send_file)

import db
import transcriber
import summarizer
import apple_notes
import chat
from config import (VOICE_MEMOS_DIR, AUDIO_EXTENSIONS,
                    APP_PASSWORD, GOOGLE_CLIENT_ID, IS_MACOS,
                    AUDIO_KEEP_MAX_MB)
from prompts import PROMPT_REGISTRY

bp = Blueprint("main", __name__)

# Endpoints that don't require authentication
_AUTH_EXEMPT = {
    "main.login", "main.logout",
    "main.auth_google", "main.auth_callback",
    "main.home", "static",
}


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _uid() -> int:
    """Return the current user's DB id (always set after require_login passes)."""
    return session["user_id"]


def _user_dir() -> str:
    """Return the voice memos folder for the current user.

    - Password / single-user mode (no GOOGLE_CLIENT_ID): flat VOICE_MEMOS_DIR,
      same as before the multi-user rewrite — existing files stay untouched.
    - Google OAuth / multi-user mode: VOICE_MEMOS_DIR/<user_id>/
    """
    if not GOOGLE_CLIENT_ID:
        os.makedirs(VOICE_MEMOS_DIR, exist_ok=True)
        return VOICE_MEMOS_DIR
    d = os.path.join(VOICE_MEMOS_DIR, str(_uid()))
    os.makedirs(d, exist_ok=True)
    return d


# ── Auth middleware ────────────────────────────────────────────────────────────

@bp.before_request
def require_login():
    if request.endpoint in _AUTH_EXEMPT:
        return
    if not session.get("user_id"):
        return redirect(url_for("main.login"))


# ── Login / logout ────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET", "POST"])
def login():
    # Already logged in
    if session.get("user_id"):
        return redirect(url_for("main.index"))

    if GOOGLE_CLIENT_ID:
        # Google OAuth mode — just show the button
        return render_template("login.html", use_google=True, error=None)

    # Password mode
    if not APP_PASSWORD:
        # Auth disabled entirely
        session["user_id"] = 1
        return redirect(url_for("main.index"))

    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["user_id"] = 1
            return redirect(url_for("main.index"))
        return render_template("login.html", use_google=False,
                               error="Incorrect password — try again.")
    return render_template("login.html", use_google=False, error=None)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ── Google OAuth ──────────────────────────────────────────────────────────────

@bp.route("/auth/google")
def auth_google():
    from oauth_client import oauth
    redirect_uri = url_for("main.auth_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@bp.route("/auth/google/callback")
def auth_callback():
    from oauth_client import oauth
    token    = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or {}
    user = db.get_or_create_user(
        google_id=userinfo.get("sub", ""),
        email=userinfo.get("email", ""),
        name=userinfo.get("name"),
        picture=userinfo.get("picture"),
    )
    session["user_id"]    = user["id"]
    session["user_name"]  = user["name"] or user["email"]
    session["user_email"] = user["email"]
    session["user_pic"]   = user.get("picture") or ""
    return redirect(url_for("main.index"))


# ── Pages ─────────────────────────────────────────────────────────────────────

@bp.route("/home")
def home():
    return render_template("home.html")


@bp.route("/")
def index():
    import json
    display_prompts = {}
    for key, tpl in PROMPT_REGISTRY.items():
        cutoff = tpl.find("---\nTRANSCRIPT:")
        display_prompts[key] = tpl[:cutoff].strip() if cutoff != -1 else tpl.strip()

    # Pass user info to template for the top-bar profile display
    user = db.get_user(_uid()) or {}
    return render_template(
        "index.html",
        is_macos=IS_MACOS,
        prompts_json=json.dumps(display_prompts),
        user_name=session.get("user_name") or user.get("name") or "You",
        user_email=session.get("user_email") or user.get("email") or "",
        user_pic=session.get("user_pic") or user.get("picture") or "",
    )


# ── Memo list ─────────────────────────────────────────────────────────────────

@bp.route("/api/memos")
def list_memos():
    try:
        return jsonify(_scan_memos())
    except Exception as e:
        return _error(e)


# ── Single memo detail ────────────────────────────────────────────────────────

@bp.route("/api/memo/<filename>")
def get_memo(filename):
    try:
        row = db.get_memo(filename, _uid())
        if not row:
            return jsonify({"error": "Not processed yet"}), 404
        return jsonify(row)
    except Exception as e:
        return _error(e)


@bp.route("/api/audio/<path:filename>")
def serve_audio(filename):
    try:
        fpath = os.path.join(_user_dir(), filename)
        if not os.path.isfile(fpath):
            return jsonify({"error": "File not found"}), 404
        return send_file(fpath, conditional=True)
    except Exception as e:
        return _error(e)


# ── Process a memo ────────────────────────────────────────────────────────────

@bp.route("/api/process/<filename>", methods=["POST"])
def process_memo(filename):
    try:
        uid                  = _uid()
        body                 = request.json or {}
        note_type            = body.get("note_type", "general")
        to_notes             = body.get("add_to_notes", False)
        force                = body.get("force", False)
        custom_instructions  = body.get("custom_instructions", "").strip()

        fpath = os.path.join(_user_dir(), filename)
        if not os.path.isfile(fpath):
            return jsonify({"error": "File not found in voice_memos folder"}), 404

        existing = db.get_memo(filename, uid)

        if (existing and existing.get("summary") and existing["note_type"] == note_type
                and not force and not custom_instructions):
            if not existing.get("display_name"):
                auto_title = summarizer.extract_title(existing["summary"], note_type)
                db.rename_memo(filename, auto_title, uid)
                existing["display_name"] = auto_title
            if to_notes:
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
                    db.mark_apple_saved(filename, uid)
                    existing["apple_saved"] = 1
            return jsonify(existing)

        segments = []
        if existing and existing.get("transcript"):
            transcript = existing["transcript"]
            file_date  = existing["file_date"]
            segments   = existing.get("segments") or []
        else:
            file_date  = datetime.fromtimestamp(os.stat(fpath).st_mtime).isoformat()
            result     = transcriber.transcribe(fpath)
            transcript = result["text"]
            segments   = result["segments"]

        summary = summarizer.generate(transcript, note_type, custom_instructions)

        existing_display = existing.get("display_name") if existing else None
        auto_title = existing_display or summarizer.extract_title(summary, note_type)

        saved = False
        if to_notes:
            title                 = os.path.splitext(filename)[0]
            transcript_note_title = title
            transcript_url = apple_notes.save_transcript_note(
                transcript_note_title, transcript, source_filename=filename
            )
            summary_url = apple_notes.save_note(
                title, summary, transcript_url=transcript_url, source_filename=filename
            )
            saved = summary_url is not None
            if transcript_url and summary_url:
                apple_notes.update_transcript_note_with_summary_link(
                    transcript_note_title, transcript, summary_url, title,
                    source_filename=filename
                )

        db.save_memo(filename, fpath, file_date, transcript, summary, note_type, saved,
                     user_id=uid, segments=segments, display_name=auto_title)

        _maybe_delete_audio(fpath)

        return jsonify({
            "filename":     filename,
            "display_name": auto_title,
            "filepath":     fpath,
            "file_date":    file_date,
            "transcript":   transcript,
            "segments":     segments,
            "summary":      summary,
            "note_type":    note_type,
            "apple_saved":  int(saved),
            "processed_at": datetime.now().isoformat(),
            "file_exists":  os.path.isfile(fpath),
        })

    except Exception as e:
        return _error(e)


# ── Rename ────────────────────────────────────────────────────────────────────

@bp.route("/api/memo/<filename>/rename", methods=["POST"])
def rename_memo(filename):
    try:
        uid          = _uid()
        body         = request.json or {}
        display_name = body.get("display_name", "").strip()
        if not display_name:
            return jsonify({"error": "display_name is required"}), 400
        if not db.get_memo(filename, uid):
            return jsonify({"error": "Memo not found"}), 404
        db.rename_memo(filename, display_name, uid)
        return jsonify({"ok": True, "filename": filename, "display_name": display_name})
    except Exception as e:
        return _error(e)


# ── Delete ────────────────────────────────────────────────────────────────────

@bp.route("/api/memo/<filename>", methods=["DELETE"])
def delete_memo(filename):
    try:
        uid   = _uid()
        fpath = os.path.join(_user_dir(), filename)
        db.delete_memo(filename, uid)
        if os.path.isfile(fpath):
            os.remove(fpath)
        return jsonify({"ok": True, "filename": filename})
    except Exception as e:
        return _error(e)


# ── Series ────────────────────────────────────────────────────────────────────

@bp.route("/api/series", methods=["GET"])
def list_series():
    try:
        return jsonify(db.list_series(_uid()))
    except Exception as e:
        return _error(e)


@bp.route("/api/series", methods=["POST"])
def create_series():
    try:
        name = (request.json or {}).get("name", "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        series_id = db.create_series(name, _uid())
        return jsonify({"ok": True, "id": series_id, "name": name})
    except Exception as e:
        return _error(e)


@bp.route("/api/series/<int:series_id>", methods=["GET"])
def get_series(series_id):
    try:
        s = db.get_series_with_memos(series_id, _uid())
        if not s:
            return jsonify({"error": "Series not found"}), 404
        return jsonify(s)
    except Exception as e:
        return _error(e)


@bp.route("/api/memo/<filename>/series", methods=["POST"])
def set_memo_series(filename):
    try:
        body      = request.json or {}
        series_id = body.get("series_id")
        if series_id is not None:
            series_id = int(series_id)
        db.set_memo_series(filename, series_id, _uid())
        return jsonify({"ok": True, "filename": filename, "series_id": series_id})
    except Exception as e:
        return _error(e)


@bp.route("/api/series/<int:series_id>/diff", methods=["POST"])
def generate_diff(series_id):
    try:
        s = db.get_series_with_memos(series_id, _uid())
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
    try:
        uid = _uid()
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        f = request.files["audio"]
        if not f.filename:
            return jsonify({"error": "No filename"}), 400

        dest_dir = _user_dir()
        dest     = os.path.join(dest_dir, f.filename)
        f.save(dest)

        display_name = None
        if IS_MACOS:
            try:
                import voice_memo_metadata as vmm
                display_name = vmm.get_display_name(f.filename)
            except Exception:
                pass

        if display_name:
            try:
                conn_inner = db._connect()
                conn_inner.execute("""
                    INSERT INTO memos (user_id, filename, filepath, display_name)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, filename) DO UPDATE SET
                        display_name = COALESCE(excluded.display_name, memos.display_name)
                """, (uid, f.filename, dest, display_name))
                conn_inner.commit()
                conn_inner.close()
            except Exception:
                pass

        return jsonify({"ok": True, "filename": f.filename, "display_name": display_name})
    except Exception as e:
        return _error(e)


# ── Chat ──────────────────────────────────────────────────────────────────────

@bp.route("/api/chat/history")
def get_chat_history():
    try:
        return jsonify(db.get_chat_history(_uid()))
    except Exception as e:
        return _error(e)


@bp.route("/api/chat/clear", methods=["DELETE"])
def clear_chat_history():
    try:
        db.clear_chat_history(_uid())
        return jsonify({"ok": True})
    except Exception as e:
        return _error(e)


@bp.route("/api/chat", methods=["POST"])
def chat_with_notes():
    try:
        uid      = _uid()
        body     = request.json or {}
        question = body.get("question", "").strip()
        if not question:
            return jsonify({"error": "No question provided"}), 400

        history = [
            {"role": m["role"], "content": m["content"]}
            for m in db.get_chat_history(uid)
        ]

        db.append_chat_message("user", question, uid)

        answer = chat.answer(question, history, user_id=uid)

        db.append_chat_message("assistant", answer, uid)

        return jsonify({"answer": answer})
    except Exception as e:
        return _error(e)


@bp.route("/api/watcher/status")
def watcher_status():
    if not IS_MACOS:
        return jsonify({"active": False, "folder": None,
                        "last_filename": None, "last_at": None, "total": 0})
    import watcher
    return jsonify(watcher.status())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _scan_memos() -> list[dict]:
    """Return all memos for the current user.

    Merges two sources so processed memos always appear even if audio was deleted:
      1. Audio files on disk (may not be processed yet)
      2. DB records (may have had their audio deleted post-transcription)
    Each entry carries `file_exists: bool` so the UI can hide the player when False.
    """
    uid      = _uid()
    base_dir = _user_dir()
    seen     = set()
    memos    = []

    # ── Pass 1: files on disk ──────────────────────────────────────────────────
    if os.path.isdir(base_dir):
        for fname in os.listdir(base_dir):
            if os.path.splitext(fname)[1].lower() not in AUDIO_EXTENSIONS:
                continue
            fpath = os.path.join(base_dir, fname)
            stat  = os.stat(fpath)
            row   = db.get_memo(fname, uid)
            seen.add(fname)

            display_name = row["display_name"] if row and row.get("display_name") else None
            if not display_name and row and row.get("summary"):
                try:
                    display_name = summarizer.extract_title(
                        row["summary"], row.get("note_type") or "general"
                    )
                    db.rename_memo(fname, display_name, uid)
                except Exception:
                    display_name = None

            memos.append({
                "filename":     fname,
                "display_name": display_name,
                "filepath":     fpath,
                "file_date":    datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "file_size_mb": round(stat.st_size / 1024 / 1024, 1),
                "file_exists":  True,
                "processed":    bool(row and row.get("transcript")),
                "note_type":    row["note_type"] if row else None,
                "apple_saved":  bool(row and row.get("apple_saved")),
                "series_id":    row["series_id"] if row and row.get("series_id") else None,
            })

    # ── Pass 2: DB records whose audio was deleted post-transcription ──────────
    for row in db.list_memos(uid):
        fname = row["filename"]
        if fname in seen or not row.get("transcript"):
            continue  # already listed from disk, or never processed

        display_name = row.get("display_name")
        if not display_name and row.get("summary"):
            try:
                display_name = summarizer.extract_title(
                    row["summary"], row.get("note_type") or "general"
                )
                db.rename_memo(fname, display_name, uid)
            except Exception:
                display_name = None

        memos.append({
            "filename":     fname,
            "display_name": display_name,
            "filepath":     row.get("filepath", ""),
            "file_date":    row.get("file_date") or row.get("processed_at") or "",
            "file_size_mb": 0,
            "file_exists":  False,
            "processed":    True,
            "note_type":    row.get("note_type"),
            "apple_saved":  bool(row.get("apple_saved")),
            "series_id":    row.get("series_id"),
        })

    memos.sort(key=lambda m: m["file_date"], reverse=True)
    return memos


def _maybe_delete_audio(fpath: str) -> bool:
    """Delete audio file if it exceeds AUDIO_KEEP_MAX_MB. Returns True if deleted.

    Set AUDIO_KEEP_MAX_MB=0 in .env to keep all files regardless of size.
    """
    if AUDIO_KEEP_MAX_MB <= 0 or not os.path.isfile(fpath):
        return False
    size_mb = os.path.getsize(fpath) / (1024 * 1024)
    if size_mb > AUDIO_KEEP_MAX_MB:
        os.remove(fpath)
        return True
    return False


def _error(exc: Exception, status: int = 500):
    import traceback
    traceback.print_exc()
    return jsonify({"error": str(exc)}), status
