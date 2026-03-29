"""
run.py — Entry point.
  Local dev:  python3 run.py
  Production: gunicorn run:app --bind 0.0.0.0:$PORT --timeout 300 --workers 1
"""
from flask import Flask
from config import MAX_UPLOAD_BYTES, PORT, SECRET_KEY, IS_MACOS
import db
import routes
from oauth_client import init_oauth

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.secret_key = SECRET_KEY

# Init DB at module level so gunicorn picks it up without __main__
db.init_db()

# Register Google OAuth (no-op if GOOGLE_CLIENT_ID is not set)
init_oauth(app)

# Register all routes (includes auth middleware)
app.register_blueprint(routes.bp)

# Start iCloud/folder auto-watcher (macOS only, silently skipped elsewhere)
if IS_MACOS:
    import watcher
    watcher.start()

# Global JSON error handlers
@app.errorhandler(Exception)
def handle_error(e):
    import traceback
    from flask import jsonify
    traceback.print_exc()
    return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def handle_404(e):
    from flask import jsonify
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    db.init_db()
    print()
    print("  🎙️  Phonos.ai")
    print("  ──────────────────────────────────────")
    from config import VOICE_MEMOS_DIR, DB_PATH, WATCH_FOLDER
    print(f"  Voice memos:  {VOICE_MEMOS_DIR}")
    print(f"  Database:     {DB_PATH}")
    if IS_MACOS and WATCH_FOLDER:
        print(f"  Watching:     {WATCH_FOLDER}")
    print(f"  Open:         http://localhost:{PORT}")
    print()
    app.run(debug=False, port=PORT)
