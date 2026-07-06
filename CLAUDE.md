# Send to Kobo — Claude Instructions

## Core capability
I can research topics, fetch web pages, compile content, convert to EPUB,
and deliver directly to the user's Kobo e-reader via Google Drive — all
without any external service setup beyond what's already connected.

---

## Google Drive — Kobo folder
- **Folder name:** Rakuten Kobo
- **Folder ID:** `1FjOoP-IC_16RJubJlzfVYhoJ2qx9OYq1`
- **MCP server:** `mcp__c5a19a6b-0b68-4632-9037-d9ea9f458ce6`

---

## How to send an EPUB to Kobo (the complete workflow)

### Step 1 — Build the EPUB file

**From a session (export this conversation):**
```bash
python export_conversation.py              # current session
python export_conversation.py --list       # pick a past session
```

**From fetched web content or research:**
Write the content to a temp markdown or HTML file, then:
```bash
python make_epub.py "Title" content.md
```
`make_epub.py` prints the output path. It handles markdown, plain text,
and HTML (uses readability if available, otherwise strips tags).

**From a URL (full fetch + image extraction):**
```bash
python send_to_kobo.py https://example.com/article --no-upload
```

### Step 2 — Base64 encode the EPUB
```bash
python3 -c "import base64; print(base64.b64encode(open('FILE.epub','rb').read()).decode())"
```

### Step 3 — Upload via MCP
Load tool schema first:
```
ToolSearch: select:mcp__c5a19a6b-0b68-4632-9037-d9ea9f458ce6__create_file
```
Then call:
```json
{
  "title": "Filename.epub",
  "contentMimeType": "application/epub+zip",
  "parentId": "1FjOoP-IC_16RJubJlzfVYhoJ2qx9OYq1",
  "base64Content": "<base64 string>"
}
```

---

## Trigger phrases to watch for

When the user says any of these, run the full workflow above:
- "send to Kobo", "put on my Kobo", "save to Kobo"
- "research X and send to Kobo"
- "fetch [URL] and send to Kobo"
- "export this conversation to Kobo"
- "send to Drive" / "save to my Drive" (use Kobo folder unless told otherwise)

---

## Fetching web content

Use the `WebFetch` tool (load via ToolSearch if needed) to retrieve URLs.
For research tasks, fetch multiple sources, synthesise, then compile into
a single EPUB with sections per source or topic.

---

## Scripts in this repo

| Script | Purpose |
|---|---|
| `make_epub.py` | EPUB from any title + content file. No deps needed. |
| `export_conversation.py` | EPUB from a Claude Code session JSONL file. |
| `send_to_kobo.py` | CLI: fetch URL → EPUB → Drive (requires OAuth setup). |
| `converter.py` | Shared library used by `send_to_kobo.py`, `app.py`, and `mcp_server.py`. |
| `app.py` | Flask web server for iOS Share Sheet workflow. |
| `mcp_server.py` | Remote MCP server exposing `send_to_kobo(title, content)` as a custom Claude connector — lets any Claude client (web/desktop/iOS/Android) push content straight to Kobo without fetching/rendering a page. See README.md "Step 5". |
