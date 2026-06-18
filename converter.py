"""Core conversion logic shared by the CLI and web server."""

import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from ebooklib import epub
from readability import Document
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CONFIG_PATH = Path.home() / ".send_to_kobo.json"


def _resolve_token_dir() -> Path:
    """Return a writable directory for the OAuth token.

    Preference order:
      1. TOKEN_DIR env var (e.g. /data on Render with a persistent disk)
      2. /tmp  (always writable; token lost on restart if no disk)
    """
    candidate = Path(os.environ.get("TOKEN_DIR", str(Path.home())))
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        # Verify it's actually writable
        test = candidate / ".write_test"
        test.touch()
        test.unlink()
        return candidate
    except OSError:
        return Path("/tmp")


TOKEN_PATH = _resolve_token_dir() / ".send_to_kobo_token.json"

EPUB_CSS = """\
body {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 0 1em;
    color: #222;
}
h1 { font-size: 1.6em; margin-bottom: 0.5em; }
h2 { font-size: 1.3em; }
h3 { font-size: 1.1em; }
h1, h2, h3 {
    font-family: Helvetica, Arial, sans-serif;
    color: #111;
    line-height: 1.2;
}
img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1em auto;
}
p { margin: 0.7em 0; text-align: justify; }
blockquote {
    border-left: 3px solid #ccc;
    margin-left: 0;
    padding-left: 1em;
    color: #555;
    font-style: italic;
}
figure { margin: 1em 0; }
figcaption { font-size: 0.85em; color: #666; text-align: center; }
a { color: #1a0dab; }
pre, code {
    font-family: "Courier New", monospace;
    font-size: 0.85em;
    background: #f5f5f5;
    padding: 0.2em 0.4em;
}
pre { padding: 0.8em; }
"""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    session = requests.Session()
    response = session.get(url, headers=headers, timeout=30, allow_redirects=True)
    response.raise_for_status()
    return response.text, response.url, session


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def extract_content(html, url):
    doc = Document(html)
    title = doc.title()
    content_html = doc.summary(html_partial=True)
    return title, content_html


def sanitize_filename(name):
    safe = re.sub(r"[^\w\s-]", "", name)
    safe = re.sub(r"\s+", "_", safe.strip())
    return safe[:80] or "article"


# ---------------------------------------------------------------------------
# EPUB creation
# ---------------------------------------------------------------------------

def _download_image(img_url, session):
    try:
        resp = session.get(img_url, timeout=15)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "").split(";")[0].strip()
        if not ct.startswith("image/"):
            ct = "image/jpeg"
        return resp.content, ct
    except Exception:
        return None, None


def _embed_images(soup, base_url, session, book):
    ext_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/svg+xml": "svg",
    }
    count = 0
    for img in soup.find_all("img"):
        # Try each attribute in order, skipping data: URIs (lazy-load placeholders)
        src = None
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            val = img.get(attr, "")
            if val and not val.startswith("data:"):
                src = val
                break
        if not src:
            img.decompose()
            continue

        img_url = urljoin(base_url, src)
        data, mime = _download_image(img_url, session)
        if not data:
            img.decompose()
            continue

        ext = ext_map.get(mime, "jpg")
        local_name = f"images/img_{count:03d}.{ext}"
        count += 1

        epub_img = epub.EpubImage()
        epub_img.file_name = local_name
        epub_img.media_type = mime
        epub_img.content = data
        book.add_item(epub_img)

        img["src"] = local_name
        img.attrs = {k: v for k, v in img.attrs.items() if k in ("src", "alt", "title")}

    return count


def create_epub(title, content_html, source_url, session, output_path):
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("en")
    book.add_metadata("DC", "source", source_url)

    soup = BeautifulSoup(content_html, "lxml")

    # Strip Wikipedia-specific clutter: citation superscripts [1][2]..., edit links
    for el in soup.select("sup.reference, .mw-editsection, .noprint"):
        el.decompose()

    n_images = _embed_images(soup, source_url, session, book)

    style = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=EPUB_CSS.encode("utf-8"),
    )
    book.add_item(style)

    escaped_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    chapter_html = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        "<head>"
        f"<title>{escaped_title}</title>"
        '<link rel="stylesheet" href="style.css" type="text/css"/>'
        "</head><body>"
        f"<h1>{escaped_title}</h1>"
        f'<p><small>Source: <a href="{source_url}">{source_url}</a></small></p>'
        f"{soup}"
        "</body></html>"
    )

    chapter = epub.EpubHtml(title=title, file_name="article.xhtml", lang="en")
    chapter.content = chapter_html.encode("utf-8")
    chapter.add_item(style)
    book.add_item(chapter)

    book.toc = (epub.Link("article.xhtml", title, "article"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(output_path), book)
    return n_images


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

def is_authenticated():
    return TOKEN_PATH.exists()


def get_drive_service(credentials_path=None):
    creds = None
    creds_file = Path(credentials_path) if credentials_path else Path("credentials.json")

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Cloud deployments set GOOGLE_CREDENTIALS_JSON and authenticate via /auth
            if os.environ.get("GOOGLE_CREDENTIALS_JSON"):
                raise RuntimeError(
                    "Not authenticated. Visit /auth in a browser to sign in to Google Drive."
                )
            if not creds_file.exists():
                raise FileNotFoundError(
                    f"'{creds_file}' not found. See README.md for Google Drive setup."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_to_drive(service, file_path, folder_id=None):
    file_name = Path(file_path).name
    metadata = {"name": file_name, "mimeType": "application/epub+zip"}
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaFileUpload(str(file_path), mimetype="application/epub+zip", resumable=True)
    result = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,webViewLink",
    ).execute()
    return result


# ---------------------------------------------------------------------------
# High-level pipeline
# ---------------------------------------------------------------------------

def convert_and_upload(url, folder_id=None, output_path=None, credentials_path=None):
    """Fetch URL, create EPUB, upload to Drive. Returns dict with job details."""
    html, final_url, session = fetch_page(url)
    title, content_html = extract_content(html, final_url)

    epub_path = Path(output_path) if output_path else Path(sanitize_filename(title) + ".epub")
    n_images = create_epub(title, content_html, final_url, session, epub_path)
    size_kb = epub_path.stat().st_size // 1024

    service = get_drive_service(credentials_path)
    result = upload_to_drive(service, epub_path, folder_id)

    return {
        "title": title,
        "epub_path": str(epub_path),
        "size_kb": size_kb,
        "n_images": n_images,
        "drive_id": result["id"],
        "drive_name": result["name"],
        "drive_link": result.get("webViewLink", ""),
    }
