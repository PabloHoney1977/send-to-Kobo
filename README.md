# Send to Kobo

Convert any web article to EPUB — with all images — and save it to Google Drive, ready to read on your Kobo e-reader.

Works from your iPhone via:
- **iOS Share Sheet** — tap Share → "Send to Kobo" while browsing any article in Safari (or any other app)
- **Safari bookmarklet** — a tappable bookmark in Safari's toolbar
- **Web UI** — a simple form if you prefer typing a URL
- **CLI** — `python send_to_kobo.py URL` from the terminal

---

## How it works

```
iPhone (Share Sheet / bookmarklet)
        │  HTTP POST /convert
        ▼
Flask server  ──►  fetch page  ──►  extract article  ──►  create EPUB  ──►  Google Drive
(runs on your Mac/PC/Pi)
                                                                                  │
                                                                            Kobo syncs ◄──┘
```

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

Requires Python 3.8 or later.

### 2. Set up Google Drive API credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. **APIs & Services → Library** → search **Google Drive API** → Enable
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
5. Application type: **Desktop app** — give it any name → Create
6. Click **Download JSON** → save as `credentials.json` in this directory

> `credentials.json` is in `.gitignore` and will never be committed.

### 3. Start the server

```bash
python app.py
```

The server listens on port 5000 on all interfaces so your iPhone can reach it over Wi-Fi.

### 4. Sign in to Google Drive (one-time, from the server machine)

Open **http://localhost:5000/auth** in a browser **on the same machine as the server**.  
Complete the Google sign-in — the token is saved locally and reused from then on.

> If your server is headless (Raspberry Pi etc.), run `python send_to_kobo.py https://example.com` once from the terminal — it will open an auth URL you can visit from any browser.

### 5. Set a default Google Drive folder (recommended)

Find your Kobo folder in Google Drive. The **folder ID** is at the end of its URL:

```
https://drive.google.com/drive/folders/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
                                        ────────────────────────────────────────────
                                                      folder ID
```

```bash
python send_to_kobo.py config --folder-id YOUR_FOLDER_ID
```

---

## iPhone setup

First, find your server's local IP address (e.g. `192.168.1.42`):
- **Mac:** System Settings → Wi-Fi → your network → IP address
- **Linux/Pi:** `ip addr` or `hostname -I`

Your server URL will be: `http://192.168.1.42:5000`

---

### Option A — iOS Share Sheet (best experience)

The shortcut appears in the Share Sheet of Safari and every other app. Tap Share → "Send to Kobo" and you're done.

**Steps (takes ~2 minutes):**

1. Open the **Shortcuts** app on your iPhone
2. Tap **+** (top right) to create a new shortcut
3. Tap the shortcut name at the top → rename it to **"Send to Kobo"**
4. Tap **Add Action** → search **"Get Contents of URL"** → select it
5. Configure the action:
   - Tap the URL field → type `http://192.168.1.42:5000/convert` (your server IP)
   - Tap **Show More**
   - Method: **POST**
   - Request Body: **JSON**
   - Tap **Add new field** (text) → Key: `url` → Value: tap the field, then tap the variable icon and choose **Shortcut Input**
6. Tap **Add Action** → search **"Show Notification"** → select it
   - Tap the message field → clear it → tap the variable icon → select the result of "Get Contents of URL"
7. Tap the **ⓘ** (info) icon at the bottom → enable **"Show in Share Sheet"** → set input types to **URLs** and **Safari web pages**
8. Tap **Done**

Now when you're reading an article in Safari: **Share → Send to Kobo** → a notification confirms it was sent to your Drive.

---

### Option B — Safari bookmarklet

A bookmark that sends the current page when tapped. Simpler to set up but lives in bookmarks, not the Share Sheet.

1. In Safari on your iPhone, bookmark any page (tap Share → Add Bookmark)
2. Open **Bookmarks** → find the bookmark you just made → tap **Edit**
3. Change the **name** to `Send to Kobo`
4. Replace the **URL** with this (change the IP to your server's):

```
javascript:(function(){fetch('http://192.168.1.42:5000/convert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:window.location.href})}).then(r=>r.json()).then(d=>alert(d.ok?'✓ Sent: '+d.title:'✗ '+d.error)).catch(e=>alert('Error: '+e))})()
```

5. Save the bookmark

While reading an article in Safari, tap the bookmarks icon → tap **Send to Kobo**.

---

## Running the server automatically

### macOS — launchd

Create `~/Library/LaunchAgents/com.sendtokobo.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sendtokobo</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/send-to-Kobo/app.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>/path/to/send-to-Kobo</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.sendtokobo.plist
```

### Linux / Raspberry Pi — systemd

```ini
# /etc/systemd/system/send-to-kobo.service
[Unit]
Description=Send to Kobo web server
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/path/to/send-to-Kobo
ExecStart=python3 /path/to/send-to-Kobo/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now send-to-kobo
```

---

## CLI usage

The CLI is still available for scripting or one-off use:

```bash
# Convert and upload
python send_to_kobo.py https://example.com/some-article

# Save locally only (no upload)
python send_to_kobo.py https://example.com/article --no-upload

# Upload to a specific folder
python send_to_kobo.py https://example.com/article --folder-id YOUR_FOLDER_ID
```

---

## Reading on Kobo

### Google Drive sync (easiest)
If your Kobo is linked to a Google account, books saved to the configured Drive folder appear automatically under **My Books → Cloud** on the next sync.

### Sideload via USB
Use `--no-upload`, then copy the `.epub` to the `Digital Editions` folder on your Kobo via USB.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| iPhone can't reach the server | Make sure both are on the same Wi-Fi; check server IP with `ifconfig` or System Settings |
| `credentials.json not found` | Download it from Google Cloud Console (Setup step 2) |
| OAuth error on `/auth` | This must be visited from the server machine's browser, not your iPhone |
| Token expired | Delete `~/.send_to_kobo_token.json` and re-visit `/auth` |
| Shortcut shows raw JSON instead of notification | Edit the Show Notification action and select the `Get Contents` result variable |
| Page content looks sparse | Some sites block scrapers or use heavy JavaScript; try a reader-mode URL if available |
| Drive upload 403 | Ensure the Google Drive API is enabled in your Cloud project |
