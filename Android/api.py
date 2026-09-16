from pathlib import Path
from threading import Thread

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
import yt_dlp


class TerminxractorApp(App):
    def build(self):
        self.title = "Terminxractor"
        layout = BoxLayout(orientation="vertical", padding=16, spacing=12)
        self.url = TextInput(hint_text="Source video URL", multiline=False, size_hint_y=None, height=48)
        self.title_input = TextInput(hint_text="Output title", multiline=False, size_hint_y=None, height=48)
        self.status = Label(text="Download content you own or are authorized to use.", halign="left")
        button = Button(text="Extract video", size_hint_y=None, height=52)
        button.bind(on_press=self.start_extract)
        layout.add_widget(Label(text="Terminxractor", font_size=28, size_hint_y=None, height=48))
        layout.add_widget(self.url)
        layout.add_widget(self.title_input)
        layout.add_widget(button)
        layout.add_widget(self.status)
        return layout

    def start_extract(self, *_args):
        url = self.url.text.strip()
        if not url:
            self.status.text = "Enter a source URL first."
            return
        self.status.text = "Extracting..."
        Thread(target=self.extract, args=(url,), daemon=True).start()

    def extract(self, url):
        try:
            output_dir = Path(self.user_data_dir) / "downloads"
            output_dir.mkdir(parents=True, exist_ok=True)
            options = {
                "format": "bestvideo+bestaudio/best",
                "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
                "merge_output_format": "mp4",
                "noplaylist": True,
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
            filename = info.get("_filename") or info.get("title", "video")
            Clock.schedule_once(lambda *_: setattr(self.status, "text", f"Saved: {filename}"))
        except Exception as error:
            message = str(error)
            Clock.schedule_once(lambda *_: setattr(self.status, "text", f"Error: {message}"))

if __name__ == "__main__":
    TerminxractorApp().run()
