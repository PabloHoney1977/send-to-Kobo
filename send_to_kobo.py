#!/usr/bin/env python3
"""Convert web articles to EPUB and upload to Google Drive for Kobo e-readers."""

import argparse
import json
import os
import re
import sys
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
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CONFIG_PATH = Path.home() / ".send_to_kobo.json"
TOKEN_PATH = Path.home() / ".send_to_kobo_token.json"

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
# Image handling
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
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )
        if not src or src.startswith("data:"):
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


# ---------------------------------------------------------------------------
# EPUB creation
# ---------------------------------------------------------------------------

def create_epub(title, content_html, source_url, session, output_path):
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("en")
    book.add_metadata("DC", "source", source_url)

    soup = BeautifulSoup(content_html, "lxml")
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
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"'
        ' "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
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

def get_drive_service(credentials_path=None):
    creds = None
    creds_file = Path(credentials_path) if credentials_path else Path("credentials.json")

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_file.exists():
                print(f"\nError: '{creds_file}' not found.")
                print("See README.md for Google Drive setup instructions.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=0)

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
# CLI commands
# ---------------------------------------------------------------------------

def cmd_convert(args):
    config = load_config()
    folder_id = args.folder_id or config.get("folder_id")

    print(f"Fetching: {args.url}")
    try:
        html, final_url, session = fetch_page(args.url)
    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
        sys.exit(1)

    print("Extracting article content...")
    title, content_html = extract_content(html, final_url)
    print(f"Title: {title}")

    epub_path = Path(args.output) if args.output else Path(sanitize_filename(title) + ".epub")

    print("Creating EPUB (downloading images)...")
    n_images = create_epub(title, content_html, final_url, session, epub_path)
    size_kb = epub_path.stat().st_size // 1024
    print(f"EPUB saved: {epub_path}  ({size_kb} KB, {n_images} image(s))")

    if args.no_upload:
        return

    print("Authenticating with Google Drive...")
    try:
        service = get_drive_service(getattr(args, "credentials", None))
    except Exception as e:
        print(f"Authentication error: {e}")
        sys.exit(1)

    dest = f" → folder {folder_id}" if folder_id else " → My Drive root"
    print(f"Uploading{dest}...")
    try:
        result = upload_to_drive(service, epub_path, folder_id)
        print(f"Uploaded: {result['name']}  (id: {result['id']})")
        if "webViewLink" in result:
            print(f"View: {result['webViewLink']}")
    except HttpError as e:
        print(f"Drive upload error: {e}")
        sys.exit(1)


def cmd_config(args):
    config = load_config()
    changed = False

    if args.folder_id:
        config["folder_id"] = args.folder_id
        print(f"Default folder ID set to: {args.folder_id}")
        changed = True

    if args.clear_folder:
        config.pop("folder_id", None)
        print("Default folder ID cleared.")
        changed = True

    if changed:
        save_config(config)
    else:
        if config:
            print("Current configuration:")
            for k, v in config.items():
                print(f"  {k}: {v}")
        else:
            print("No configuration stored.")
        print(f"\nConfig file: {CONFIG_PATH}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="send_to_kobo",
        description="Convert a web article to EPUB and send it to Google Drive for Kobo reading.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s https://example.com/some-article
  %(prog)s https://example.com/some-article --folder-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
  %(prog)s https://example.com/some-article --no-upload --output my-article.epub
  %(prog)s config --folder-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    # --- config sub-command ---
    cfg = subparsers.add_parser("config", help="View or set default configuration")
    cfg.add_argument("--folder-id", metavar="ID", help="Set the default Google Drive folder ID")
    cfg.add_argument("--clear-folder", action="store_true", help="Remove the saved folder ID")

    # --- convert (default, no sub-command needed) ---
    # Support both: `send_to_kobo.py URL` and `send_to_kobo.py convert URL`
    conv = subparsers.add_parser("convert", help="Convert a URL to EPUB and upload (default)")
    conv.add_argument("url", help="Web page URL to convert")
    conv.add_argument("--folder-id", metavar="ID", help="Google Drive folder ID (overrides config)")
    conv.add_argument("--output", "-o", metavar="FILE", help="Local filename for the EPUB")
    conv.add_argument("--no-upload", action="store_true", help="Save locally only, skip Drive upload")
    conv.add_argument("--credentials", metavar="FILE", help="Path to credentials.json", default=None)

    # Allow `send_to_kobo.py URL` without the 'convert' keyword by pre-inserting it
    argv = sys.argv[1:]
    if argv and argv[0] not in ("convert", "config", "-h", "--help"):
        argv = ["convert"] + argv

    args = parser.parse_args(argv)

    if args.command == "config":
        cmd_config(args)
    elif args.command == "convert":
        cmd_convert(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
