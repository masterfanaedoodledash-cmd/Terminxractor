# Terminxractor

Terminxractor is a lightweight extractor and uploader utility for downloading a media source and re-uploading it to YouTube through the official YouTube Data API.

This repository intentionally keeps the workflow simple:
- download a source video URL or use a local extracted file
- normalize the output name
- upload to YouTube with OAuth credentials
- keep the upload private by default until the uploader confirms it is ready

Important: only upload content you own or are explicitly authorized to redistribute.

## Features
- Download a YouTube video using yt-dlp
- Upload a local media file to YouTube
- Set title, description, tags, and privacy status
- Uses environment variables for secrets

## Setup

1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Prepare YouTube OAuth credentials

- Create a Google Cloud project
- Enable the YouTube Data API v3
- Create OAuth client credentials
- Set up a refresh token with the `youtube.upload` scope
- Copy `.env.example` to `.env` and fill in the values

```bash
cp .env.example .env
```

## Example usage

Download a YouTube URL and upload it to YouTube:

```bash
python youtube_reupload.py \
  --source-url "https://www.youtube.com/watch?v=example" \
  --title "My Reupload" \
  --description "Uploaded via Terminxractor" \
  --tags "youtube,upload,tool" \
  --privacy-status private
```

Upload a local file directly:

```bash
python youtube_reupload.py \
  --source-file "downloads/example.mp4" \
  --title "Local File Reupload" \
  --description "Processed locally and uploaded via Terminxractor" \
  --tags "local,upload" \
  --privacy-status private
```

## Required environment variables

```env
YOUTUBE_CLIENT_ID=your_client_id
YOUTUBE_CLIENT_SECRET=your_client_secret
YOUTUBE_REFRESH_TOKEN=your_refresh_token
```

## Notes
- The script stores downloaded files in `downloads/`
- If you are reusing a video you do not own, ensure you have permission before uploading
- A public upload is possible, but private is safer when testing
