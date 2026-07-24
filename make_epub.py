#!/usr/bin/env python3
"""
Create an EPUB from a title + content (HTML, markdown, or plain text).
Used when building EPUBs from fetched web content or research gathered
during a conversation, before uploading to Google Drive via MCP.

Usage:
    python make_epub.py "Title" content.md
    python make_epub.py "Title" content.html
    echo "some text" | python make_epub.py "Title" -
    python make_epub.py "Title" content.md --output custom.epub
"""

import argparse
import re
import sys
import uuid
import zipfile
from pathlib import Path

CSS = """\
body{font-family:Georgia,"Times New Roman",serif;font-size:1em;
     line-height:1.6;margin:0 1.2em;color:#222}
h1{font-size:1.5em;font-family:Helvetica,Arial,sans-serif}
h2,h3{font-family:Helvetica,Arial,sans-serif;color:#111;margin:1.4em 0 .3em}
p{margin:.7em 0;text-align:justify}
pre{background:#f5f5f5;padding:.8em;font-size:.82em;
    font-family:"Courier New",monospace;white-space:pre-wrap;
    word-break:break-word;border-left:3px solid #ccc;margin:.8em 0}
code{background:#f0f0f0;padding:.1em .3em;
     font-family:"Courier New",monospace;font-size:.85em}
blockquote{border-left:3px solid #ccc;margin-left:0;
           padding-left:1em;color:#555}
ul,ol{margin:.5em 0;padding-left:1.5em}
li{margin:.2em 0}
hr{border:none;border-top:1px solid #ddd;margin:1em 0}
strong{font-weight:bold}em{font-style:italic}
a{color:inherit;text-decoration:underline}
img{max-width:100%;height:auto;display:block;margin:1em auto}
"""


# ---------------------------------------------------------------------------
# Minimal markdown → XHTML (no deps)
# ---------------------------------------------------------------------------

def _esc(s):
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _inline(s):
    s = re.sub(r'`([^`]+)`',          r'<code>\1</code>', s)
    s = re.sub(r'\*\*\*(.+?)\*\*\*',  r'<strong><em>\1</em></strong>', s)
    s = re.sub(r'\*\*(.+?)\*\*',      r'<strong>\1</strong>', s)
    s = re.sub(r'\*([^*]+)\*',        r'<em>\1</em>', s)
    s = re.sub(r'___(.+?)___',        r'<strong><em>\1</em></strong>', s)
    s = re.sub(r'__(.+?)__',          r'<strong>\1</strong>', s)
    s = re.sub(r'_([^_\n]+)_',        r'<em>\1</em>', s)
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', s)
    return s

def markdown_to_xhtml(text):
    html, pre_buf, in_pre, in_list = [], [], False, None

    def flush_list():
        nonlocal in_list
        if in_list:
            html.append(f"</{in_list}>")
            in_list = None

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if not in_pre:
                flush_list()
                in_pre = True
                pre_buf = []
            else:
                html.append("<pre>" + _esc("\n".join(pre_buf)) + "</pre>")
                in_pre = False
                pre_buf = []
            continue
        if in_pre:
            pre_buf.append(line)
            continue

        s = line.strip()
        if not s:
            flush_list()
            continue
        if re.match(r'^[-*_]{3,}$', s):
            flush_list(); html.append("<hr/>"); continue

        m = re.match(r'^(#{1,6})\s+(.*)', s)
        if m:
            flush_list()
            lvl = min(len(m.group(1)) + 1, 6)
            html.append(f"<h{lvl}>{_inline(_esc(m.group(2)))}</h{lvl}>")
            continue
        m = re.match(r'^\d+\.\s+(.*)', s)
        if m:
            if in_list != 'ol': flush_list(); html.append("<ol>"); in_list = 'ol'
            html.append(f"<li>{_inline(_esc(m.group(1)))}</li>"); continue
        m = re.match(r'^[-*+]\s+(.*)', s)
        if m:
            if in_list != 'ul': flush_list(); html.append("<ul>"); in_list = 'ul'
            html.append(f"<li>{_inline(_esc(m.group(1)))}</li>"); continue

        flush_list()
        html.append(f"<p>{_inline(_esc(s))}</p>")

    if in_pre and pre_buf:
        html.append("<pre>" + _esc("\n".join(pre_buf)) + "</pre>")
    flush_list()
    return "\n".join(html)


def html_to_xhtml(raw_html):
    """Light clean-up of HTML for embedding in EPUB."""
    # Try lxml+readability for clean extraction if available
    try:
        from readability import Document
        from bs4 import BeautifulSoup
        doc = Document(raw_html)
        soup = BeautifulSoup(doc.summary(html_partial=True), "lxml")
        # Strip scripts/styles
        for tag in soup(["script","style","nav","header","footer"]):
            tag.decompose()
        return str(soup)
    except Exception:
        pass
    # Fallback: strip tags crudely and treat as plain text
    plain = re.sub(r'<[^>]+>', ' ', raw_html)
    plain = re.sub(r'[ \t]+', ' ', plain)
    return markdown_to_xhtml(plain)


# ---------------------------------------------------------------------------
# EPUB writer (stdlib only)
# ---------------------------------------------------------------------------

def write_epub(title, body_html, output_path):
    uid = str(uuid.uuid4())
    esc = _esc(title)
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        f'<title>{esc}</title>'
        '<link rel="stylesheet" href="style.css" type="text/css"/>'
        f'</head><body><h1>{esc}</h1>{body_html}</body></html>'
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid" version="2.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title>{esc}</dc:title>'
        f'<dc:identifier id="uid">{uid}</dc:identifier>'
        '<dc:language>en</dc:language></metadata>'
        '<manifest>'
        '<item id="c" href="content.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="s" href="style.css"     media-type="text/css"/>'
        '<item id="n" href="toc.ncx"       media-type="application/x-dtbncx+xml"/>'
        '</manifest>'
        '<spine toc="n"><itemref idref="c"/></spine></package>'
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="{uid}"/></head>'
        f'<docTitle><text>{esc}</text></docTitle>'
        '<navMap><navPoint id="n1" playOrder="1">'
        f'<navLabel><text>{esc}</text></navLabel>'
        '<content src="content.xhtml"/>'
        '</navPoint></navMap></ncx>'
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf"'
        ' media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf",      opf)
        z.writestr("OEBPS/toc.ncx",          ncx)
        z.writestr("OEBPS/style.css",         CSS)
        z.writestr("OEBPS/content.xhtml",    xhtml)


def sanitise(s):
    return re.sub(r"\s+","_", re.sub(r"[^\w\s-]","",s).strip())[:60] or "output"


def main():
    parser = argparse.ArgumentParser(description="Create EPUB from a content file")
    parser.add_argument("title",   help="Title of the EPUB")
    parser.add_argument("content", help="Path to content file (.md/.txt/.html) or - for stdin")
    parser.add_argument("--output", "-o", help="Output .epub path (default: <title>.epub)")
    args = parser.parse_args()

    if args.content == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.content).read_text(encoding="utf-8")

    ext = Path(args.content).suffix.lower() if args.content != "-" else ".md"
    if ext in (".html", ".htm"):
        body = html_to_xhtml(raw)
    else:
        body = markdown_to_xhtml(raw)

    out = Path(args.output) if args.output else Path(sanitise(args.title) + ".epub")
    write_epub(args.title, body, out)
    print(out)   # print path so callers can capture it


if __name__ == "__main__":
    main()
