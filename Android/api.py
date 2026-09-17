import json
import re
from pathlib import Path
from threading import Thread

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
import yt_dlp


def safe_filename(value):
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", value or "video").strip(" .")
    return cleaned[:120] or "video"


def video_id_from_info(info):
    return str(info.get("id") or "")


def build_metadata(info, source_url, output_path, title_override, description, tags, category_id, privacy_status):
    title = title_override.strip() or str(info.get("title") or output_path.stem)
    normalized_tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    return {
        "title": title,
        "description": description.strip(),
        "tags": normalized_tags,
        "categoryId": category_id.strip() or "22",
        "privacyStatus": privacy_status.strip() or "private",
        "sourceUrl": source_url,
        "sourceVideoId": video_id_from_info(info),
        "file": str(output_path),
    }


class TerminxractorApp(App):
    def build(self):
        self.title = "Terminxractor"
        scroll = ScrollView()
        layout = BoxLayout(orientation="vertical", padding=16, spacing=10, size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))

        layout.add_widget(Label(text="Terminxractor", font_size=28, size_hint_y=None, height=48))
        self.url = self.field(layout, "Source video URL")
        self.title_input = self.field(layout, "Upload title (optional)")
        self.description_input = self.field(layout, "Description (optional)", multiline=True, height=100)
        self.tags_input = self.field(layout, "Tags, comma separated (optional)")
        self.category_input = self.field(layout, "YouTube category ID", text="22")
        self.privacy_input = self.field(layout, "Privacy status", text="private")
        self.status = Label(
            text="Use only media you own or are authorized to redistribute.",
            halign="left",
            valign="top",
            size_hint_y=None,
            height=64,
        )
        self.status.bind(texture_size=lambda instance, size: setattr(instance, "height", max(64, size[1])))
        button = Button(text="Extract and save metadata", size_hint_y=None, height=52)
        button.bind(on_press=self.start_extract)

        layout.add_widget(button)
        layout.add_widget(self.status)
        scroll.add_widget(layout)
        return scroll

    def field(self, layout, hint, text="", multiline=False, height=48):
        widget = TextInput(hint_text=hint, text=text, multiline=multiline, size_hint_y=None, height=height)
        layout.add_widget(widget)
        return widget

    def start_extract(self, *_args):
        url = self.url.text.strip()
        if not url:
            self.status.text = "Enter a source URL first."
            return
        self.status.text = "Extracting the best available single-file format..."
        Thread(target=self.extract, args=(url,), daemon=True).start()

    def update_status(self, message):
        Clock.schedule_once(lambda *_: setattr(self.status, "text", message))

    def extract(self, url):
        try:
            output_dir = Path(self.user_data_dir) / "downloads"
            output_dir.mkdir(parents=True, exist_ok=True)
            options = {
                "format": "best[ext=mp4]/best",
                "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
                downloaded_path = Path(downloader.prepare_filename(info))
            if not downloaded_path.exists():
                candidates = sorted(output_dir.glob(f"{safe_filename(info.get('title'))}.*"), key=lambda path: path.stat().st_mtime, reverse=True)
                if not candidates:
                    raise FileNotFoundError("The downloaded media file was not found.")
                downloaded_path = candidates[0]
            metadata = build_metadata(
                info,
                url,
                downloaded_path,
                self.title_input.text,
                self.description_input.text,
                self.tags_input.text,
                self.category_input.text,
                self.privacy_input.text,
            )
            metadata_path = downloaded_path.with_suffix(".json")
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            self.update_status(f"Saved media:\n{downloaded_path}\nMetadata:\n{metadata_path}")
        except Exception as error:
            self.update_status(f"Error: {error}")


if __name__ == "__main__":
    TerminxractorApp().run()
