import sqlite3
import tempfile
import unittest
from pathlib import Path

from youtube_reupload import VideoMetadata, extract_youtube_video_id, initialize_database


class UploaderTests(unittest.TestCase):
    def test_extracts_supported_youtube_urls(self):
        video_id = "dQw4w9WgXcQ"
        self.assertEqual(extract_youtube_video_id(video_id), video_id)
        self.assertEqual(extract_youtube_video_id(f"https://www.youtube.com/watch?v={video_id}"), video_id)
        self.assertEqual(extract_youtube_video_id(f"https://youtu.be/{video_id}"), video_id)
        self.assertEqual(extract_youtube_video_id(f"https://www.youtube.com/shorts/{video_id}"), video_id)
        self.assertIsNone(extract_youtube_video_id("https://example.com/video"))

    def test_publish_at_forces_private(self):
        metadata = VideoMetadata("Title", "Description", ["tag"], "22", "public", "2030-01-01T00:00:00Z")
        metadata.validate()
        self.assertEqual(metadata.privacy_status, "private")
        self.assertEqual(metadata.api_body()["status"]["privacyStatus"], "private")

    def test_database_has_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            connection = sqlite3.connect(path)
            initialize_database(connection)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(uploads)")}
            self.assertIn("source_video_id", columns)
            self.assertIn("file_sha256", columns)
            connection.close()


if __name__ == "__main__":
    unittest.main()
