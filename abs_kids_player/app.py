from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")

from gi.repository import Gdk, Gio, GLib, Gst, Gtk, Pango  # noqa: E402

from .api import AudiobookshelfClient, AudiobookshelfError, client_from_config
from .config import CONFIG_DIR, AppConfig, load_config, save_config
from .models import Book, PlaybackSession


COVER_CACHE_DIR = CONFIG_DIR / "covers"
PROGRESS_SYNC_SECONDS = 15
SEEK_STEP_SECONDS = 30


CSS = """
window {
  background: #f4f1ea;
  color: #20242a;
}

.setup {
  margin: 48px;
}

.title {
  font-size: 34px;
  font-weight: 800;
}

.subtitle {
  font-size: 18px;
  color: #4d5763;
}

.tile {
  background: #ffffff;
  border: 2px solid #d9d3c7;
  border-radius: 8px;
  padding: 14px;
}

.tile:hover {
  border-color: #2e7d79;
}

.book-title {
  font-size: 18px;
  font-weight: 800;
}

.book-author {
  font-size: 14px;
  color: #59616d;
}

.player {
  background: #20242a;
  color: #ffffff;
  padding: 18px;
}

.player-title {
  font-size: 22px;
  font-weight: 800;
}

.player-author {
  color: #d6e2e1;
}

.control-button {
  min-width: 84px;
  min-height: 64px;
  font-size: 24px;
  font-weight: 800;
}

.primary-button {
  background: #2e7d79;
  color: #ffffff;
}

.danger-text {
  color: #9b2c2c;
}
"""


def main() -> None:
    Gst.init(None)
    app = KidsPlayerApp()
    app.run()


class KidsPlayerApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="dev.codex.AbsKidsPlayer",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.config = load_config()
        self.window: Gtk.ApplicationWindow | None = None
        self.client: AudiobookshelfClient | None = None
        self.library_id = ""
        self.books: list[Book] = []
        self.player: PlayerController | None = None

        self.stack: Gtk.Stack | None = None
        self.error_label: Gtk.Label | None = None
        self.flow: Gtk.FlowBox | None = None
        self.now_title: Gtk.Label | None = None
        self.now_author: Gtk.Label | None = None
        self.now_cover: Gtk.Picture | None = None
        self.play_pause_button: Gtk.Button | None = None
        self.progress_scale: Gtk.Scale | None = None
        self.progress_label: Gtk.Label | None = None
        self.sync_source_id = 0
        self.updating_progress = False

    def do_activate(self) -> None:
        self.install_css()
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("Chapter Player for Audiobookshelf")
        self.window.set_default_size(1024, 600)
        self.window.connect("close-request", self.on_close)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.build_setup_view(), "setup")
        self.stack.add_named(self.build_library_view(), "library")
        self.window.set_child(self.stack)
        self.window.present()

        if self.config.is_ready:
            self.connect_and_load()
        else:
            self.stack.set_visible_child_name("setup")

    def install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def build_setup_view(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        outer.add_css_class("setup")
        outer.set_valign(Gtk.Align.CENTER)
        outer.set_halign(Gtk.Align.CENTER)

        title = Gtk.Label(label="Chapter Player for Audiobookshelf")
        title.add_css_class("title")
        title.set_wrap(True)
        outer.append(title)

        subtitle = Gtk.Label(label="Connect this Raspberry Pi to a kid-friendly Audiobookshelf account.")
        subtitle.add_css_class("subtitle")
        subtitle.set_wrap(True)
        outer.append(subtitle)

        server_entry = Gtk.Entry()
        server_entry.set_placeholder_text("Server URL")
        server_entry.set_text(self.config.server_url)
        server_entry.set_size_request(520, 52)
        outer.append(server_entry)

        token_entry = Gtk.PasswordEntry()
        token_entry.set_placeholder_text("API token")
        token_entry.set_text(self.config.token)
        token_entry.set_size_request(520, 52)
        outer.append(token_entry)

        library_entry = Gtk.Entry()
        library_entry.set_placeholder_text("Library ID (optional)")
        library_entry.set_text(self.config.library_id)
        library_entry.set_size_request(520, 52)
        outer.append(library_entry)

        self.error_label = Gtk.Label()
        self.error_label.add_css_class("danger-text")
        self.error_label.set_wrap(True)
        outer.append(self.error_label)

        button = Gtk.Button(label="Connect")
        button.add_css_class("primary-button")
        button.set_size_request(220, 58)
        button.connect(
            "clicked",
            lambda _button: self.save_settings_and_load(
                server_entry.get_text(),
                token_entry.get_text(),
                library_entry.get_text(),
            ),
        )
        outer.append(button)
        return outer

    def build_library_view(self) -> Gtk.Widget:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header.set_margin_top(18)
        header.set_margin_bottom(12)
        header.set_margin_start(18)
        header.set_margin_end(18)

        title = Gtk.Label(label="Choose a book")
        title.add_css_class("title")
        title.set_hexpand(True)
        title.set_xalign(0)
        header.append(title)

        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda _button: self.connect_and_load())
        header.append(refresh)

        settings = Gtk.Button(label="Settings")
        settings.connect("clicked", lambda _button: self.show_setup())
        header.append(settings)
        root.append(header)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(5)
        self.flow.set_min_children_per_line(2)
        self.flow.set_row_spacing(18)
        self.flow.set_column_spacing(18)
        self.flow.set_margin_start(18)
        self.flow.set_margin_end(18)
        self.flow.set_margin_bottom(18)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.flow)
        scroller.set_vexpand(True)
        root.append(scroller)

        root.append(self.build_player_bar())
        return root

    def build_player_bar(self) -> Gtk.Widget:
        player = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        player.add_css_class("player")

        self.now_cover = Gtk.Picture()
        self.now_cover.set_size_request(96, 96)
        self.now_cover.set_content_fit(Gtk.ContentFit.COVER)
        player.append(self.now_cover)

        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        details.set_hexpand(True)
        self.now_title = Gtk.Label(label="Pick a book to start")
        self.now_title.add_css_class("player-title")
        self.now_title.set_xalign(0)
        self.now_title.set_ellipsize(Pango.EllipsizeMode.END)
        details.append(self.now_title)

        self.now_author = Gtk.Label(label="")
        self.now_author.add_css_class("player-author")
        self.now_author.set_xalign(0)
        details.append(self.now_author)

        self.progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.progress_scale.set_draw_value(False)
        self.progress_scale.connect("value-changed", self.on_progress_change)
        details.append(self.progress_scale)

        self.progress_label = Gtk.Label(label="0:00 / 0:00")
        self.progress_label.set_xalign(0)
        details.append(self.progress_label)
        player.append(details)

        back = Gtk.Button(label="-30")
        back.add_css_class("control-button")
        back.connect("clicked", lambda _button: self.seek_relative(-SEEK_STEP_SECONDS))
        player.append(back)

        self.play_pause_button = Gtk.Button(label="Play")
        self.play_pause_button.add_css_class("control-button")
        self.play_pause_button.add_css_class("primary-button")
        self.play_pause_button.connect("clicked", lambda _button: self.toggle_playback())
        player.append(self.play_pause_button)

        forward = Gtk.Button(label="+30")
        forward.add_css_class("control-button")
        forward.connect("clicked", lambda _button: self.seek_relative(SEEK_STEP_SECONDS))
        player.append(forward)
        return player

    def save_settings_and_load(self, server_url: str, token: str, library_id: str) -> None:
        self.config = replace(
            self.config,
            server_url=server_url.strip(),
            token=token.strip(),
            refresh_token="",
            library_id=library_id.strip(),
        )
        save_config(self.config)
        self.connect_and_load()

    def show_setup(self) -> None:
        if self.stack:
            self.stack.set_visible_child_name("setup")

    def connect_and_load(self) -> None:
        if self.error_label:
            self.error_label.set_text("Loading...")
        threading.Thread(target=self.load_books_worker, daemon=True).start()

    def load_books_worker(self) -> None:
        try:
            client = client_from_config(self.config, AudiobookshelfClient)
            library_id = client.choose_library_id(self.config.library_id)
            books = client.get_books(library_id)
        except AudiobookshelfError as error:
            GLib.idle_add(self.show_error, str(error))
            return

        GLib.idle_add(self.show_books, client, library_id, books)

    def show_error(self, message: str) -> bool:
        if self.error_label:
            self.error_label.set_text(message)
        if self.stack:
            self.stack.set_visible_child_name("setup")
        return False

    def show_books(self, client: AudiobookshelfClient, library_id: str, books: list[Book]) -> bool:
        self.client = client
        self.library_id = library_id
        self.books = books
        if self.error_label:
            self.error_label.set_text("")
        if self.stack:
            self.stack.set_visible_child_name("library")
        self.render_books()
        return False

    def render_books(self) -> None:
        if not self.flow:
            return

        child = self.flow.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.flow.remove(child)
            child = next_child

        for book in self.books:
            self.flow.append(self.create_book_tile(book))

    def create_book_tile(self, book: Book) -> Gtk.Widget:
        button = Gtk.Button()
        button.add_css_class("tile")
        button.set_size_request(170, 276)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cover = Gtk.Picture()
        cover.set_size_request(140, 190)
        cover.set_content_fit(Gtk.ContentFit.COVER)
        cover.set_hexpand(True)
        box.append(cover)

        title = Gtk.Label(label=book.title)
        title.add_css_class("book-title")
        title.set_wrap(True)
        title.set_max_width_chars(18)
        title.set_justify(Gtk.Justification.CENTER)
        box.append(title)

        author = Gtk.Label(label=book.author)
        author.add_css_class("book-author")
        author.set_wrap(True)
        author.set_max_width_chars(18)
        author.set_justify(Gtk.Justification.CENTER)
        box.append(author)

        button.set_child(box)
        button.connect("clicked", lambda _button: self.play_book(book))
        self.load_cover_async(book.cover_url, cover)
        return button

    def play_book(self, book: Book, start_over: bool = False) -> None:
        if not self.client:
            return
        self.set_now_playing_text(f"Loading {book.title}", book.author)
        threading.Thread(target=self.play_book_worker, args=(book, start_over), daemon=True).start()

    def play_book_worker(self, book: Book, start_over: bool = False) -> None:
        try:
            assert self.client is not None
            session = self.client.start_playback(book.id, start_over=start_over)
        except AudiobookshelfError as error:
            GLib.idle_add(self.set_now_playing_text, "Could not play book", str(error))
            return
        GLib.idle_add(self.start_session, session)

    def start_session(self, session: PlaybackSession) -> bool:
        if self.player:
            self.player.stop()
        assert self.client is not None
        self.player = PlayerController(session, self.client, self.on_player_tick, self.on_play_state_changed)
        self.set_now_playing_text(session.title, session.author)
        if self.progress_scale:
            self.progress_scale.set_range(0, max(session.duration, 1))
        if self.now_cover:
            self.load_cover_async(session.cover_url, self.now_cover)
        self.player.play()
        self.ensure_progress_timer()
        return False

    def set_now_playing_text(self, title: str, author: str) -> bool:
        if self.now_title:
            self.now_title.set_text(title)
        if self.now_author:
            self.now_author.set_text(author)
        return False

    def load_cover_async(self, url: str, picture: Gtk.Picture) -> None:
        threading.Thread(target=self.load_cover_worker, args=(url, picture), daemon=True).start()

    def load_cover_worker(self, url: str, picture: Gtk.Picture) -> None:
        try:
            COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            suffix = ".jpg"
            cache_name = hashlib.sha256(url.encode("utf-8")).hexdigest() + suffix
            cache_path = COVER_CACHE_DIR / cache_name
            if not cache_path.exists():
                with urlopen(url, timeout=20) as response:
                    cache_path.write_bytes(response.read())
        except Exception:
            return
        GLib.idle_add(self.set_picture_file, picture, cache_path)

    def set_picture_file(self, picture: Gtk.Picture, path: Path) -> bool:
        picture.set_file(Gio.File.new_for_path(str(path)))
        return False

    def toggle_playback(self) -> None:
        if self.player:
            self.player.toggle()

    def seek_relative(self, seconds: float) -> None:
        if self.player:
            self.player.seek_global(self.player.current_time + seconds)

    def on_progress_change(self, scale: Gtk.Scale) -> None:
        if self.player and not self.updating_progress:
            self.player.seek_global(scale.get_value())

    def on_player_tick(self, current_time: float, duration: float) -> None:
        if self.progress_scale:
            self.updating_progress = True
            self.progress_scale.set_value(current_time)
            self.updating_progress = False
        if self.progress_label:
            self.progress_label.set_text(f"{format_time(current_time)} / {format_time(duration)}")

    def on_play_state_changed(self, is_playing: bool) -> None:
        if self.play_pause_button:
            self.play_pause_button.set_label("Pause" if is_playing else "Play")

    def ensure_progress_timer(self) -> None:
        if not self.sync_source_id:
            self.sync_source_id = GLib.timeout_add_seconds(PROGRESS_SYNC_SECONDS, self.sync_progress)

    def sync_progress(self) -> bool:
        if self.player:
            self.player.sync_progress()
            return True
        self.sync_source_id = 0
        return False

    def on_close(self, *_args: object) -> bool:
        if self.player:
            self.player.sync_progress()
            self.player.stop()
        return False


class PlayerController:
    def __init__(
        self,
        session: PlaybackSession,
        client: AudiobookshelfClient,
        on_tick: Callable[[float, float], None],
        on_play_state_changed: Callable[[bool], None],
    ) -> None:
        self.session = session
        self.client = client
        self.on_tick = on_tick
        self.on_play_state_changed = on_play_state_changed
        self.playbin = Gst.ElementFactory.make("playbin", "abs-player")
        if self.playbin is None:
            raise RuntimeError("Could not create GStreamer playbin.")
        self.track_index = self.track_index_for_time(session.current_time)
        self.current_time = session.current_time
        self.is_playing = False
        self.tick_source_id = 0

        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

    def track_index_for_time(self, current_time: float) -> int:
        for index, track in enumerate(self.session.tracks):
            if track.start_offset <= current_time < track.start_offset + track.duration:
                return index
        return max(0, len(self.session.tracks) - 1)

    @property
    def current_track(self):
        return self.session.tracks[self.track_index]

    def play(self) -> None:
        self.load_current_track()
        self.playbin.set_state(Gst.State.PLAYING)
        self.is_playing = True
        self.on_play_state_changed(True)
        if not self.tick_source_id:
            self.tick_source_id = GLib.timeout_add_seconds(1, self.tick)

    def load_current_track(self) -> None:
        track = self.current_track
        self.playbin.set_state(Gst.State.NULL)
        self.playbin.set_property("uri", track.url)
        self.playbin.set_state(Gst.State.PAUSED)
        offset_seconds = max(0, self.current_time - track.start_offset)
        self.seek_track(offset_seconds)

    def toggle(self) -> None:
        if self.is_playing:
            self.playbin.set_state(Gst.State.PAUSED)
            self.is_playing = False
        else:
            self.playbin.set_state(Gst.State.PLAYING)
            self.is_playing = True
        self.on_play_state_changed(self.is_playing)
        self.sync_progress()

    def seek_track(self, seconds: float) -> None:
        self.playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(seconds * Gst.SECOND),
        )

    def seek_global(self, current_time: float) -> None:
        self.current_time = min(max(current_time, 0), self.session.duration)
        new_index = self.track_index_for_time(self.current_time)
        if new_index != self.track_index:
            was_playing = self.is_playing
            self.track_index = new_index
            self.load_current_track()
            self.playbin.set_state(Gst.State.PLAYING if was_playing else Gst.State.PAUSED)
        else:
            self.seek_track(self.current_time - self.current_track.start_offset)
        self.on_tick(self.current_time, self.session.duration)
        self.sync_progress()

    def tick(self) -> bool:
        success, position = self.playbin.query_position(Gst.Format.TIME)
        if success:
            self.current_time = self.current_track.start_offset + position / Gst.SECOND
            self.on_tick(self.current_time, self.session.duration)
        return True

    def sync_progress(self) -> None:
        try:
            self.client.update_progress(self.session.library_item_id, self.current_time, self.session.duration)
        except AudiobookshelfError:
            pass

    def advance_within_session(self) -> bool:
        if self.track_index + 1 >= len(self.session.tracks):
            self.current_time = self.session.duration
            self.sync_progress()
            self.stop()
            return False
        self.track_index += 1
        self.current_time = self.current_track.start_offset
        self.load_current_track()
        self.playbin.set_state(Gst.State.PLAYING)
        return True

    def on_bus_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        if message.type == Gst.MessageType.EOS:
            self.advance_within_session()
        elif message.type == Gst.MessageType.ERROR:
            self.stop()

    def stop(self) -> None:
        if self.tick_source_id:
            GLib.source_remove(self.tick_source_id)
            self.tick_source_id = 0
        self.playbin.set_state(Gst.State.NULL)
        self.is_playing = False
        self.on_play_state_changed(False)


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
