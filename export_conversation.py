#!/usr/bin/env python3
"""
Export a Claude Code conversation (JSONL session file) to EPUB,
then optionally upload to Google Drive.

Usage:
    python export_conversation.py                    # auto-detects current session
    python export_conversation.py SESSION.jsonl
    python export_conversation.py SESSION.jsonl --upload
    python export_conversation.py --list             # list recent sessions
"""

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

SESSIONS_DIR = Path.home() / ".claude" / "projects"


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def find_sessions():
    """Return all session JSONL files, newest first."""
    return sorted(
        SESSIONS_DIR.rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def current_session():
    """Return the most recently modified session file."""
    sessions = find_sessions()
    if not sessions:
        raise FileNotFoundError("No Claude Code sessions found.")
    return sessions[0]


# ---------------------------------------------------------------------------
# Parse conversation
# ---------------------------------------------------------------------------

def _text_from_content(content):
    """Extract plain text from a message content field."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(block.get("text", "").strip())
            # skip tool_use, tool_result, image blocks
        return "\n\n".join(p for p in parts if p)
    return ""


def load_conversation(path):
    """
    Parse a JSONL session file into a list of {"role": ..., "text": ...} dicts.
    Skips system messages, attachments, and empty turns.
    """
    turns = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = entry.get("type")
            if role not in ("user", "assistant"):
                continue

            msg = entry.get("message", {})
            text = _text_from_content(msg.get("content", ""))
            if text:
                turns.append({"role": role, "text": text})

    # Collapse consecutive same-role turns (can happen with tool calls)
    merged = []
    for t in turns:
        if merged and merged[-1]["role"] == t["role"]:
            merged[-1]["text"] += "\n\n" + t["text"]
        else:
            merged.append(dict(t))
    return merged


def conversation_title(turns):
    """Use the first user message (truncated) as the title."""
    for t in turns:
        if t["role"] == "user":
            first_line = t["text"].split("\n")[0].strip()
            return first_line[:80] or "Claude Conversation"
    return "Claude Conversation"


# ---------------------------------------------------------------------------
# EPUB rendering
# ---------------------------------------------------------------------------

_EPUB_CSS = """\
body {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 0 1.2em;
    color: #222;
}
h1 { font-size: 1.4em; font-family: Helvetica, Arial, sans-serif; }
h2 { font-size: 1.1em; font-family: Helvetica, Arial, sans-serif;
     color: #555; margin: 1.6em 0 0.3em; border-bottom: 1px solid #eee; padding-bottom: 2px; }
p  { margin: 0.6em 0; text-align: justify; }
pre {
    background: #f5f5f5;
    padding: 0.8em;
    font-size: 0.82em;
    font-family: "Courier New", monospace;
    white-space: pre-wrap;
    word-break: break-word;
    border-left: 3px solid #ccc;
    margin: 0.8em 0;
}
code {
    background: #f0f0f0;
    padding: 0.1em 0.3em;
    font-family: "Courier New", monospace;
    font-size: 0.85em;
}
blockquote {
    border-left: 3px solid #ccc;
    margin-left: 0;
    padding-left: 1em;
    color: #555;
}
ul, ol { margin: 0.5em 0; padding-left: 1.5em; }
li { margin: 0.2em 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 1em 0; }
strong { font-weight: bold; }
em     { font-style: italic; }
"""


def _markdown_to_html(text):
    """
    Minimal markdown → HTML for Kobo readability.
    Handles: code fences, inline code, bold, italic, headers, lists, hr, paragraphs.
    """
    html = []

    # Escape XML special chars first (we'll un-escape our own tags)
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = text.split("\n")
    i = 0
    in_list = None   # 'ul' or 'ol'
    in_pre = False
    pre_buf = []

    def flush_list():
        nonlocal in_list
        if in_list:
            html.append(f"</{in_list}>")
            in_list = None

    while i < len(lines):
        line = lines[i]

        # Code fence
        if line.strip().startswith("```"):
            if not in_pre:
                flush_list()
                in_pre = True
                pre_buf = []
            else:
                html.append("<pre>" + esc("\n".join(pre_buf)) + "</pre>")
                in_pre = False
                pre_buf = []
            i += 1
            continue

        if in_pre:
            pre_buf.append(line)
            i += 1
            continue

        stripped = line.strip()

        # Blank line
        if not stripped:
            flush_list()
            i += 1
            continue

        # HR
        if re.match(r'^[-*_]{3,}$', stripped):
            flush_list()
            html.append("<hr/>")
            i += 1
            continue

        # Headers
        m = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if m:
            flush_list()
            level = min(len(m.group(1)) + 1, 6)  # shift h1→h2 since h1 is the title
            html.append(f"<h{level}>{_inline(esc(m.group(2)))}</h{level}>")
            i += 1
            continue

        # Ordered list
        m = re.match(r'^\d+\.\s+(.*)', stripped)
        if m:
            if in_list != 'ol':
                flush_list()
                html.append("<ol>")
                in_list = 'ol'
            html.append(f"<li>{_inline(esc(m.group(1)))}</li>")
            i += 1
            continue

        # Unordered list
        m = re.match(r'^[-*+]\s+(.*)', stripped)
        if m:
            if in_list != 'ul':
                flush_list()
                html.append("<ul>")
                in_list = 'ul'
            html.append(f"<li>{_inline(esc(m.group(1)))}</li>")
            i += 1
            continue

        # Plain paragraph
        flush_list()
        html.append(f"<p>{_inline(esc(stripped))}</p>")
        i += 1

    if in_pre and pre_buf:
        html.append("<pre>" + esc("\n".join(pre_buf)) + "</pre>")
    flush_list()

    return "\n".join(html)


def _inline(s):
    """Apply inline markdown: bold, italic, inline code."""
    s = re.sub(r'`([^`]+)`',        r'<code>\1</code>', s)
    s = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', s)
    s = re.sub(r'\*\*(.+?)\*\*',    r'<strong>\1</strong>', s)
    s = re.sub(r'\*(.+?)\*',        r'<em>\1</em>', s)
    s = re.sub(r'___(.+?)___',      r'<strong><em>\1</em></strong>', s)
    s = re.sub(r'__(.+?)__',        r'<strong>\1</strong>', s)
    s = re.sub(r'_([^_]+)_',        r'<em>\1</em>', s)
    return s


def build_html_body(turns):
    parts = []
    for t in turns:
        label = "You" if t["role"] == "user" else "Claude"
        parts.append(f"<h2>{label}</h2>")
        parts.append(_markdown_to_html(t["text"]))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# EPUB file construction
# ---------------------------------------------------------------------------

def write_epub(title, body_html, output_path):
    try:
        from ebooklib import epub
    except ImportError:
        _write_epub_manual(title, body_html, output_path)
        return

    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("en")

    style = epub.EpubItem(uid="style", file_name="style.css",
                          media_type="text/css", content=_EPUB_CSS.encode())
    book.add_item(style)

    esc_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"'
        ' "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        f'<title>{esc_title}</title>'
        '<link rel="stylesheet" href="style.css" type="text/css"/>'
        f'</head><body><h1>{esc_title}</h1>{body_html}</body></html>'
    )

    chapter = epub.EpubHtml(title=title, file_name="conversation.xhtml", lang="en")
    chapter.content = xhtml.encode()
    chapter.add_item(style)
    book.add_item(chapter)

    book.toc = (epub.Link("conversation.xhtml", title, "conv"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(output_path), book)


def _write_epub_manual(title, body_html, output_path):
    """Fallback: build EPUB manually using only stdlib (zipfile)."""
    import zipfile
    uid = str(uuid.uuid4())
    esc = title.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"'
        ' "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
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
        '<item id="c" href="conversation.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="s" href="style.css" media-type="text/css"/>'
        '<item id="n" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
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
        '<content src="conversation.xhtml"/>'
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
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/toc.ncx", ncx)
        z.writestr("OEBPS/style.css", _EPUB_CSS)
        z.writestr("OEBPS/conversation.xhtml", xhtml)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def sanitise(s):
    return re.sub(r"\s+", "_", re.sub(r"[^\w\s-]", "", s).strip())[:60] or "conversation"


def main():
    parser = argparse.ArgumentParser(description="Export a Claude conversation to EPUB")
    parser.add_argument("session", nargs="?", help="Path to .jsonl session file (default: most recent)")
    parser.add_argument("--upload", action="store_true", help="Upload to Google Drive after creating EPUB")
    parser.add_argument("--output", "-o", help="Output EPUB path")
    parser.add_argument("--list", action="store_true", help="List recent sessions and exit")
    args = parser.parse_args()

    if args.list:
        sessions = find_sessions()
        for i, s in enumerate(sessions[:10]):
            turns = load_conversation(s)
            title = conversation_title(turns)
            print(f"  {i+1}. {title[:60]}")
            print(f"     {s}")
        return

    session_path = Path(args.session) if args.session else current_session()
    print(f"Session: {session_path.name}")

    turns = load_conversation(session_path)
    if not turns:
        print("No conversation turns found in that session.")
        sys.exit(1)

    title = conversation_title(turns)
    print(f"Title:   {title}")
    print(f"Turns:   {len(turns)}")

    output = Path(args.output) if args.output else Path(sanitise(title) + ".epub")
    body_html = build_html_body(turns)
    write_epub(title, body_html, output)
    size_kb = output.stat().st_size // 1024
    print(f"EPUB:    {output}  ({size_kb} KB)")

    if args.upload:
        try:
            import converter
            config = converter.load_config()
            folder_id = config.get("folder_id")
            print("Uploading to Google Drive...")
            service = converter.get_drive_service()
            result = converter.upload_to_drive(service, output, folder_id)
            print(f"Uploaded: {result['name']}")
            if result.get("webViewLink"):
                print(f"Link:     {result['webViewLink']}")
        except Exception as e:
            print(f"Drive upload failed: {e}")
            print("(EPUB was still saved locally)")


if __name__ == "__main__":
    main()
