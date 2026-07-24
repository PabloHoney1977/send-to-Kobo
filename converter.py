"""Core conversion logic shared by the CLI and web server."""

import io
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

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

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
a { color: inherit; text-decoration: underline; }
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
    session = requests.Session()
    # Set headers on the SESSION so they persist to every request, including the
    # image downloads in _download_image. Wikimedia (upload.wikimedia.org) returns
    # 403 to the default python-requests User-Agent, which previously caused all
    # images to fail to download (text came through, images didn't).
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    response = session.get(url, timeout=30, allow_redirects=True)
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

def _normalize_image(data):
    """Decode and re-encode an image as JPEG/PNG for e-reader compatibility.

    Many Kobo firmware versions can't render WebP/AVIF/TIFF embedded in an
    EPUB (they just show blank space), and some CDNs send a wrong or generic
    Content-Type header. Round-tripping every image through Pillow both
    verifies it decodes cleanly and normalizes it to a format every Kobo can
    display. Returns (data, mime_type), or (None, None) if the image can't
    be decoded at all.
    """
    if not _PIL_AVAILABLE:
        return data, None
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return None, None

    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    buf = io.BytesIO()
    if has_alpha:
        im.convert("RGBA").save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    im.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def _download_image(img_url, session):
    try:
        resp = session.get(img_url, timeout=20)
        resp.raise_for_status()
        raw = resp.content
        ct = resp.headers.get("content-type", "").split(";")[0].strip()

        # SVGs decode fine as text but Pillow can't rasterize them; pass
        # through unchanged rather than feeding them to _normalize_image.
        if ct == "image/svg+xml" or img_url.lower().split("?")[0].endswith(".svg"):
            return raw, "image/svg+xml"

        data, mime = _normalize_image(raw)
        if mime is not None:
            return data, mime
        if data is None:
            return None, None

        # Pillow unavailable or couldn't decode; fall back to the declared
        # content-type (previous behaviour).
        if not ct.startswith("image/"):
            ct = "image/jpeg"
        return raw, ct
    except Exception:
        return None, None


_EXT_MAP = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


def _pick_best_from_srcset(srcset):
    """Return the highest-resolution URL from a srcset string, or None.

    Handles both "url 320w, url 640w" (width) and "url 1x, url 2x" (density)
    descriptor forms; picks the entry with the largest numeric value.
    """
    best_url, best_val = None, -1.0
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        url = tokens[0]
        if url.startswith("data:"):
            continue
        descriptor = 1.0
        if len(tokens) > 1:
            d = tokens[1].lower().rstrip("wx")
            try:
                descriptor = float(d)
            except ValueError:
                pass
        if descriptor > best_val:
            best_val, best_url = descriptor, url
    return best_url


def _best_src(img):
    """Return the highest-resolution image URL for an <img> tag.

    Prefers the largest entry in the img's own srcset, then falls back to
    a parent <picture>'s <source srcset> (common for art-directed hero/lead
    images that carry no usable src on the <img> itself), then src /
    data-src / data-lazy-src / data-original, skipping data: URI
    placeholders used for lazy loading.
    """
    best = _pick_best_from_srcset(img.get("srcset", ""))
    if best:
        return best

    picture = img.find_parent("picture")
    if picture:
        for source in picture.find_all("source"):
            best = _pick_best_from_srcset(source.get("srcset", ""))
            if best:
                return best

    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
        val = img.get(attr, "")
        if val and not val.startswith("data:"):
            return val
    return None


def _embed_images(soup, base_url, session, book, seen_urls=None):
    if seen_urls is None:
        seen_urls = set()
    count = 0
    for img in soup.find_all("img"):
        src = _best_src(img)
        if not src:
            img.decompose()
            continue

        img_url = urljoin(base_url, src)
        data, mime = _download_image(img_url, session)
        if not data:
            img.decompose()
            continue

        ext = _EXT_MAP.get(mime, "jpg")
        local_name = f"images/img_{count:03d}.{ext}"
        count += 1

        epub_img = epub.EpubImage()
        epub_img.uid = f"img_{count}"
        epub_img.file_name = local_name
        epub_img.media_type = mime
        epub_img.content = data
        book.add_item(epub_img)

        img["src"] = local_name
        img.attrs = {k: v for k, v in img.attrs.items() if k in ("src", "alt", "title")}
        seen_urls.add(img_url)

    return count


def _extract_lead_image_url(original_html, base_url):
    """Return the article's lead/featured image URL from social meta tags.

    Sites almost universally set og:image (or twitter:image) to the exact
    hero image shown atop the article, regardless of where that image
    actually lives in the DOM. Readability frequently drops this image
    because it sits in a post header outside the extracted content block
    (e.g. a WordPress "featured image"), so this is a more reliable way to
    recover it than re-scanning the body.
    """
    orig = BeautifulSoup(original_html, "lxml")
    for selector in (
        {"property": "og:image"},
        {"property": "og:image:url"},
        {"name": "twitter:image"},
        {"name": "twitter:image:src"},
    ):
        tag = orig.find("meta", attrs=selector)
        if tag and tag.get("content"):
            return urljoin(base_url, tag["content"].strip())
    return None


def _embed_lead_image(img_url, base_url, session, book, seen_urls):
    """Download and wrap the lead image as a standalone <img> tag, or None on failure."""
    data, mime = _download_image(img_url, session)
    if not data:
        return None
    ext = _EXT_MAP.get(mime, "jpg")
    local_name = f"images/lead.{ext}"

    epub_img = epub.EpubImage()
    epub_img.uid = "img_lead"
    epub_img.file_name = local_name
    epub_img.media_type = mime
    epub_img.content = data
    book.add_item(epub_img)
    seen_urls.add(img_url)

    return BeautifulSoup(f'<img src="{local_name}" alt=""/>', "lxml").find("img")


def _recover_images(original_html, base_url, session, book, seen_urls=None):
    """Fallback: extract images from original page HTML when readability strips them.
    Returns (gallery_tag, n_images) where gallery_tag is a <div> ready to prepend."""
    orig = BeautifulSoup(original_html, "lxml")
    # Remove non-article chrome
    for sel in (
        "#mw-navigation", ".navbox", ".reflist", ".references", ".refbegin",
        ".mw-editsection", ".toc", "#toc", "#catlinks", ".printfooter",
        "nav", "header", "footer", ".sidebar", ".advertisement",
    ):
        for el in orig.select(sel):
            el.decompose()
    # Find main content area
    main = (
        orig.find(id="mw-content-text") or  # Wikipedia desktop
        orig.find(id="content") or           # Wikipedia mobile
        orig.find("article") or
        orig.find(attrs={"role": "main"}) or
        orig.body
    )
    if not main:
        return None, 0
    # Collect figure/thumb wrappers; fall back to bare img tags
    candidates = main.find_all("figure")
    if not candidates:
        candidates = main.find_all(
            "div", class_=lambda c: c and any(x in c for x in ("thumb", "image"))
        )
    if not candidates:
        candidates = main.find_all("img")
    if not candidates:
        return None, 0
    gallery = BeautifulSoup('<div class="image-gallery"></div>', "lxml").find("div")
    for el in list(candidates):
        gallery.append(el)
    n = _embed_images(gallery, base_url, session, book, seen_urls)
    return (gallery, n) if n > 0 else (None, 0)


def create_epub(title, content_html, source_url, session, output_path, original_html=None):
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("en")
    book.add_metadata("DC", "source", source_url)

    # Some CDNs reject image requests without a Referer matching the page
    # that embeds them, even though the page itself fetched fine.
    session.headers.update({"Referer": source_url})

    soup = BeautifulSoup(content_html, "lxml")

    # Strip Wikipedia-specific clutter: citation superscripts [1][2]..., edit links
    for el in soup.select("sup.reference, .mw-editsection, .noprint"):
        el.decompose()

    seen_urls = set()
    n_images = _embed_images(soup, source_url, session, book, seen_urls)

    # Readability often strips lazy-loaded images; recover them from the original HTML
    if n_images == 0 and original_html:
        gallery, n_images = _recover_images(original_html, source_url, session, book, seen_urls)
        if gallery:
            body = soup.find("body") or soup
            body.insert(0, gallery)

    # The article's lead/featured image often lives in a post header outside
    # the block readability extracted as "content" (e.g. a WordPress
    # "featured image"), so it silently never gets embedded above even when
    # every other image in the body does. og:image/twitter:image reliably
    # point at that exact image regardless of where it sits in the DOM.
    if original_html:
        lead_url = _extract_lead_image_url(original_html, source_url)
        if lead_url and lead_url not in seen_urls:
            lead_img = _embed_lead_image(lead_url, source_url, session, book, seen_urls)
            if lead_img is not None:
                body = soup.find("body") or soup
                body.insert(0, lead_img)
                n_images += 1

    # Source sites often wrap images in containers with a fixed pixel width
    # (e.g. Wikipedia's <div class="thumb" style="width:220px">). The <img>
    # tag's own size attributes are already stripped in _embed_images, but a
    # sized wrapper still clamps it below the CSS max-width:100% rule. Strip
    # sizing from every non-img element so images render at full width.
    for tag in soup.find_all(True):
        if tag.name == "img":
            continue
        for attr in ("style", "width", "height"):
            if attr in tag.attrs:
                del tag.attrs[attr]

    style = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=EPUB_CSS.encode("utf-8"),
    )
    book.add_item(style)

    escaped_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Use decode_contents() to get only the inner body HTML, avoiding nested <html><body>
    # tags that lxml adds when parsing with BeautifulSoup.
    body = soup.find("body")
    inner_html = body.decode_contents() if body else str(soup)
    chapter_html = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        "<head>"
        f"<title>{escaped_title}</title>"
        '<link rel="stylesheet" href="style.css" type="text/css"/>'
        "</head><body>"
        f"<h1>{escaped_title}</h1>"
        f'<p><small>Source: <a href="{source_url}">{source_url}</a></small></p>'
        f"{inner_html}"
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
    # GOOGLE_TOKEN_JSON env var is the durable, free-tier path: an OAuth token
    # captured once and pasted into the environment so it survives restarts.
    return bool(os.environ.get("GOOGLE_TOKEN_JSON")) or TOKEN_PATH.exists()


def _load_user_creds():
    """Load OAuth user credentials from the GOOGLE_TOKEN_JSON env var or token file."""
    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json:
        return Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if TOKEN_PATH.exists():
        return Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    return None


def get_drive_service(credentials_path=None):
    creds = _load_user_creds()

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.environ.get("GOOGLE_CREDENTIALS_JSON") or os.environ.get("GOOGLE_TOKEN_JSON"):
                raise RuntimeError(
                    "Not authenticated. Visit /auth in a browser to sign in to Google Drive."
                )
            creds_file = Path(credentials_path) if credentials_path else Path("credentials.json")
            if not creds_file.exists():
                raise FileNotFoundError(
                    f"'{creds_file}' not found. See README.md for Google Drive setup."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=0)

        # Best-effort token persistence (works on disk-backed deployments / local dev).
        # On free-tier Render this writes to /tmp and is lost on restart — which is
        # why GOOGLE_TOKEN_JSON is the recommended way to persist credentials there.
        try:
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        except OSError:
            pass

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
    n_images = create_epub(title, content_html, final_url, session, epub_path, original_html=html)
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
