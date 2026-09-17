#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Config:
    client_secrets_file: Path
    token_file: Path
    state_db: Path
    download_dir: Path
    oauth_port: int
    chunk_bytes: int
    max_retries: int
    default_privacy: str
    default_category_id: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        return cls(
            client_secrets_file=Path(os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "oauth-client.json")).expanduser(),
            token_file=Path(os.getenv("YOUTUBE_TOKEN_FILE", ".youtube-token.json")).expanduser(),
            state_db=Path(os.getenv("YOUTUBE_STATE_DB", ".terminxractor.sqlite3")).expanduser(),
            download_dir=Path(os.getenv("YOUTUBE_DOWNLOAD_DIR", "downloads")).expanduser(),
            oauth_port=int(os.getenv("YOUTUBE_OAUTH_PORT", "8080")),
            chunk_bytes=max(256 * 1024, int(os.getenv("YOUTUBE_UPLOAD_CHUNK_BYTES", str(8 * 1024 * 1024)))),
            max_retries=max(1, int(os.getenv("YOUTUBE_UPLOAD_MAX_RETRIES", "5"))),
            default_privacy=os.getenv("YOUTUBE_UPLOAD_DEFAULT_PRIVACY", "private"),
            default_category_id=os.getenv("YOUTUBE_UPLOAD_CATEGORY_ID", "22"),
        )


@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: list[str]
    category_id: str
    privacy_status: str
    publish_at: str | None = None

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("Title is required")
        if len(self.title) > 100:
            raise ValueError("Title must be at most 100 characters")
        if len(self.description) > 5000:
            raise ValueError("Description must be at most 5000 characters")
        if self.privacy_status not in {"private", "public", "unlisted"}:
            raise ValueError("Privacy status must be private, public, or unlisted")
        if not self.category_id.isdigit():
            raise ValueError("Category ID must be numeric")
        if self.publish_at:
            parsed = datetime.fromisoformat(self.publish_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("publishAt must include a timezone")
            self.privacy_status = "private"

    def api_body(self) -> dict[str, Any]:
        self.validate()
        snippet: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "categoryId": self.category_id,
        }
        status: dict[str, Any] = {"privacyStatus": self.privacy_status}
        if self.publish_at:
            status["publishAt"] = self.publish_at
        return {"snippet": snippet, "status": status}


def extract_youtube_video_id(value: str) -> str | None:
    candidate = value.strip()
    if VIDEO_ID_RE.fullmatch(candidate):
        return candidate
    parsed = urlparse(candidate)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "youtu.be":
        path_id = parsed.path.strip("/").split("/", 1)[0]
        return path_id if VIDEO_ID_RE.fullmatch(path_id) else None
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        return None
    query_id = parse_qs(parsed.query).get("v", [None])[0]
    if query_id and VIDEO_ID_RE.fullmatch(query_id):
        return query_id
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"} and VIDEO_ID_RE.fullmatch(parts[1]):
        return parts[1]
    return None


def parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(tag).strip() for tag in value if str(tag).strip()]
    return [tag.strip() for tag in str(value).split(",") if tag.strip()]


def load_metadata(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Metadata JSON must contain an object")
    return data


def build_metadata(args: argparse.Namespace, config: Config, file_path: Path, sidecar: dict[str, Any]) -> VideoMetadata:
    title = args.title if args.title is not None else str(sidecar.get("title") or file_path.stem)
    description = args.description if args.description is not None else str(sidecar.get("description") or "")
    tags = parse_tags(args.tags if args.tags is not None else sidecar.get("tags"))
    category_id = str(args.category_id if args.category_id is not None else sidecar.get("categoryId") or config.default_category_id)
    privacy_status = str(args.privacy_status if args.privacy_status is not None else sidecar.get("privacyStatus") or config.default_privacy)
    publish_at = args.publish_at if args.publish_at is not None else sidecar.get("publishAt")
    metadata = VideoMetadata(title, description, tags, category_id, privacy_status, publish_at)
    metadata.validate()
    return metadata


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_credentials(path: Path, credentials: Credentials) -> None:
    ensure_parent(path)
    path.write_text(credentials.to_json(), encoding="utf-8")
    path.chmod(0o600)


def load_credentials(config: Config, interactive: bool = True) -> Credentials:
    credentials: Credentials | None = None
    if config.token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(config.token_file), SCOPES)
    if credentials and credentials.valid:
        return credentials
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        save_credentials(config.token_file, credentials)
        return credentials
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    if refresh_token and client_id and client_secret:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        credentials.refresh(Request())
        save_credentials(config.token_file, credentials)
        return credentials
    if not interactive:
        raise RuntimeError("No usable YouTube OAuth token found; run `python youtube_reupload.py auth`")
    if not config.client_secrets_file.exists():
        raise FileNotFoundError(f"OAuth client file not found: {config.client_secrets_file}")
    flow = InstalledAppFlow.from_client_secrets_file(str(config.client_secrets_file), SCOPES)
    credentials = flow.run_local_server(port=config.oauth_port, access_type="offline", prompt="consent")
    save_credentials(config.token_file, credentials)
    return credentials


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_video_id TEXT UNIQUE,
            source_url TEXT,
            source_file TEXT NOT NULL,
            file_sha256 TEXT UNIQUE NOT NULL,
            metadata_json TEXT NOT NULL,
            youtube_video_id TEXT,
            status TEXT NOT NULL,
            session_uri TEXT,
            bytes_total INTEGER NOT NULL,
            bytes_uploaded INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def open_database(path: Path) -> sqlite3.Connection:
    ensure_parent(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    initialize_database(connection)
    return connection


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_job(connection: sqlite3.Connection, source_video_id: str | None, file_sha256: str) -> sqlite3.Row | None:
    if source_video_id:
        row = connection.execute("SELECT * FROM uploads WHERE source_video_id = ?", (source_video_id,)).fetchone()
        if row:
            return row
    return connection.execute("SELECT * FROM uploads WHERE file_sha256 = ?", (file_sha256,)).fetchone()


def create_or_update_job(
    connection: sqlite3.Connection,
    source_video_id: str | None,
    source_url: str | None,
    source_file: Path,
    file_sha256: str,
    metadata: VideoMetadata,
) -> sqlite3.Row:
    existing = find_job(connection, source_video_id, file_sha256)
    timestamp = now()
    metadata_json = json.dumps(metadata.api_body(), ensure_ascii=False, sort_keys=True)
    if existing:
        if existing["status"] == "completed":
            return existing
        connection.execute(
            """
            UPDATE uploads
            SET source_video_id = COALESCE(?, source_video_id), source_url = ?, source_file = ?, metadata_json = ?,
                bytes_total = ?, status = 'pending', last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (source_video_id, source_url, str(source_file), metadata_json, source_file.stat().st_size, timestamp, existing["id"]),
        )
        connection.commit()
        return connection.execute("SELECT * FROM uploads WHERE id = ?", (existing["id"],)).fetchone()
    connection.execute(
        """
        INSERT INTO uploads(source_video_id, source_url, source_file, file_sha256, metadata_json, status, bytes_total, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (source_video_id, source_url, str(source_file), file_sha256, metadata_json, source_file.stat().st_size, timestamp, timestamp),
    )
    connection.commit()
    return connection.execute("SELECT * FROM uploads WHERE id = last_insert_rowid()").fetchone()


def update_job(connection: sqlite3.Connection, job_id: int, **values: Any) -> None:
    if not values:
        return
    values["updated_at"] = now()
    assignments = ", ".join(f"{key} = ?" for key in values)
    connection.execute(f"UPDATE uploads SET {assignments} WHERE id = ?", (*values.values(), job_id))
    connection.commit()


def response_error(response: Any) -> str:
    try:
        payload = response.json()
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return response.text[:1000]


def retry_call(operation: Callable[[], Any], max_retries: int) -> Any:
    delay = 2.0
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = operation()
            if getattr(response, "status_code", 200) not in TRANSIENT_STATUS_CODES:
                return response
            last_error = RuntimeError(f"Transient HTTP {response.status_code}: {response_error(response)}")
        except Exception as exc:
            last_error = exc
        if attempt == max_retries:
            break
        time.sleep(delay)
        delay = min(delay * 2, 60.0)
    raise RuntimeError(f"Request failed after {max_retries + 1} attempts: {last_error}")


def read_server_offset(response: Any) -> int | None:
    value = response.headers.get("Range", "")
    match = re.search(r"bytes=0-(\d+)", value)
    return int(match.group(1)) + 1 if match else None


def query_upload_offset(session: AuthorizedSession, session_uri: str, total_bytes: int, max_retries: int) -> int:
    response = retry_call(
        lambda: session.put(session_uri, data=b"", headers={"Content-Length": "0", "Content-Range": f"bytes */{total_bytes}"}),
        max_retries,
    )
    if response.status_code == 308:
        return read_server_offset(response) or 0
    if response.status_code in {200, 201}:
        return total_bytes
    if response.status_code in {404, 410}:
        return -1
    raise RuntimeError(f"Unable to resume upload: HTTP {response.status_code}: {response_error(response)}")


def start_upload_session(
    session: AuthorizedSession,
    metadata: VideoMetadata,
    total_bytes: int,
    content_type: str,
    max_retries: int,
) -> str:
    response = retry_call(
        lambda: session.post(
            UPLOAD_ENDPOINT,
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=metadata.api_body(),
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(total_bytes),
                "X-Upload-Content-Type": content_type,
            },
        ),
        max_retries,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Unable to start upload: HTTP {response.status_code}: {response_error(response)}")
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError("YouTube did not return a resumable upload session URL")
    return location


def resumable_upload(
    connection: sqlite3.Connection,
    job: sqlite3.Row,
    metadata: VideoMetadata,
    config: Config,
    credentials: Credentials,
) -> str:
    source_file = Path(job["source_file"])
    total_bytes = source_file.stat().st_size
    content_type = mimetypes.guess_type(source_file.name)[0] or "video/mp4"
    session = AuthorizedSession(credentials)
    session_uri = job["session_uri"]
    offset = 0
    if session_uri:
        offset = query_upload_offset(session, session_uri, total_bytes, config.max_retries)
        if offset == -1:
            session_uri = None
            offset = 0
        elif offset == total_bytes:
            raise RuntimeError("Upload session reported completion without a video ID")
    if not session_uri:
        session_uri = start_upload_session(session, metadata, total_bytes, content_type, config.max_retries)
        update_job(connection, job["id"], session_uri=session_uri, status="uploading", bytes_uploaded=0)
    else:
        update_job(connection, job["id"], status="uploading", bytes_uploaded=offset)
    with source_file.open("rb") as handle:
        handle.seek(offset)
        while offset < total_bytes:
            chunk = handle.read(min(config.chunk_bytes, total_bytes - offset))
            if not chunk:
                raise RuntimeError("Source file ended before the expected upload size")
            start = offset
            end = start + len(chunk) - 1
            def send_chunk() -> Any:
                return session.put(
                    session_uri,
                    data=chunk,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{total_bytes}",
                        "Content-Type": content_type,
                    },
                )
            try:
                response = retry_call(send_chunk, config.max_retries)
            except Exception:
                offset = query_upload_offset(session, session_uri, total_bytes, config.max_retries)
                if offset == -1:
                    raise
                handle.seek(offset)
                update_job(connection, job["id"], bytes_uploaded=offset)
                continue
            if response.status_code in {200, 201}:
                payload = response.json()
                youtube_video_id = payload.get("id")
                if not youtube_video_id:
                    raise RuntimeError("YouTube completed the upload without returning a video ID")
                update_job(connection, job["id"], status="completed", youtube_video_id=youtube_video_id, bytes_uploaded=total_bytes, last_error=None)
                return youtube_video_id
            if response.status_code != 308:
                raise RuntimeError(f"Upload failed: HTTP {response.status_code}: {response_error(response)}")
            server_offset = read_server_offset(response)
            offset = server_offset if server_offset is not None else end + 1
            handle.seek(offset)
            update_job(connection, job["id"], bytes_uploaded=offset, status="uploading")
    raise RuntimeError("Upload ended without a completion response")


def download_source(url: str, config: Config) -> Path:
    video_id = extract_youtube_video_id(url)
    if not video_id:
        raise ValueError("source-url must be a valid YouTube video URL")
    config.download_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(config.download_dir / f"{video_id}.%(ext)s")
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--merge-output-format",
        "mp4",
        "--output",
        output_template,
        url,
    ]
    subprocess.run(command, check=True)
    candidates = [path for path in config.download_dir.glob(f"{video_id}.*") if path.suffix not in {".part", ".ytdl"}]
    if not candidates:
        raise FileNotFoundError("yt-dlp finished without producing a media file")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def upload_command(args: argparse.Namespace) -> int:
    config = Config.from_env()
    source_url = args.source_url
    source_video_id = args.source_video_id or (extract_youtube_video_id(source_url) if source_url else None)
    if source_url and not source_video_id:
        raise ValueError("Could not extract a YouTube video ID from source-url")
    source_file = Path(args.source_file).expanduser() if args.source_file else download_source(source_url, config)
    if not source_file.is_file():
        raise FileNotFoundError(f"Source file not found: {source_file}")
    sidecar = load_metadata(Path(args.metadata).expanduser() if args.metadata else None)
    metadata = build_metadata(args, config, source_file, sidecar)
    file_hash = sha256_file(source_file)
    connection = open_database(config.state_db)
    job = create_or_update_job(connection, source_video_id, source_url, source_file, file_hash, metadata)
    if job["status"] == "completed":
        print(json.dumps({"status": "duplicate", "youtube_video_id": job["youtube_video_id"], "source_video_id": job["source_video_id"]}))
        return 0
    update_job(connection, job["id"], status="uploading", attempt_count=job["attempt_count"] + 1, last_error=None)
    try:
        credentials = load_credentials(config)
        youtube_video_id = resumable_upload(connection, job, metadata, config, credentials)
        print(json.dumps({"status": "completed", "youtube_video_id": youtube_video_id, "source_video_id": source_video_id}))
        return 0
    except Exception as exc:
        update_job(connection, job["id"], status="failed", last_error=str(exc))
        raise
    finally:
        connection.close()


def auth_command() -> int:
    config = Config.from_env()
    credentials = load_credentials(config, interactive=True)
    print(json.dumps({"status": "authorized", "token_file": str(config.token_file), "scopes": list(credentials.scopes or SCOPES)}))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Authorized YouTube upload and resumable re-upload utility")
    subparsers = root.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth", help="Authorize the YouTube account with OAuth 2.0")
    upload = subparsers.add_parser("upload", help="Upload a local file or a publicly accessible source URL")
    sources = upload.add_mutually_exclusive_group(required=True)
    sources.add_argument("--source-file")
    sources.add_argument("--source-url")
    upload.add_argument("--source-video-id")
    upload.add_argument("--metadata")
    upload.add_argument("--title")
    upload.add_argument("--description")
    upload.add_argument("--tags")
    upload.add_argument("--category-id")
    upload.add_argument("--privacy-status", choices=["private", "public", "unlisted"])
    upload.add_argument("--publish-at")
    return root


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parser().parse_args(argv)
    try:
        if args.command == "auth":
            return auth_command()
        return upload_command(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
