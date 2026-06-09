"""Flask web server — accepts URLs from the iOS Shortcut or Safari bookmarklet."""

import os
import threading
from pathlib import Path

from flask import Flask, jsonify, redirect, request, session, url_for
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

import converter

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = Path("credentials.json")

# Jobs dict: job_id -> status dict (in-memory, fine for single-user home server)
_jobs: dict = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_BASE_HTML = """\
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
  .status {{ margin-top: 16px; padding: 12px; border-radius: 6px;
             background: {status_bg}; color: {status_fg}; }}
  .note {{ font-size: 0.85em; color: #666; margin-top: 24px; border-top: 1px solid #ddd;
           padding-top: 14px; }}
  a {{ color: #2c5fcf; }}
</style>
</head>
<body>
<h1>📖 Send to Kobo</h1>
{body}
</body>
</html>
"""


def _page(body, status_bg="#eef4ff", status_fg="#1a3a8a"):
    return _BASE_HTML.format(body=body, status_bg=status_bg, status_fg=status_fg)


@app.route("/")
def index():
    authed = converter.is_authenticated()
    config = converter.load_config()
    folder_id = config.get("folder_id", "")

    auth_section = (
        '<p style="color:#c00">⚠️ Not authenticated with Google Drive. '
        '<a href="/auth">Sign in now</a></p>'
        if not authed
        else '<p style="color:#080">✓ Authenticated with Google Drive</p>'
    )

    folder_section = (
        f'<p>Default folder ID: <code>{folder_id}</code></p>'
        if folder_id
        else '<p style="color:#c00">⚠️ No default Drive folder set. '
             'Add <code>?folder_id=YOUR_ID</code> to convert requests, '
             'or set one via the CLI: <code>python send_to_kobo.py config --folder-id ID</code></p>'
    )

    body = f"""
    {auth_section}
    {folder_section}
    <form id="form">
      <label for="url"><strong>Article URL</strong></label><br>
      <input type="url" id="url" name="url" placeholder="https://example.com/article" required>
      <br><button type="submit">Convert &amp; Send to Kobo</button>
    </form>
    <div id="result"></div>
    <div class="note">
      <strong>iOS Shortcut:</strong> set the shortcut URL to
      <code>{request.host_url}convert</code><br><br>
      <strong>Safari bookmarklet JS:</strong><br>
      <code>javascript:(function(){{fetch('{request.host_url}convert',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{url:window.location.href}})}})
      .then(r=>r.json()).then(d=>alert(d.ok?'Sent: '+d.title:d.error))}})()</code>
    </div>
    <script>
    document.getElementById('form').addEventListener('submit', async function(e) {{
      e.preventDefault();
      const url = document.getElementById('url').value;
      const res = document.getElementById('result');
      res.innerHTML = '<p>Converting… (this may take 15-30 seconds)</p>';
      try {{
        const r = await fetch('/convert', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{url}})
        }});
        const d = await r.json();
        if (d.ok) {{
          res.innerHTML = `<div class="status">✓ Sent to Kobo: <strong>${{d.title}}</strong>
            (${{d.size_kb}} KB, ${{d.n_images}} image(s))</div>`;
        }} else {{
          res.innerHTML = `<div class="status" style="background:#fee;color:#900">
            ✗ ${{d.error}}</div>`;
        }}
      }} catch(err) {{
        res.innerHTML = `<div class="status" style="background:#fee;color:#900">
          ✗ Request failed: ${{err}}</div>`;
      }}
    }});
    </script>
    """
    return _page(body)


# ---------------------------------------------------------------------------
# Convert API  (called by iOS Shortcut and bookmarklet)
# ---------------------------------------------------------------------------

@app.route("/convert", methods=["POST"])
def convert_endpoint():
    if not converter.is_authenticated():
        return jsonify({
            "ok": False,
            "error": f"Not authenticated. Open {request.host_url} on the server machine and sign in.",
        }), 401

    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or request.form.get("url", "")).strip()
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400

    config = converter.load_config()
    folder_id = data.get("folder_id") or config.get("folder_id")

    try:
        result = converter.convert_and_upload(url, folder_id=folder_id)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Google OAuth (run once from server machine's browser)
# ---------------------------------------------------------------------------

@app.route("/auth")
def auth_start():
    if not CREDENTIALS_FILE.exists():
        return _page(
            "<p style='color:#c00'>❌ <code>credentials.json</code> not found in the server "
            "directory.<br>See <strong>README.md</strong> for setup instructions.</p>"
        ), 500

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=url_for("auth_callback", _external=True),
    )
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/auth/callback")
def auth_callback():
    state = session.get("oauth_state")
    if not state:
        return _page("<p style='color:#c00'>OAuth state missing. Please start from <a href='/auth'>/auth</a>.</p>"), 400

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=url_for("auth_callback", _external=True),
        state=state,
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    with open(converter.TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    return _page(
        "<div class='status'>✓ Authenticated with Google Drive! "
        "You can close this tab — your iPhone is ready to send articles.</div>"
        "<p><a href='/'>← Back to home</a></p>"
    )


# ---------------------------------------------------------------------------
# Status endpoint (useful for Shortcut health-check)
# ---------------------------------------------------------------------------

@app.route("/status")
def status():
    config = converter.load_config()
    return jsonify({
        "ok": True,
        "authenticated": converter.is_authenticated(),
        "folder_id": config.get("folder_id"),
    })


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Send to Kobo server running.")
    print(f"  Open http://localhost:{port}/ in this machine's browser to sign in to Google Drive.")
    print(f"  Then set your iOS Shortcut URL to http://YOUR_LOCAL_IP:{port}/convert\n")
    app.run(host=host, port=port, debug=False)
