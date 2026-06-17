"""Flask web server — accepts URLs from the iOS Shortcut or Safari bookmarklet."""

import json
import os
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, redirect, request, session, url_for
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from werkzeug.middleware.proxy_fix import ProxyFix

import converter

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))
# Trust the X-Forwarded-Proto header set by Render/Fly.io's HTTPS proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = Path("credentials.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_google_flow(redirect_uri):
    """Build an OAuth Flow from credentials.json or the GOOGLE_CREDENTIALS_JSON env var."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        client_config = json.loads(creds_json)
        return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)
    if CREDENTIALS_FILE.exists():
        return Flow.from_client_secrets_file(str(CREDENTIALS_FILE), scopes=SCOPES, redirect_uri=redirect_uri)
    raise FileNotFoundError(
        "No Google credentials found. Set GOOGLE_CREDENTIALS_JSON env var "
        "or place credentials.json in the app directory. See README.md."
    )


def require_api_token(f):
    """Decorator: enforce Bearer token auth when API_TOKEN env var is set."""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_token = os.environ.get("API_TOKEN")
        if api_token:
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if token != api_token:
                return jsonify({"ok": False, "error": "Unauthorized — check your API token."}), 401
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Send to Kobo</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 520px; margin: 40px auto;
         padding: 0 20px; color: #222; background: #fafafa; }}
  h1 {{ font-size: 1.4em; }}
  input[type=url] {{ width: 100%; box-sizing: border-box; padding: 10px; font-size: 1em;
                     border: 1px solid #ccc; border-radius: 6px; margin: 8px 0; }}
  button {{ background: #2c5fcf; color: #fff; border: none; padding: 10px 22px;
            font-size: 1em; border-radius: 6px; cursor: pointer; }}
  button:hover {{ background: #1a4bbf; }}
  .ok  {{ margin-top:14px; padding:12px; border-radius:6px; background:#eef4ff; color:#1a3a8a; }}
  .err {{ margin-top:14px; padding:12px; border-radius:6px; background:#fee; color:#900; }}
  .note {{ font-size:0.85em; color:#666; margin-top:24px; border-top:1px solid #ddd; padding-top:14px; }}
  code {{ background:#f0f0f0; padding:2px 5px; border-radius:3px; font-size:0.9em; word-break:break-all; }}
  a {{ color:#2c5fcf; }}
</style>
</head>
<body>
<h1>&#128218; Send to Kobo</h1>
{body}
</body>
</html>
"""


def _page(body):
    return _PAGE.format(body=body)


@app.route("/")
def index():
    authed = converter.is_authenticated()
    config = converter.load_config()
    folder_id = config.get("folder_id", "")
    host = request.host_url.rstrip("/")
    api_token_set = bool(os.environ.get("API_TOKEN"))

    auth_line = (
        '<p style="color:#080">&#10003; Authenticated with Google Drive</p>'
        if authed else
        '<p style="color:#c00">&#9888; Not signed in to Google Drive &mdash; '
        '<a href="/auth">Sign in now</a></p>'
    )
    folder_line = (
        f'<p>Default Drive folder: <code>{folder_id}</code></p>'
        if folder_id else
        '<p style="color:#c00">&#9888; No default Drive folder set. '
        'Set <code>DRIVE_FOLDER_ID</code> in your environment, or pass '
        '<code>?folder_id=ID</code> on each request.</p>'
    )

    convert_url = f"{host}/convert"
    bookmarklet = (
        f"javascript:(function(){{fetch('{convert_url}',"
        "{{method:'POST',headers:{{'Content-Type':'application/json'"
        + (f",'Authorization':'Bearer '+prompt('API token?')" if api_token_set else "")
        + f"}},body:JSON.stringify({{url:window.location.href}})}}))"
        ".then(r=>r.json()).then(d=>alert(d.ok?'\\u2713 Sent: '+d.title:'\\u2717 '+d.error))"
        ".catch(e=>alert('Error: '+e))})()"
    )

    body = f"""
    {auth_line}
    {folder_line}
    <form id="form">
      <label for="url"><strong>Article URL</strong></label><br>
      <input type="url" id="url" name="url" placeholder="https://example.com/article" required>
      <br><button type="submit">Convert &amp; Send to Kobo</button>
    </form>
    <div id="result"></div>
    <div class="note">
      <strong>iOS Shortcut URL:</strong> <code>{convert_url}</code><br><br>
      <strong>Safari bookmarklet:</strong><br>
      <code>{bookmarklet}</code>
    </div>
    <script>
    document.getElementById('form').addEventListener('submit', async function(e) {{
      e.preventDefault();
      const url = document.getElementById('url').value;
      const res = document.getElementById('result');
      res.innerHTML = '<p>Converting&hellip; (may take 15&ndash;30 seconds)</p>';
      const headers = {{'Content-Type': 'application/json'}};
      {"const t = prompt('Enter API token:'); if(t) headers['Authorization'] = 'Bearer ' + t;" if api_token_set else ""}
      try {{
        const r = await fetch('/convert', {{
          method: 'POST', headers,
          body: JSON.stringify({{url}})
        }});
        const d = await r.json();
        if (d.ok) {{
          res.innerHTML = `<div class="ok">&#10003; Sent to Kobo: <strong>${{d.title}}</strong>
            (${{d.size_kb}} KB, ${{d.n_images}} image(s))</div>`;
        }} else {{
          res.innerHTML = `<div class="err">&#10007; ${{d.error}}</div>`;
        }}
      }} catch(err) {{
        res.innerHTML = `<div class="err">&#10007; Request failed: ${{err}}</div>`;
      }}
    }});
    </script>
    """
    return _page(body)


# ---------------------------------------------------------------------------
# Convert API  (called by iOS Shortcut and bookmarklet)
# ---------------------------------------------------------------------------

@app.route("/convert", methods=["POST"])
@require_api_token
def convert_endpoint():
    if not converter.is_authenticated():
        return jsonify({
            "ok": False,
            "error": f"Not authenticated with Google Drive. Visit {request.host_url}auth to sign in.",
        }), 401

    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or request.form.get("url", "")).strip()
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400

    config = converter.load_config()
    folder_id = (
        data.get("folder_id")
        or config.get("folder_id")
        or os.environ.get("DRIVE_FOLDER_ID")
    )

    try:
        result = converter.convert_and_upload(url, folder_id=folder_id)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Google OAuth  — visit /auth from any browser to sign in once
# ---------------------------------------------------------------------------

@app.route("/auth")
def auth_start():
    try:
        flow = _get_google_flow(url_for("auth_callback", _external=True))
    except FileNotFoundError as e:
        return _page(f"<p style='color:#c00'>&#10007; {e}</p>"), 500

    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    session["oauth_state"] = state
    # PKCE: newer google-auth-oauthlib generates a code_verifier; persist it so
    # the callback can send it to Google during token exchange.
    if getattr(flow, "code_verifier", None):
        session["oauth_code_verifier"] = flow.code_verifier
    return redirect(auth_url)


@app.route("/auth/callback")
def auth_callback():
    state = session.get("oauth_state")
    if not state:
        return _page("<p style='color:#c00'>Session state missing. <a href='/auth'>Try again</a>.</p>"), 400

    try:
        flow = _get_google_flow(url_for("auth_callback", _external=True))
        # Restore the PKCE code verifier if one was generated during /auth
        code_verifier = session.get("oauth_code_verifier")
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.url, state=state)

        converter.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(converter.TOKEN_PATH, "w") as f:
            f.write(flow.credentials.to_json())
    except Exception as e:
        import traceback
        tb = traceback.format_exc().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return _page(
            f"<p style='color:#c00'>OAuth error: {e}</p>"
            f"<pre style='font-size:0.75em;overflow:auto'>{tb}</pre>"
            "<p><a href='/auth'>Try again</a></p>"
        ), 500

    return _page(
        "<div class='ok'>&#10003; Signed in to Google Drive! "
        "Your iPhone and iPad are now ready to send articles.</div>"
        "<p><a href='/'>&#8592; Back to home</a></p>"
    )


# ---------------------------------------------------------------------------
# Status — useful for Shortcut health-check
# ---------------------------------------------------------------------------

@app.route("/status")
def status():
    config = converter.load_config()
    return jsonify({
        "ok": True,
        "authenticated": converter.is_authenticated(),
        "folder_id": config.get("folder_id") or os.environ.get("DRIVE_FOLDER_ID"),
    })


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Send to Kobo server running at http://localhost:{port}/")
    print(f"  Open that URL in a browser on this machine to sign in to Google Drive.\n")
    app.run(host=host, port=port, debug=False)
