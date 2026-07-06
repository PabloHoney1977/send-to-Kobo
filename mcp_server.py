#!/usr/bin/env python3
"""
Remote MCP server exposing a single tool: send_to_kobo.

Lets Claude call this tool directly from any client (web, desktop, iOS,
Android) once added as a custom connector, so a conversation or piece of
writing can be turned into an EPUB and uploaded to the user's Kobo Google
Drive folder without ever fetching or rendering a page — the content comes
straight from the calling model's own context.

Run locally:
    python mcp_server.py

Deploy: see render.yaml (runs this under uvicorn as a second Render service).

Auth: there's no login flow. Access is controlled by keeping the server URL
secret — set MCP_SECRET_PATH to a random string and only share the full URL
(https://.../<secret>/mcp) with your own Claude connector settings, the same
way you'd treat a private calendar or webhook URL.
"""

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))
import make_epub
import converter

DEFAULT_FOLDER_ID = "1FjOoP-IC_16RJubJlzfVYhoJ2qx9OYq1"  # Rakuten Kobo folder


def _secret_path() -> str:
    secret = os.environ.get("MCP_SECRET_PATH", "").strip("/")
    return f"/{secret}/mcp" if secret else "/mcp"


mcp = FastMCP(
    name="send-to-kobo",
    instructions=(
        "Converts text or markdown content into an EPUB and uploads it to "
        "the user's Kobo Google Drive folder. Use the send_to_kobo tool "
        "when the user asks to send a conversation, article, or piece of "
        "writing to their Kobo e-reader."
    ),
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
    streamable_http_path=_secret_path(),
    stateless_http=True,
)


@mcp.tool()
def send_to_kobo(title: str, content: str) -> str:
    """Convert markdown/plain-text content into an EPUB and upload it to the user's Kobo Drive folder.

    Args:
        title: Title for the resulting book (used as the EPUB title and filename).
        content: The full text to include, in markdown or plain text.
    """
    if not content or not content.strip():
        return "Error: content is empty — nothing to send."

    folder_id = os.environ.get("DRIVE_FOLDER_ID", DEFAULT_FOLDER_ID)
    out_path = Path(f"/tmp/{make_epub.sanitise(title)}.epub")

    body_html = make_epub.markdown_to_xhtml(content)
    make_epub.write_epub(title, body_html, out_path)

    try:
        service = converter.get_drive_service()
        result = converter.upload_to_drive(service, out_path, folder_id)
    except Exception as e:
        return f"Error: EPUB was created but the Drive upload failed — {e}"
    finally:
        out_path.unlink(missing_ok=True)

    link = result.get("webViewLink", "")
    suffix = f" {link}" if link else ""
    return f"Sent '{title}' to your Kobo Drive folder.{suffix}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
