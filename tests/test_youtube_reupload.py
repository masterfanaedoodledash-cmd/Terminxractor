import tempfile
import unittest
from pathlib import Path

from youtube_reupload import (
    Config,
    VideoMetadata,
    build_metadata,
    extract_youtube_video_id,
    initialize_database,
    read_server_offset,
)


class FakeResponse:
    def __init__(self, headers):
        self.headers = headers


class YouTubeReuploadTests(unittest.TestCase):
    def test_extracts_supported_youtube_ids(self):
        video_id = "abc12345678"
        self.assertEqual(extract_youtube_video_id(f"https://www.youtube.com/watch?v={video_id}"), video_id)
        self.assertEqual(extract_youtube_video_id(f"https://youtu.be/{video_id}"), video_id)
        self.assertEqual(extract_youtube_video_id(f"https://www.youtube.com/shorts/{video_id}"), video_id)
        self.assertIsNone(extract_youtube_video_id("https://example.com/abc12345678"))

    def test_metadata_supports_upload_fields(self):
        args = type("Args", (), {
            "title": "Title",
            "description": "Description",
            "tags": "one,two",
            "category_id": "22",
            "privacy_status": "unlisted",
            "publish_at": None,
        })()
        config = Config(Path("oauth-client.json"), Path("token.json"), Path("state.sqlite3"), Path("downloads"), 8080, 1024, 3, "private", "22")
        metadata = build_metadata(args, config, Path("video.mp4"), {})
        self.assertEqual(metadata.api_body()["snippet"]["title"], "Title")
        self.assertEqual(metadata.api_body()["snippet"]["tags"], ["one", "two"])
        self.assertEqual(metadata.api_body()["snippet"]["categoryId"], "22")
        self.assertEqual(metadata.api_body()["status"]["privacyStatus"], "unlisted")

    def test_publish_at_forces_private(self):
        metadata = VideoMetadata("Title", "", [], "22", "public", "2030-01-01T00:00:00Z")
        body = metadata.api_body()
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertEqual(body["status"]["publishAt"], "2030-01-01T00:00:00Z")

    def test_database_schema_has_duplicate_and_resume_state(self):
        import sqlite3

        connection = sqlite3.connect(":memory:")
        initialize_database(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(uploads)")}
        self.assertTrue({"source_video_id", "file_sha256", "youtube_video_id", "session_uri", "bytes_uploaded"}.issubset(columns))
        connection.close()

    def test_reads_resumable_upload_offset(self):
        self.assertEqual(read_server_offset(FakeResponse({"Range": "bytes=0-8388607"})), 8388608)
        self.assertIsNone(read_server_offset(FakeResponse({})))


if __name__ == "__main__":
    unittest.main()
