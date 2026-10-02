from __future__ import annotations

import unittest

from abs_kids_player.config import LIBRARY_SORT_AUTHOR
from abs_kids_player.models import AudioTrack, Book, Chapter, PlaybackSession
from abs_kids_player.player_state import LastPlaybackState
from abs_kids_player.rotary_ui import (
    ApplianceMenu,
    BluetoothDevicesFrame,
    BluetoothMenuFrame,
    ChapterConfirmFrame,
    CommandType,
    HomeFrame,
    PLAYING_PLAY_INDEX,
    PlayingFrame,
    ResumeChoiceFrame,
    Screen,
    SleepConfirmFrame,
    StartupResumeFrame,
    VolumeFrame,
    author_line,
    author_section_letter,
    author_sort_text,
    marquee_text,
    power_off_resume_time,
    title_sort_text,
    title_section_letter,
    volume_bar,
)


BOOKS = [
    Book("book-1", "The Wild Robot", "Peter Brown", 1000, ""),
    Book("book-2", "Matilda", "Roald Dahl", 1000, ""),
]

BOOKS_WITH_HISTORY = [
    Book("book-1", "The Wild Robot", "Peter Brown", 1000, "", current_time=120, progress=0.12),
    Book("book-2", "Matilda", "Roald Dahl", 1000, ""),
]


def make_session() -> PlaybackSession:
    return PlaybackSession(
        id="session-1",
        library_item_id="book-1",
        title="The Wild Robot",
        author="Peter Brown",
        duration=300,
        current_time=65,
        cover_url="",
        tracks=[AudioTrack(1, 0, 300, "http://example.test/book.mp3", "Track")],
        chapters=[
            Chapter(1, "Ch 1", 0, 60),
            Chapter(2, "Ch 2", 60, 120),
            Chapter(3, "Ch 3", 120, 300),
        ],
    )


def make_long_title_session() -> PlaybackSession:
    session = make_session()
    session.title = "The Wild Robot Escapes Again and Again"
    return session


def make_short_title_session() -> PlaybackSession:
    session = make_session()
    session.title = "Matilda"
    return session


def make_long_chapter_session() -> PlaybackSession:
    session = make_session()
    session.chapters[1].title = "Chapter Two With A Very Long Name"
    return session


class ApplianceMenuTest(unittest.TestCase):
    def test_library_scrolls_titles_and_authors(self) -> None:
        menu = ApplianceMenu(BOOKS)
        frame = menu.render()
        self.assertIsInstance(frame, HomeFrame)
        self.assertEqual(frame.top, "The Wild Robot")
        self.assertEqual(frame.bottom, "By Peter Brown")

        menu.rotate_nav(1)

        frame = menu.render()
        self.assertIsInstance(frame, HomeFrame)
        self.assertEqual(frame.top, "Matilda")
        self.assertEqual(frame.bottom, "By Roald Dahl")

    def test_spoken_selection_debounces_books_and_names_selected_controls(self) -> None:
        menu = ApplianceMenu(BOOKS_WITH_HISTORY)

        book_selection = menu.spoken_selection()
        self.assertEqual(book_selection.text, "The Wild Robot")
        self.assertGreater(book_selection.delay_seconds, 0)

        menu.click_nav()
        self.assertEqual(menu.spoken_selection().text, "Continue")
        self.assertEqual(menu.spoken_selection().delay_seconds, 0)

        menu.set_session(make_session())
        self.assertEqual(menu.spoken_selection().text, "Pause")
        menu.rotate_nav(-1)
        self.assertEqual(menu.spoken_selection().text, "Previous chapter")

    def test_library_marks_podcasts_on_home_frame(self) -> None:
        menu = ApplianceMenu([Book("podcast:yoto-daily", "Yoto Daily", "Yoto", 0, "")])
        frame = menu.render()

        self.assertIsInstance(frame, HomeFrame)
        self.assertTrue(frame.is_podcast)

    def test_library_shows_series_position_on_home_frame(self) -> None:
        book = Book(
            "book-1",
            "The Wild Robot Escapes",
            "Peter Brown",
            1000,
            "",
            series_name="The Wild Robot",
            series_sequence="2",
            series_total=3,
        )

        frame = ApplianceMenu([book]).render()

        self.assertIsInstance(frame, HomeFrame)
        self.assertEqual(frame.title, "The Wild Robot: The Wild Robot Escapes")
        self.assertEqual(frame.series_position, "2/3")

    def test_series_title_is_not_prefixed_twice(self) -> None:
        book = Book(
            "book-1",
            "The Wild Robot: The Wild Robot Escapes",
            "Peter Brown",
            1000,
            "",
            series_name="The Wild Robot",
        )

        self.assertEqual(book.display_title, "The Wild Robot: The Wild Robot Escapes")

    def test_library_scroll_shows_section_letter_then_fades(self) -> None:
        menu = ApplianceMenu(BOOKS)

        menu.rotate_nav(1)
        frame = menu.render()

        self.assertIsInstance(frame, HomeFrame)
        self.assertEqual(frame.section_letter, "M")
        self.assertEqual(frame.section_letter_fill, 255)

        menu.tick_section_letter(0.9)
        held = menu.render()
        self.assertIsInstance(held, HomeFrame)
        self.assertEqual(held.section_letter, "M")
        self.assertEqual(held.section_letter_fill, 255)

        menu.tick_section_letter(0.3)
        fading = menu.render()
        self.assertIsInstance(fading, HomeFrame)
        self.assertEqual(fading.section_letter, "M")
        self.assertLess(fading.section_letter_fill, 255)
        self.assertGreater(fading.section_letter_fill, 0)

        menu.tick_section_letter(1.0)
        faded = menu.render()
        self.assertIsInstance(faded, HomeFrame)
        self.assertEqual(faded.section_letter, "")
        self.assertEqual(faded.section_letter_fill, 0)

    def test_author_order_scroll_uses_last_name_section_letter(self) -> None:
        menu = ApplianceMenu(BOOKS, library_sort_mode=LIBRARY_SORT_AUTHOR)

        menu.rotate_nav(1)

        self.assertEqual(menu.render().section_letter, "D")

    def test_title_click_without_history_opens_home_start_choice(self) -> None:
        menu = ApplianceMenu(BOOKS)

        commands = menu.click_nav()

        self.assertEqual(commands, [])
        self.assertEqual(menu.screen, Screen.RESUME_CHOICE)
        frame = menu.render()
        self.assertIsInstance(frame, ResumeChoiceFrame)
        self.assertEqual(frame.top, "The Wild Robot")
        self.assertEqual(frame.options, ("Home", "Start"))
        self.assertEqual(frame.selected_index, 1)
        self.assertEqual(frame.bottom, "Home [Start]")

    def test_startup_resume_prompt_defaults_to_continue(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_startup_resume(LastPlaybackState("book-1", "The Hobbit", current_time=90))

        frame = menu.render()

        self.assertIsInstance(frame, StartupResumeFrame)
        self.assertEqual(frame.title, "The Hobbit")
        self.assertEqual(frame.bottom, "[Continue] Home")

    def test_startup_resume_continue_plays_saved_book(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_startup_resume(LastPlaybackState("book-1", "The Hobbit", current_time=90))

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.PLAY_BOOK)
        self.assertEqual(command.book_id, "book-1")
        self.assertFalse(command.start_over)
        self.assertEqual(command.resume_time, 80)
        self.assertEqual(menu.screen, Screen.LIBRARY)

    def test_power_off_resume_time_rewinds_ten_seconds_without_going_negative(self) -> None:
        self.assertEqual(power_off_resume_time(90), 80)
        self.assertEqual(power_off_resume_time(5), 0)

    def test_startup_resume_home_clears_saved_book_and_returns_home(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_startup_resume(LastPlaybackState("book-1", "The Hobbit", current_time=90))

        menu.rotate_nav(1)
        frame = menu.render()
        self.assertIsInstance(frame, StartupResumeFrame)
        self.assertEqual(frame.bottom, "Continue [Home]")
        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.CLEAR_LAST_PLAYBACK)
        self.assertEqual(menu.screen, Screen.LIBRARY)

    def test_title_click_with_history_opens_continue_start_over_choice(self) -> None:
        menu = ApplianceMenu(BOOKS_WITH_HISTORY)
        commands = menu.click_nav()

        self.assertEqual(menu.screen, Screen.RESUME_CHOICE)
        self.assertEqual(commands, [])
        frame = menu.render()
        self.assertIsInstance(frame, ResumeChoiceFrame)
        self.assertEqual(frame.top, "The Wild Robot")
        self.assertEqual(frame.options, ("Home", "Continue", "Start over"))
        self.assertEqual(frame.selected_index, 1)
        self.assertEqual(frame.bottom, "Home [Continue] Start over")

    def test_continue_is_default_when_history_exists(self) -> None:
        menu = ApplianceMenu(BOOKS_WITH_HISTORY)
        menu.click_nav()

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.PLAY_BOOK)
        self.assertEqual(command.book_id, "book-1")
        self.assertFalse(command.start_over)
        self.assertEqual(command.resume_time, 120)

    def test_start_is_default_without_history(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.click_nav()

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.PLAY_BOOK)
        self.assertEqual(command.book_id, "book-1")
        self.assertTrue(command.start_over)

    def test_start_over_can_be_selected_when_history_exists(self) -> None:
        menu = ApplianceMenu(BOOKS_WITH_HISTORY)
        menu.click_nav()

        menu.rotate_nav(1)
        frame = menu.render()
        self.assertIsInstance(frame, ResumeChoiceFrame)
        self.assertEqual(frame.selected_index, 2)
        self.assertEqual(frame.bottom, "Home Continue [Start over]")

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.PLAY_BOOK)
        self.assertEqual(command.book_id, "book-1")
        self.assertTrue(command.start_over)

    def test_home_can_be_selected_from_resume_choice(self) -> None:
        menu = ApplianceMenu(BOOKS_WITH_HISTORY)
        menu.click_nav()

        menu.rotate_nav(-1)
        frame = menu.render()
        self.assertIsInstance(frame, ResumeChoiceFrame)
        self.assertEqual(frame.selected_index, 0)
        self.assertEqual(frame.bottom, "[Home] Continue Start over")

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.HOME)
        self.assertEqual(menu.screen, Screen.LIBRARY)

    def test_playing_click_toggles_play_pause(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        self.assertEqual(menu.playing_action_index, PLAYING_PLAY_INDEX)
        frame = menu.render()
        self.assertIsInstance(frame, PlayingFrame)
        self.assertEqual(frame.actions, ("Home", "Prev", "Pause", "Next"))
        self.assertEqual(frame.selected_index, PLAYING_PLAY_INDEX)
        self.assertEqual(frame.bottom, "Home Prev [Pause] Next")

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.TOGGLE_PLAYBACK)

    def test_playing_title_scrolls_when_long(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_long_chapter_session())

        first = menu.render()
        menu.tick_title_scroll()
        second = menu.render()

        self.assertIsInstance(first, PlayingFrame)
        self.assertEqual(first.chapter_text, "Chapter Two With A Very Long Name")
        self.assertEqual(first.remaining_text, "-3:55")
        self.assertIsInstance(second, PlayingFrame)
        self.assertEqual(second.chapter_text, first.chapter_text)
        self.assertEqual(second.remaining_text, first.remaining_text)
        self.assertNotEqual(second.title_scroll_px, first.title_scroll_px)

    def test_playing_title_timed_scroll_waits_then_matches_home_speed(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_long_chapter_session())

        menu.update_title_scroll(1.9, delay_seconds=2.0, pixels_per_second=16.0)
        waiting = menu.render()
        menu.update_title_scroll(1.1, delay_seconds=2.0, pixels_per_second=16.0)
        scrolling = menu.render()

        self.assertIsInstance(waiting, PlayingFrame)
        self.assertIsInstance(scrolling, PlayingFrame)
        self.assertEqual(waiting.title_scroll_px, 0)
        self.assertEqual(scrolling.title_scroll_px, 16)

    def test_playing_title_does_not_scroll_when_short(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_short_title_session())

        first = menu.render()
        menu.tick_title_scroll()
        second = menu.render()

        self.assertIsInstance(first, PlayingFrame)
        self.assertIsInstance(second, PlayingFrame)
        self.assertEqual(first.chapter_text, second.chapter_text)
        self.assertEqual(first.remaining_text, second.remaining_text)
        self.assertEqual(first.chapter_text, "Ch 2")
        self.assertEqual(first.remaining_text, "-3:55")

    def test_playing_remaining_time_counts_down(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        first = menu.render()
        menu.update_playback(70, is_playing=True)
        second = menu.render()

        self.assertIsInstance(first, PlayingFrame)
        self.assertIsInstance(second, PlayingFrame)
        self.assertEqual(first.remaining_text, "-3:55")
        self.assertEqual(second.remaining_text, "-3:50")

    def test_playing_action_row_stops_at_edges(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        menu.rotate_nav(1)
        menu.rotate_nav(1)
        menu.rotate_nav(1)

        self.assertIn("[Next]", menu.render().bottom)

        menu.rotate_nav(1)

        self.assertIn("[Next]", menu.render().bottom)

        menu.rotate_nav(-1)
        menu.rotate_nav(-1)
        menu.rotate_nav(-1)
        menu.rotate_nav(-1)

        self.assertIn("[Home]", menu.render().bottom)

    def test_selecting_next_chapter_requires_confirmation(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        menu.rotate_nav(1)
        menu.click_nav()

        self.assertEqual(menu.screen, Screen.CHAPTER_CONFIRM)
        frame = menu.render()
        self.assertIsInstance(frame, ChapterConfirmFrame)
        self.assertEqual(frame.top, "Are you sure you want to listen to the next chapter?")
        self.assertEqual(frame.bottom, "[Yes] No")

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.SEEK_CHAPTER)
        self.assertEqual(command.chapter_index, 2)
        self.assertEqual(command.seek_time, 120)

    def test_chapter_confirmation_can_be_cancelled(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        menu.rotate_nav(-1)
        menu.click_nav()
        frame = menu.render()
        self.assertIsInstance(frame, ChapterConfirmFrame)
        self.assertEqual(frame.top, "Are you sure you want to listen to the previous chapter?")
        menu.rotate_nav(1)
        commands = menu.click_nav()

        self.assertEqual(commands, [])
        self.assertEqual(menu.screen, Screen.PLAYING)

    def test_chapter_confirmation_left_and_right_choose_yes_no(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        menu.rotate_nav(1)
        menu.click_nav()
        menu.rotate_nav(-1)
        yes = menu.render()
        menu.rotate_nav(1)
        no = menu.render()

        self.assertIsInstance(yes, ChapterConfirmFrame)
        self.assertIsInstance(no, ChapterConfirmFrame)
        self.assertEqual(yes.bottom, "[Yes] No")
        self.assertEqual(no.bottom, "Yes [No]")

    def test_chapter_confirmation_times_out_to_play_screen(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        menu.rotate_nav(1)
        menu.click_nav()

        self.assertFalse(menu.tick_chapter_confirm_timeout(4.9))
        self.assertEqual(menu.screen, Screen.CHAPTER_CONFIRM)
        self.assertTrue(menu.tick_chapter_confirm_timeout(0.1))
        self.assertEqual(menu.screen, Screen.PLAYING)

    def test_sleep_confirmation_shows_countdown_and_single_yes_option(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        menu.show_sleep_confirmation(30)
        first = menu.render()
        menu.update_sleep_confirmation(12)
        later = menu.render()

        self.assertIsInstance(first, SleepConfirmFrame)
        self.assertEqual(first.top, "Are you still listening? 30")
        self.assertEqual(first.bottom, "[Yes]")
        self.assertEqual(later.top, "Are you still listening? 12")

    def test_sleep_confirmation_yes_returns_to_playback(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())
        menu.show_sleep_confirmation(30)

        menu.rotate_nav(1)
        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.CONFIRM_STILL_LISTENING)
        self.assertEqual(menu.screen, Screen.PLAYING)

    def test_home_returns_to_library(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())

        menu.rotate_nav(-1)
        menu.rotate_nav(-1)
        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.HOME)
        self.assertEqual(menu.screen, Screen.LIBRARY)

    def test_home_returns_to_active_playback_after_five_seconds(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())
        menu.rotate_nav(-2)
        menu.click_nav()

        self.assertFalse(menu.tick_home_return_timeout(4.9))
        self.assertEqual(menu.screen, Screen.LIBRARY)
        self.assertTrue(menu.tick_home_return_timeout(0.1))
        self.assertEqual(menu.screen, Screen.PLAYING)
        self.assertEqual(menu.playing_action_index, PLAYING_PLAY_INDEX)

    def test_home_return_timeout_resets_on_input_activity(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())
        menu.rotate_nav(-2)
        menu.click_nav()

        self.assertFalse(menu.tick_home_return_timeout(4.0))
        menu.note_input_activity()
        self.assertFalse(menu.tick_home_return_timeout(4.9))
        self.assertEqual(menu.screen, Screen.LIBRARY)
        self.assertTrue(menu.tick_home_return_timeout(0.1))
        self.assertEqual(menu.screen, Screen.PLAYING)

    def test_home_does_not_return_to_paused_playback(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session(), is_playing=False)
        menu.rotate_nav(-2)
        menu.click_nav()

        self.assertFalse(menu.tick_home_return_timeout(10.0))
        self.assertEqual(menu.screen, Screen.LIBRARY)

    def test_home_return_timeout_stops_if_playback_pauses(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.set_session(make_session())
        menu.rotate_nav(-2)
        menu.click_nav()

        self.assertFalse(menu.tick_home_return_timeout(4.0))
        menu.update_playback(menu.current_time, is_playing=False)
        self.assertFalse(menu.tick_home_return_timeout(2.0))
        self.assertEqual(menu.screen, Screen.LIBRARY)

    def test_volume_encoder_emits_volume_commands(self) -> None:
        menu = ApplianceMenu(BOOKS)

        volume = menu.rotate_volume(-2)[0]
        mute = menu.click_volume()[0]
        show_ip = menu.hold_volume()[0]

        self.assertEqual(volume.type, CommandType.VOLUME_DELTA)
        self.assertEqual(volume.volume_delta, -2)
        self.assertEqual(mute.type, CommandType.TOGGLE_MUTE)
        self.assertEqual(show_ip.type, CommandType.SHOW_IP)
        self.assertEqual(show_ip.display_seconds, 5)

    def test_control_hold_opens_bluetooth_menu(self) -> None:
        menu = ApplianceMenu(BOOKS)

        commands = menu.hold_nav(bluetooth_enabled=True)
        frame = menu.render()

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].type, CommandType.PAUSE_PLAYBACK)
        self.assertIsInstance(frame, BluetoothMenuFrame)
        self.assertTrue(frame.enabled)
        self.assertEqual(frame.options, ("Back", "Disable", "Pair"))
        self.assertEqual(frame.selected_index, 2)

    def test_control_hold_shows_unpair_when_bluetooth_connected(self) -> None:
        menu = ApplianceMenu(BOOKS)

        menu.hold_nav(bluetooth_enabled=True, bluetooth_connected=True)
        frame = menu.render()

        self.assertIsInstance(frame, BluetoothMenuFrame)
        self.assertEqual(frame.options, ("Back", "Disable", "Unpair"))

        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.UNPAIR_BLUETOOTH_DEVICE)

    def test_bluetooth_menu_can_disable_bluetooth(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.hold_nav(bluetooth_enabled=True)

        menu.rotate_nav(-1)
        command = menu.click_nav()[0]
        frame = menu.render()

        self.assertEqual(command.type, CommandType.SET_BLUETOOTH_ENABLED)
        self.assertFalse(command.bluetooth_enabled)
        self.assertIsInstance(frame, BluetoothMenuFrame)
        self.assertFalse(frame.enabled)
        self.assertEqual(frame.options, ("Back", "Enable", "Pair"))

    def test_bluetooth_pair_turns_bluetooth_on_when_disabled(self) -> None:
        menu = ApplianceMenu(BOOKS)
        menu.hold_nav(bluetooth_enabled=False)

        menu.rotate_nav(1)
        commands = menu.click_nav()

        self.assertEqual(commands[0].type, CommandType.SET_BLUETOOTH_ENABLED)
        self.assertTrue(commands[0].bluetooth_enabled)
        self.assertEqual(commands[1].type, CommandType.START_BLUETOOTH_SCAN)

    def test_bluetooth_device_list_scrolls_and_selects_device(self) -> None:
        menu = ApplianceMenu(BOOKS)

        menu.set_bluetooth_devices(
            [
                ("AA:BB:CC:DD:EE:FF", "Playroom Speaker"),
                ("11:22:33:44:55:66", "Blue Headphones"),
            ]
        )
        menu.rotate_nav(1)
        command = menu.click_nav()[0]

        self.assertEqual(command.type, CommandType.PAIR_BLUETOOTH_DEVICE)
        self.assertEqual(command.bluetooth_device_address, "11:22:33:44:55:66")
        self.assertEqual(command.bluetooth_device_name, "Blue Headphones")

    def test_bluetooth_device_list_shortens_long_names_before_marker(self) -> None:
        frame = BluetoothDevicesFrame(
            "Bose SoundLink Wireless Mobile speaker",
            selected_index=0,
            total_count=4,
        )

        self.assertEqual(frame.bottom, "Bose SoundLink Wi... 1/4")

    def test_volume_rotation_updates_volume_overlay(self) -> None:
        menu = ApplianceMenu(BOOKS)

        menu.rotate_volume(3)
        frame = menu.render()

        self.assertIsInstance(frame, VolumeFrame)
        self.assertEqual(frame.percent, 65)
        self.assertEqual(frame.top, "Volume")
        self.assertEqual(frame.bottom, "[########----]")

    def test_volume_overlay_returns_to_previous_screen_after_timeout(self) -> None:
        menu = ApplianceMenu(BOOKS)

        original = menu.render()
        menu.rotate_volume(1)

        self.assertIsInstance(menu.render(), VolumeFrame)

        menu.tick_overlay(2)
        self.assertIsInstance(menu.render(), VolumeFrame)

        menu.tick_overlay(1)
        restored = menu.render()

        self.assertEqual(restored, original)

    def test_volume_adjustment_refreshes_overlay_timeout(self) -> None:
        menu = ApplianceMenu(BOOKS)

        menu.rotate_volume(1)
        menu.tick_overlay(2)
        menu.rotate_volume(1)
        menu.tick_overlay(2)

        self.assertIsInstance(menu.render(), VolumeFrame)

        menu.tick_overlay(1)

        self.assertNotIsInstance(menu.render(), VolumeFrame)

    def test_volume_clamps_to_zero_and_one_hundred(self) -> None:
        menu = ApplianceMenu(BOOKS)

        menu.rotate_volume(-20)
        self.assertEqual(menu.render_volume().top, "Muted")
        self.assertEqual(menu.render_volume().percent, 0)
        self.assertTrue(menu.render_volume().is_muted)

        menu.rotate_volume(40)
        self.assertEqual(menu.render_volume().top, "Volume")
        self.assertEqual(menu.render_volume().percent, 100)

    def test_volume_bar_renders_from_zero_to_one_hundred(self) -> None:
        self.assertEqual(volume_bar(0), "[------------]")
        self.assertEqual(volume_bar(50), "[######------]")
        self.assertEqual(volume_bar(100), "[############]")

    def test_author_line_prefixes_author(self) -> None:
        self.assertEqual(author_line("Peter Brown"), "By Peter Brown")
        self.assertEqual(author_line(""), "")

    def test_title_section_letter_uses_first_title_letter(self) -> None:
        self.assertEqual(title_section_letter("  the hobbit"), "H")
        self.assertEqual(title_section_letter("A Wrinkle in Time"), "W")
        self.assertEqual(title_section_letter("The A Team"), "T")
        self.assertEqual(title_section_letter("Theodore Boone"), "T")
        self.assertEqual(title_section_letter("Anansi Boys"), "A")
        self.assertEqual(title_section_letter("...Matilda"), "M")
        self.assertEqual(title_section_letter("1984"), "#")

    def test_title_sort_text_ignores_leading_articles(self) -> None:
        self.assertEqual(title_sort_text("The Hobbit"), "hobbit")
        self.assertEqual(title_sort_text("A Wrinkle in Time"), "wrinkle in time")
        self.assertEqual(title_sort_text("The A Team"), "team")
        self.assertEqual(title_sort_text("Theodore Boone"), "theodore boone")
        self.assertEqual(title_sort_text("Anansi Boys"), "anansi boys")

    def test_author_sort_text_uses_first_authors_last_name(self) -> None:
        self.assertEqual(author_sort_text("J.R.R. Tolkien"), "tolkien j.r.r.")
        self.assertEqual(author_sort_text("Mary Pope Osborne"), "osborne mary pope")
        self.assertEqual(author_sort_text("Neil Gaiman & Terry Pratchett"), "gaiman neil")
        self.assertEqual(author_sort_text("Dahl, Roald"), "dahl")
        self.assertEqual(author_sort_text(""), "")
        self.assertEqual(author_section_letter("Madeleine L'Engle"), "L")

    def test_marquee_text_scrolls_with_gap(self) -> None:
        self.assertEqual(marquee_text("Long title", 4, 0), "Long")
        self.assertEqual(marquee_text("Long title", 4, 5), "titl")
        self.assertEqual(marquee_text("Short", 10, 5), "Short")


if __name__ == "__main__":
    unittest.main()
