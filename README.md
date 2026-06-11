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
