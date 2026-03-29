"""
oauth_client.py — Google OAuth singleton using Authlib.

Usage:
  from oauth_client import oauth, init_oauth
  init_oauth(app)          # called once in run.py
  oauth.google             # used in routes.py for authorize_redirect / authorize_access_token
"""
from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def init_oauth(app) -> bool:
    """Register Google OAuth on the Flask app. Returns True if configured."""
    from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    if not GOOGLE_CLIENT_ID:
        return False
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return True
