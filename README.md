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

**Make sure the code is on a branch Render can see.** If you're working off
a feature branch (e.g. from a Claude Code session), either merge it to the
branch your Render services deploy from, or point the new service at that
branch directly in step 2 below — either works.

### 5.1 — Create the second Render service

You already created `send-to-kobo` by hand in Step 1 (**New → Web Service**),
so create this one the same way rather than via Blueprint — mixing manual
services with a Blueprint sync in the same Render project can get confusing.

1. Render dashboard → **New → Web Service**
2. Connect the same GitHub repo you used for `send-to-kobo` (your fork)
3. Pick the branch that has `mcp_server.py` (see note above)
4. **Name:** `send-to-kobo-mcp` (anything works, you'll need the URL later either way)
5. **Runtime:** Python 3
6. **Build Command:** `pip install -r requirements.txt`
7. **Start Command:** `python mcp_server.py`
8. **Instance Type:** Free is fine (same as the main service)
9. Don't click Create yet — open **Advanced** to add environment variables first (next section)

### 5.2 — Add its environment variables

Still on the "New Web Service" setup screen (or **Environment** tab after
creating it):

1. **Add Environment Variable** → Key: `MCP_SECRET_PATH` → click **Generate**
   next to the value field (Render fills in a random string). This becomes
   part of your connector URL, acting like a password — nothing else
   guards this endpoint.
2. **Add Environment Variable** → Key: `GOOGLE_TOKEN_JSON` → leave the value
   blank for now, save a placeholder — you'll fill it in in step 5.3.
3. *(Optional)* **Add Environment Variable** → Key: `DRIVE_FOLDER_ID` →
   same folder ID you used for the main service, if you set one there.
4. Click **Create Web Service**. First deploy takes ~2 minutes.

### 5.3 — Copy your Google auth token from the main service into this one

The MCP server needs to sign in to Drive the same way the main service
does, but it can't run the interactive `/auth` browser flow itself — it
just reuses the token.

1. Confirm the main `send-to-kobo` service is already signed in (Step 3
   above). If you're not sure, visit `https://YOUR-APP-NAME.onrender.com/auth`
   again — signing in again is harmless and shows the token either way.
2. Render dashboard → `send-to-kobo` service → **Environment** tab
3. Find `GOOGLE_TOKEN_JSON` → click the eye icon to reveal it → copy the
   entire value (it's one long JSON string starting with `{` and ending
   with `}`)
   - If `GOOGLE_TOKEN_JSON` isn't there yet, get it from the `/auth` sign-in
     page instead — it shows the same token in a text box right after you
     authenticate, with instructions to paste it into this env var.
4. Render dashboard → `send-to-kobo-mcp` service → **Environment** tab
5. Click into `GOOGLE_TOKEN_JSON` → paste the value you copied → **Save
   Changes** (this triggers a redeploy automatically, ~1 minute)

### 5.4 — Build your connector URL

1. On the `send-to-kobo-mcp` service page, copy the service's URL from the
   top of the dashboard, e.g. `https://send-to-kobo-mcp.onrender.com`
2. **Environment** tab → find `MCP_SECRET_PATH` → click the eye icon →
   copy its value, e.g. `k3j9d8f7a2b1...`
3. Your connector URL is those two pieces combined:

   ```
   https://send-to-kobo-mcp.onrender.com/k3j9d8f7a2b1.../mcp
   ```

   (service URL + `/` + the secret value + `/mcp` — no other slashes)

**Treat this URL like a password.** There's no login screen guarding it —
anyone who has the exact URL can upload files to your Kobo Drive folder.
Don't post it publicly, commit it to a repo, or paste it anywhere other
than your own Claude connector settings.

### 5.5 — Add it as a custom connector in Claude

1. In Claude (web, desktop app, or mobile app) open **Settings → Connectors**
2. Tap/click **Add custom connector** (wording may vary slightly by
   platform/version — look for "Add connector" or a "+" next to Connectors)
3. **Name:** anything, e.g. `Send to Kobo`
4. **URL:** paste the connector URL from 5.4
5. Save — Claude should confirm it connected and list a `send_to_kobo` tool
6. If your client shows a per-chat toggle for which connectors/tools are
   active, make sure "Send to Kobo" is turned on for the conversation you
   want to use it in

### 5.6 — Test it

In any chat, ask something like *"send this conversation to my Kobo"* or
*"turn this into an EPUB and send it to Kobo."* Claude will call the tool
and reply with a confirmation and the Drive link. Check the Kobo folder in
Google Drive (or your Kobo device, after its next sync) to confirm the
EPUB landed.

Note: like the main service, this one is on Render's free tier and sleeps
after 15 minutes of inactivity — the first call after a while may take
~20–30 seconds to respond. That's normal, not a failure.

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
