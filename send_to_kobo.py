#!/usr/bin/env python3
"""CLI — convert web articles to EPUB and send to Google Drive for Kobo reading."""

import argparse
import sys
from pathlib import Path

import converter
from converter import load_config, save_config


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_convert(args):
    config = load_config()
    folder_id = args.folder_id or config.get("folder_id")

    print(f"Fetching: {args.url}")
    try:
        html, final_url, session = converter.fetch_page(args.url)
    except Exception as e:
        print(f"Error fetching page: {e}")
        sys.exit(1)

    print("Extracting article content...")
    title, content_html = converter.extract_content(html, final_url)
    print(f"Title: {title}")

    epub_path = Path(args.output) if args.output else Path(converter.sanitize_filename(title) + ".epub")

    print("Creating EPUB (downloading images)...")
    n_images = converter.create_epub(title, content_html, final_url, session, epub_path)
    size_kb = epub_path.stat().st_size // 1024
    print(f"EPUB saved: {epub_path}  ({size_kb} KB, {n_images} image(s))")

    if args.no_upload:
        return

    print("Authenticating with Google Drive...")
    try:
        drive = converter.get_drive_service(getattr(args, "credentials", None))
    except Exception as e:
        print(f"Authentication error: {e}")
        sys.exit(1)

    dest = f" → folder {folder_id}" if folder_id else " → My Drive root"
    print(f"Uploading{dest}...")
    try:
        result = converter.upload_to_drive(drive, epub_path, folder_id)
        print(f"Uploaded: {result['name']}  (id: {result['id']})")
        if "webViewLink" in result:
            print(f"View: {result['webViewLink']}")
    except Exception as e:
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
        print(f"\nConfig file: {converter.CONFIG_PATH}")


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

    cfg = subparsers.add_parser("config", help="View or set default configuration")
    cfg.add_argument("--folder-id", metavar="ID", help="Set the default Google Drive folder ID")
    cfg.add_argument("--clear-folder", action="store_true", help="Remove the saved folder ID")

    conv = subparsers.add_parser("convert", help="Convert a URL to EPUB and upload (default)")
    conv.add_argument("url", help="Web page URL to convert")
    conv.add_argument("--folder-id", metavar="ID", help="Google Drive folder ID (overrides config)")
    conv.add_argument("--output", "-o", metavar="FILE", help="Local filename for the EPUB")
    conv.add_argument("--no-upload", action="store_true", help="Save locally only, skip Drive upload")
    conv.add_argument("--credentials", metavar="FILE", help="Path to credentials.json", default=None)

    # Allow `send_to_kobo.py URL` without typing 'convert'
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
