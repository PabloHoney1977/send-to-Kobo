# Send to Kobo

Convert any web article to EPUB — with all images — and save it to Google Drive, ready to read on your Kobo e-reader.

Trigger it from your iPhone or iPad via the **iOS Share Sheet** (tap Share → "Send to Kobo" in any app) or a **Safari bookmarklet**. The server runs in the cloud so it works anywhere, not just at home.

---

## How it works

```
iPad / iPhone  ──  Share Sheet or bookmarklet
                          │  HTTPS POST /convert
                          ▼
              Flask server on Render (free)
                          │
          fetch → extract → create EPUB → Google Drive
                                                │
                                         Kobo syncs ◄──┘
```

---

## Setup overview

1. Deploy the server to Render (free)
2. Set up Google Drive credentials
3. Sign in to Google Drive via your browser
4. Install the iOS Shortcut or Safari bookmarklet

---

## Step 1 — Deploy to Render

[Render](https://render.com) is a free cloud hosting service. Your server gets a permanent HTTPS URL like `https://send-to-kobo.onrender.com`.

1. **Fork this repository** to your own GitHub account (click Fork on GitHub)
2. Go to [render.com](https://render.com) and create a free account
3. Click **New → Web Service** → connect your GitHub account → select your forked repo
4. Render will detect `render.yaml` automatically — click **Create Web Service**
5. Wait ~2 minutes for the first deploy to finish

Render auto-generates `SECRET_KEY` and `API_TOKEN` for you. **Copy the `API_TOKEN`** — you'll need it in your iOS Shortcut.

To find it: Render dashboard → your service → **Environment** tab → reveal `API_TOKEN`.

> **Free tier note:** The server sleeps after 15 minutes of inactivity and takes ~30 seconds to wake on the next request. For occasional use this is fine. Upgrade to Render's $7/month "Starter" plan if you want it always-on.

---

## Step 2 — Set up Google Drive credentials

### Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. **APIs & Services → Library** → search **Google Drive API** → Enable

### Create OAuth credentials

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
2. If prompted to configure the consent screen first:
   - User type: **External** → fill in app name (anything) → save
3. Application type: **Web application**
4. Name: anything (e.g. "Send to Kobo")
5. Under **Authorized redirect URIs** → Add URI:
   ```
   https://YOUR-APP-NAME.onrender.com/auth/callback
   ```
   (replace `YOUR-APP-NAME` with your actual Render service name)
6. Click **Create**
7. Click **Download JSON** — this is your `credentials.json`

### Add credentials to Render

Open the downloaded `credentials.json` in a text editor and copy its entire contents.

In Render: your service → **Environment** tab → find `GOOGLE_CREDENTIALS_JSON` → paste the JSON → **Save Changes**.

### Set your Drive folder ID (optional but recommended)

Find or create a folder in Google Drive for your Kobo books. The **folder ID** is the string at the end of its URL:

```
https://drive.google.com/drive/folders/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
                                        ────────────────────────────────────────────
                                                      this is the folder ID
```

In Render: **Environment** → `DRIVE_FOLDER_ID` → paste the ID → **Save Changes**.

---

## Step 3 — Sign in to Google Drive

Visit `https://YOUR-APP-NAME.onrender.com/auth` in any browser on any device.  
Sign in with the Google account that owns the Drive folder. You only do this once — the token is stored on the server's persistent disk and refreshed automatically.

---

## Step 4 — Set up your iPhone / iPad

Your server URL is: `https://YOUR-APP-NAME.onrender.com`  
Your API token is: the `API_TOKEN` value from the Render Environment tab

---

### Option A — iOS Share Sheet (best experience)

Appears in the Share Sheet of Safari and every other app. Tap Share → "Send to Kobo" on any article.

**Steps (~3 minutes in the Shortcuts app):**

1. Open the **Shortcuts** app → tap **+** to create a new shortcut
2. Tap the name at the top → rename to **"Send to Kobo"**
3. Tap **Add Action** → search **"Get Contents of URL"** → select it
4. Configure the action:
   - URL: `https://YOUR-APP-NAME.onrender.com/convert`
   - Tap **Show More**
   - Method: **POST**
   - Request Body: **JSON**
   - Tap **Add new field** → Key: `url` → tap the value field → tap the variable icon → select **Shortcut Input**
5. Add a header for authentication:
   - Still in the same action, scroll to **Headers**
   - Tap **Add new field** → Key: `Authorization` → Value: `Bearer YOUR_API_TOKEN`
6. Tap **Add Action** → search **"Show Notification"** → select it
   - Clear the message field → tap the variable icon → select the result from "Get Contents of URL"
7. Tap the **ⓘ** icon at the bottom → enable **Show in Share Sheet** → input types: **URLs** and **Safari web pages**
8. Tap **Done**

Now: open any article in Safari → tap **Share** → **Send to Kobo** → get a notification when it's in your Drive.

---

### Option B — Safari bookmarklet

A bookmark in Safari's toolbar that sends the current page when tapped.

1. In Safari, bookmark any page (Share → Add Bookmark)
2. Open Bookmarks → find it → tap **Edit**
3. Rename it to **Send to Kobo**
4. Replace the URL with the following — substituting your server URL and API token:

```
javascript:(function(){fetch('https://YOUR-APP-NAME.onrender.com/convert',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer YOUR_API_TOKEN'},body:JSON.stringify({url:window.location.href})}).then(r=>r.json()).then(d=>alert(d.ok?'✓ Sent: '+d.title:'✗ '+d.error)).catch(e=>alert('Error: '+e))})()
```

5. Save it

While reading an article: tap the bookmarks icon → **Send to Kobo**.

---

## Step 5 — Add the Claude connector (send chats straight from the app)

Options A/B above only work for web pages you can share a URL for — they
can't see the content of a Claude conversation, because claude.ai's share
links are rendered client-side (there's no HTML for a server to fetch).

`mcp_server.py` sidesteps that: it's a small remote MCP server exposing one
tool, `send_to_kobo(title, content)`. Add it as a **custom connector** in
Claude, and Claude can call it directly from *any* client — web, desktop,
iOS, Android — passing the conversation text it already has in context. No
fetching, no rendering, no Share Sheet involved.

**Deploy it** (as a second Render service — already defined in `render.yaml`
next to the main one):

1. Push this repo (with `mcp_server.py` and the updated `render.yaml`) to
   your fork, then in Render: **New → Blueprint** → select the repo. Render
   creates both `send-to-kobo` and `send-to-kobo-mcp` from the one
   `render.yaml`. (If you already created `send-to-kobo` manually, just add
   `send-to-kobo-mcp` the same way, using `python mcp_server.py` as the
   start command.)
2. On the main `send-to-kobo` service, finish Steps 1–3 above (Google auth)
   if you haven't already.
3. Render dashboard → `send-to-kobo` service → **Environment** → open
   `GOOGLE_TOKEN_JSON` (or read it off `/auth` after signing in) and copy
   its value.
4. Render dashboard → `send-to-kobo-mcp` service → **Environment** → paste
   that same value into `GOOGLE_TOKEN_JSON` → **Save Changes**.
5. Still on `send-to-kobo-mcp` → **Environment** → copy the generated
   `MCP_SECRET_PATH` value.

Your connector URL is:

```
https://YOUR-MCP-APP-NAME.onrender.com/YOUR_MCP_SECRET_PATH/mcp
```

**There's no login step for this endpoint** — anyone with that exact URL can
upload files to your Kobo Drive folder, so treat it like a password: don't
post it publicly, don't commit it, don't share it outside your own Claude
connector settings.

**Add it in Claude:**

1. In Claude (web, desktop, or the app) go to **Settings → Connectors → Add
   custom connector**
2. Paste the URL from above, give it a name (e.g. "Send to Kobo"), save
3. In any chat, just ask — e.g. *"send this conversation to my Kobo"* or
   *"turn this into an EPUB and send it to Kobo"* — Claude will call the
   tool and reply with the Drive link

---

## Reading on Kobo

### Google Drive sync (easiest)
If your Kobo is linked to a Google account, books in the configured Drive folder appear automatically under **My Books → Cloud** on the next sync.

### USB sideload
Download the EPUB from Google Drive to your device, then transfer to the Kobo via the **Kobo iOS app** or copy to the `Digital Editions` folder over USB.

---

## CLI usage (optional)

The command-line tool still works for scripting or one-off use, running locally:

```bash
pip install -r requirements.txt
python send_to_kobo.py https://example.com/some-article
python send_to_kobo.py https://example.com/article --no-upload --output article.epub
python send_to_kobo.py config --folder-id YOUR_FOLDER_ID
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Shortcut returns "Unauthorized" | Check the `Authorization: Bearer TOKEN` header matches `API_TOKEN` in Render |
| `/auth` shows "No Google credentials" | Paste your `credentials.json` content into `GOOGLE_CREDENTIALS_JSON` in Render |
| OAuth callback error | Make sure the redirect URI in Google Cloud Console exactly matches `https://YOUR-APP.onrender.com/auth/callback` |
| First request after inactivity is slow | Free tier apps sleep; the first request takes ~30s to wake up. Normal. |
| Drive upload 403 | Confirm the Google Drive API is enabled in your Google Cloud project |
| Page content looks sparse | Some sites use heavy JavaScript; try the article's "reader mode" URL if available |
| Token expired | Visit `https://YOUR-APP.onrender.com/auth` again to re-authenticate |
| Connector tool call fails with "credentials.json not found" | You didn't copy `GOOGLE_TOKEN_JSON` from the main service into `send-to-kobo-mcp`'s environment |
| Claude can't find/add the connector | Make sure the URL ends in `/mcp` and includes the exact `MCP_SECRET_PATH` value — a wrong path returns 404 |
