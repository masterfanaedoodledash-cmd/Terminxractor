# Terminxractor

Terminxractor is an authorized YouTube upload utility for videos you own or are explicitly allowed to redistribute. It can download a publicly accessible source, upload a local MP4 through the official YouTube Data API v3, and safely resume interrupted uploads.

## Implemented

- OAuth 2.0 authorization with a local callback and refresh-token persistence
- Title, description, tags, category, privacy status, and scheduled publish metadata
- Duplicate prevention by source YouTube ID and SHA-256 file hash
- SQLite upload state with YouTube upload IDs and resumable session URLs
- Chunked resumable uploads with retry/backoff for transient failures
- Download-to-upload flow for publicly accessible source URLs
- Secrets and tokens supplied through environment variables or ignored local files

The utility does not bypass private, removed, terminated, regional, or otherwise restricted videos. Use it only for content you own or are authorized to upload.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

In Google Cloud Console:

1. Create or select a project.
2. Enable **YouTube Data API v3**.
3. Create an OAuth client for a desktop application.
4. Download the client JSON to the path configured by `YOUTUBE_CLIENT_SECRETS_FILE`.

Copy the environment template and adjust paths if needed:

```bash
cp .env.example .env
```

Run OAuth authorization once:

```bash
python youtube_reupload.py auth
```

The token is saved locally with restrictive permissions and is ignored by Git.

## Upload a local file

```bash
python youtube_reupload.py upload \
  --source-file downloads/example.mp4 \
  --source-video-id SOURCE_VIDEO_ID \
  --title "Authorized upload" \
  --description "Uploaded through the YouTube Data API" \
  --tags "example,authorized" \
  --category-id 22 \
  --privacy-status private
```

## Upload a publicly accessible source URL

```bash
python youtube_reupload.py upload \
  --source-url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --title "Authorized upload" \
  --privacy-status private
```

For repeatable metadata, use a JSON sidecar:

```json
{
  "title": "Authorized upload",
  "description": "Description",
  "tags": ["example", "authorized"],
  "categoryId": "22",
  "privacyStatus": "private"
}
```

```bash
python youtube_reupload.py upload \
  --source-file downloads/example.mp4 \
  --metadata metadata.json
```

If an upload is interrupted, run the same command again. The SQLite state file reuses the resumable YouTube session when possible and skips completed duplicates.

## Environment variables

See `.env.example`:

- `YOUTUBE_CLIENT_SECRETS_FILE`
- `YOUTUBE_TOKEN_FILE`
- `YOUTUBE_STATE_DB`
- `YOUTUBE_DOWNLOAD_DIR`
- `YOUTUBE_OAUTH_PORT`
- `YOUTUBE_UPLOAD_CHUNK_BYTES`
- `YOUTUBE_UPLOAD_MAX_RETRIES`
- `YOUTUBE_UPLOAD_DEFAULT_PRIVACY`
- `YOUTUBE_UPLOAD_CATEGORY_ID`

Legacy `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` values are also accepted for an existing authorized setup, but client secrets and refresh tokens must never be committed.
