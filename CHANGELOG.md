# Changelog

All notable changes to Chapter Player for Audiobookshelf are documented here.

## Unreleased

- Return from the library to the current playback controls after five seconds of inactivity while audio is playing.
- Refine the lightweight eSpeak NG spoken-navigation pacing and pitch while retaining its smoother default voice.

## [0.2.1] - 2026-10-02

- Documented the trusted-local-network security model and safe deployment boundaries.
- Added GitHub Actions coverage for the test suite, syntax checks, and Raspberry Pi OS Lite installer simulation.
- Made the installer simulation portable across macOS and Linux.

## [0.2.0] - 2026-10-02

- Added a web setting to order the player library by title or by author last name.
- Added optional offline spoken navigation for highlighted book titles and controls.
- Added the Chapter color logo and refined the tabbed administration interface.
- Added CSRF protection to setup-page forms and live player controls.
- Pinned the Raspberry Pi installer to versioned releases for reproducible installs.

## [0.1.0] - 2026-10-01

Initial public release.

- Raspberry Pi Zero 2 W/WH appliance interface with SH1122 OLED and two rotary controls.
- Audiobookshelf login, library browsing, playback, resume, and progress synchronization.
- Internal MAX98357A speaker output and Bluetooth audio support.
- Podcast support, sleep timer, screensavers, and web administration.
- Automated Raspberry Pi OS Lite installer, first-boot setup hotspot, and captive portal support.
- Printable enclosure files, wiring documentation, assembly references, and parts list.
- Shared storage ownership handling and an isolated installer simulation for clean-install validation.
