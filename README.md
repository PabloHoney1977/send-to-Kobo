# Send to Kobo

Convert any web article to EPUB — with all images — and save it directly to your Google Drive so you can read it on your Kobo e-reader.

## How it works

1. Fetches the web page and extracts the main article body (using [readability](https://github.com/buriy/python-readability))
2. Downloads and embeds all images into the EPUB
3. Uploads the finished EPUB to a folder of your choice in Google Drive
4. Open the file on your Kobo via the Kobo app's Google Drive sync, or download it manually

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

Requires Python 3.8 or later.

### 2. Set up Google Drive API credentials

You need a Google Cloud OAuth client to allow the script to upload files to your Drive.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. In the left menu go to **APIs & Services → Library**, search for **Google Drive API**, and click **Enable**
4. Go to **APIs & Services → Credentials** and click **Create Credentials → OAuth client ID**
5. Set **Application type** to **Desktop app**, give it a name, and click **Create**
6. Click **Download JSON** and save the file as `credentials.json` in this directory

> **Note:** `credentials.json` is listed in `.gitignore` and will never be committed.

### 3. (Optional) Set a default Google Drive folder

Find the folder you want to save books to in Google Drive. The folder ID is the long string at the end of its URL:

```
https://drive.google.com/drive/folders/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                        this is the folder ID
```

Save it as your default so you don't have to type it every time:

```bash
python send_to_kobo.py config --folder-id YOUR_FOLDER_ID
```

---

## Usage

### Convert and upload an article

```bash
python send_to_kobo.py https://example.com/some-great-article
```

On the **first run** a browser window will open asking you to sign in to Google and grant access to your Drive. This only happens once; the token is saved to `~/.send_to_kobo_token.json`.

### Convert without uploading (local EPUB only)

```bash
python send_to_kobo.py https://example.com/article --no-upload
python send_to_kobo.py https://example.com/article --no-upload --output my-article.epub
```

### Upload to a specific folder (one-off)

```bash
python send_to_kobo.py https://example.com/article --folder-id YOUR_FOLDER_ID
```

### All options

```
usage: send_to_kobo [-h] {convert,config} ...

positional arguments:
  URL                   Web page URL to convert (shorthand, no sub-command needed)

sub-commands:
  convert               Convert a URL to EPUB and upload (default)
    --folder-id ID      Google Drive folder ID (overrides saved config)
    --output, -o FILE   Local filename for the EPUB
    --no-upload         Save locally only, skip Drive upload
    --credentials FILE  Path to credentials.json (default: ./credentials.json)

  config                View or set default configuration
    --folder-id ID      Set the default Google Drive folder ID
    --clear-folder      Remove the saved folder ID
```

---

## Reading on Kobo

### Option A — Kobo + Google Drive (easiest)

If your Kobo is linked to Google Drive (via the Kobo account settings), books uploaded to the configured folder will appear automatically in **My Books → Cloud** on your device the next time it syncs.

### Option B — Sideload via USB

1. Use `--no-upload` to save the EPUB locally
2. Connect your Kobo with a USB cable
3. Copy the `.epub` file to the `Digital Editions` folder on the Kobo
4. Eject and the book will appear in your library

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `credentials.json not found` | Download it from Google Cloud Console (see Setup step 2) |
| Page content looks wrong | Some sites block scrapers; try a different article or check if the page uses heavy JavaScript |
| Images missing in EPUB | Some images are served with hot-link protection; the script skips ones it can't download |
| Drive upload fails with 403 | Make sure the Google Drive API is enabled in your Google Cloud project |
| Token expired / revoked | Delete `~/.send_to_kobo_token.json` and re-run to re-authenticate |
