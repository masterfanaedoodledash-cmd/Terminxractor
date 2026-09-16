#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
import yt_dlp

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DEFAULT_DOWNLOAD_DIR = Path("downloads")

def load_environment():
    load_dotenv()


def create_oauth_credentials():
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        raise ValueError(
            "Missing required YouTube authentication variables. "
            "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN in your environment or .env file."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def ensure_download_dir():
    DEFAULT_DOWNLOAD_DIR.mkdir(exist_ok=True, parents=True)


def download_source_video(source_url: str, output_dir: Path = DEFAULT_DOWNLOAD_DIR) -> str:
    ensure_download_dir()
    output_path = output_dir / "%(title)s.%(ext)s"

    ydl_options = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": str(output_path),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": False,
        "nocheckcertificate": True,
    }

    print(f"Downloading: {source_url}")
    with yt_dlp.YoutubeDL(ydl_options) as ydl:
        info = ydl.extract_info(source_url, download=True)
        title = info.get("title", "downloaded-video")
        ext = info.get("ext", "mp4")
        filename = f"{title}.{ext}"
        candidate = output_dir / filename
        if candidate.exists():
            return str(candidate)

        # Some extractors name files differently when audio/video are merged.
        for path in output_dir.iterdir():
            if path.is_file() and path.name.startswith(title):
                return str(path)

        raise FileNotFoundError(f"Downloaded file for {source_url} was not found in {output_dir}")


def upload_video(file_path: str, title: str, description: str, tags: list[str], privacy_status: str):
    creds = create_oauth_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    print(json.dumps({"kind": "youtube.video.uploaded", "id": response.get("id")}, indent=2))
    return response


def parse_args():
    parser = argparse.ArgumentParser(description="Download a source media file and upload it to YouTube.")
    parser.add_argument("--source-url", help="Source video URL to download before uploading.")
    parser.add_argument("--source-file", help="Local file path to upload directly without downloading.")
    parser.add_argument("--title", required=True, help="YouTube title for the upload.")
    parser.add_argument("--description", default="Uploaded via Terminxractor.", help="Description to use on YouTube.")
    parser.add_argument("--tags", default="", help="Comma-separated tags for the uploaded video.")
    parser.add_argument("--privacy-status", default="private", choices=["private", "public", "unlisted"], help="YouTube privacy setting.")
    return parser.parse_args()


def main():
    load_environment()
    args = parse_args()

    if not args.source_url and not args.source_file:
        print("Either --source-url or --source-file must be provided.", file=sys.stderr)
        return 2

    if args.source_url and args.source_file:
        print("Provide only one of --source-url or --source-file.", file=sys.stderr)
        return 2

    try:
        if args.source_url:
            file_path = download_source_video(args.source_url)
        else:
            file_path = args.source_file

        file_path = str(Path(file_path).expanduser().resolve())
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Video file does not exist: {file_path}")

        tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        upload_video(file_path, args.title, args.description, tags, args.privacy_status)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
