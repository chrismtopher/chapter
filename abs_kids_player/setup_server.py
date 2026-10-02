from __future__ import annotations

import argparse
import html
import json
import subprocess
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import __version__
from .api import AudiobookshelfClient, AudiobookshelfError, client_from_config
from .bluetooth_audio import connected_bluetooth_audio_device
from .config import (
    LIBRARY_SORT_AUTHOR,
    LIBRARY_SORT_TITLE,
    MAX_SLEEP_TIMER_MINUTES,
    MIN_SLEEP_TIMER_MINUTES,
    SCREEN_SAVER_BOOKS,
    SCREEN_SAVER_CHAPTER,
    SCREEN_SAVER_CLOCK,
    SCREEN_SAVER_DIM_LEVELS,
    AppConfig,
    PodcastConfig,
    load_config,
    save_config,
    valid_library_sort_mode,
    valid_screen_saver_dim_percent,
    valid_screen_saver_mode,
    valid_sleep_timer_minutes,
)
from .library_cache import clear_cached_books
from .player_state import clear_last_playback
from .player_control import WebPlayerStatus, load_web_player_status, queue_web_player_command
from .podcast import PodcastError, resolve_podcast_config
from .wifi import (
    SETUP_HOTSPOT_SSID,
    SETUP_HOTSPOT_URL,
    WifiError,
    WifiStatus,
    connect_wifi,
    ensure_wifi_or_hotspot,
    forget_all_wifi_connections_and_start_hotspot,
    forget_current_wifi_and_start_hotspot,
    wifi_status,
)


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 47831
WIFI_CHANGE_DELAY_SECONDS = 5.0
SYSTEM_ACTION_DELAY_SECONDS = 3.0
PLAYER_EVENT_POLL_SECONDS = 0.25
PLAYER_EVENT_TIME_SECONDS = 1.0
PLAYER_EVENT_HEARTBEAT_SECONDS = 10.0
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "chapter-logo.png"


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chapter Player for Audiobookshelf</title>
  <link rel="icon" type="image/png" href="/assets/chapter-logo.png">
  <style>
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      min-height: 100vh;
      background: #edf1ef;
      color: #1f292b;
    }}
    main {{
      width: min(92vw, 780px);
      margin: 28px auto 48px;
    }}
    .app-header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: center;
      padding: 0 2px;
    }}
    .app-brand {{
      display: flex;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }}
    .app-logo {{
      width: 84px;
      height: 63px;
      flex: 0 0 auto;
      object-fit: contain;
    }}
    .app-intro {{
      max-width: 500px;
      margin: 0;
      font-size: 0.95rem;
    }}
    .tabs {{
      display: flex;
      gap: 4px;
      margin-top: 22px;
      padding: 4px;
      overflow-x: auto;
      border: 1px solid #cfd9d6;
      border-radius: 8px;
      background: #f8faf9;
      scrollbar-width: none;
    }}
    .tabs::-webkit-scrollbar {{ display: none; }}
    .tab-button {{
      width: auto;
      min-width: 68px;
      min-height: 42px;
      flex: 1 0 auto;
      margin: 0;
      padding: 8px 4px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: #586467;
      font-size: 0.8rem;
      font-weight: 750;
      cursor: pointer;
    }}
    .tab-button:hover {{
      background: #e9efed;
      color: #1f292b;
    }}
    .tab-button.is-active {{
      background: #234f50;
      color: #fff;
      box-shadow: 0 2px 7px rgba(26, 58, 59, 0.2);
    }}
    .tab-button:focus-visible,
    button:focus-visible,
    input:focus-visible,
    select:focus-visible {{
      outline: 3px solid #e8ad55;
      outline-offset: 2px;
    }}
    .tab-panel {{
      margin-top: 14px;
    }}
    .tab-panel[hidden] {{
      display: none;
    }}
    .connection-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .card {{
      background: #fff;
      border: 1px solid #d7dfdc;
      border-radius: 8px;
      padding: 24px;
      margin: 0;
      box-shadow: 0 10px 28px rgba(30, 49, 48, 0.09);
    }}
    h1 {{ margin: 0; font-size: 1.75rem; line-height: 1.15; }}
    h2 {{ margin: 0 0 14px; font-size: 1.05rem; }}
    p {{ color: #5d686b; line-height: 1.45; }}
    label {{ display: block; margin-top: 16px; font-weight: 700; }}
    input {{
      box-sizing: border-box;
      width: 100%;
      min-height: 44px;
      margin-top: 6px;
      padding: 8px 10px;
      border: 1px solid #b9c5c2;
      border-radius: 6px;
      font: inherit;
    }}
    button {{
      width: 100%;
      min-height: 48px;
      margin-top: 22px;
      border: 0;
      border-radius: 6px;
      background: #2e7d79;
      color: #fff;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }}
    button:hover {{
      background: #256c68;
    }}
    button:disabled {{
      cursor: wait;
      opacity: 0.65;
    }}
    .playback-form button {{
      margin-top: 12px;
    }}
    .volume-form {{
      margin-top: 12px;
      display: grid;
      grid-template-columns: 28px 1fr 52px;
      gap: 10px;
      align-items: center;
    }}
    .volume-icon {{
      color: #20242a;
      font-size: 1.2rem;
      text-align: center;
      line-height: 1;
    }}
    .volume-percent {{
      color: #20242a;
      font-weight: 800;
      text-align: left;
      white-space: nowrap;
    }}
    .volume-slider {{
      padding: 0;
      margin-top: 0;
      min-height: 44px;
      border: 0;
      border-radius: 0;
      accent-color: #2e7d79;
    }}
    .message {{
      padding: 12px;
      border-radius: 6px;
      margin: 16px 0 0;
      background: #eef7f5;
      color: #164b47;
    }}
    .error {{
      background: #fbebeb;
      color: #842020;
    }}
    .hint {{
      font-size: 0.92rem;
    }}
    .settings-list {{
      margin-top: 12px;
      border: 1px solid #dfe6e3;
      border-radius: 8px;
      overflow: hidden;
    }}
    .settings-row {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
      padding: 12px;
      border-top: 1px solid #dfe6e3;
    }}
    .settings-row:first-child {{ border-top: 0; }}
    .setting-name {{
      font-weight: 800;
    }}
    .setting-state {{
      color: #59616d;
      font-size: 0.88rem;
      margin-top: 3px;
    }}
    .toggle-form {{
      margin: 0;
    }}
    .toggle-button {{
      position: relative;
      width: 54px;
      height: 30px;
      min-height: 30px;
      margin: 0;
      padding: 0;
      display: block;
      box-sizing: border-box;
      border-radius: 999px;
      background: #a9aea9;
      overflow: hidden;
    }}
    .toggle-button::after {{
      content: "";
      position: absolute;
      top: 4px;
      left: 4px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.28);
    }}
    .toggle-button.is-on {{
      background: #2e7d79;
    }}
    .toggle-button.is-on::after {{
      left: 28px;
    }}
    .select-form {{
      display: flex;
      gap: 8px;
      align-items: center;
      margin: 0;
    }}
    .settings-select {{
      min-width: 150px;
      border: 1px solid #d8d0c5;
      border-radius: 8px;
      padding: 8px 10px;
      background: #fff;
      color: #1f2933;
      font: inherit;
    }}
    .screen-saver-settings-form {{
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 0.8fr) auto;
      gap: 8px;
      align-items: end;
      margin: 2px 0 0;
    }}
    .screen-saver-settings-form label {{
      margin: 0;
      color: #59616d;
      font-size: 0.82rem;
    }}
    .screen-saver-settings-form .settings-select {{
      width: 100%;
      min-width: 0;
      margin-top: 4px;
    }}
    .settings-number {{
      width: 76px;
      min-height: 38px;
      margin: 0;
      padding: 7px 8px;
    }}
    .sleep-timer-content {{
      min-width: 0;
    }}
    .sleep-timer-duration-form {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 10px 0 0;
      color: #59616d;
      font-size: 0.88rem;
    }}
    .sleep-timer-duration-form .settings-number {{
      width: 68px;
    }}
    .small-button {{
      width: auto;
      min-height: 36px;
      padding: 8px 12px;
      border-radius: 8px;
      white-space: nowrap;
    }}
    .secondary {{
      background: #e8eeec;
      color: #20242a;
    }}
    .secondary:hover {{
      background: #dce6e2;
    }}
    .podcast-form {{
      margin-top: 12px;
    }}
    .podcast-table {{
      display: grid;
      gap: 10px;
    }}
    .podcast-row {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: end;
      padding: 10px;
      border: 1px solid #dfe6e3;
      border-radius: 8px;
      background: #f8faf9;
    }}
    .podcast-row input {{
      margin-top: 0;
    }}
    .podcast-meta {{
      color: #59616d;
      font-size: 0.84rem;
      margin-top: 5px;
    }}
    .podcast-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin-top: 12px;
    }}
    .podcast-actions button {{
      margin-top: 0;
    }}
    .podcast-save-button {{
      width: auto;
      min-width: 132px;
    }}
    .system-actions {{
      border: 1px solid #dfe6e3;
      border-radius: 8px;
      overflow: hidden;
    }}
    .system-version {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
      padding: 14px 16px;
      border: 1px solid #dfe6e3;
      border-radius: 8px;
      background: #f8faf9;
    }}
    .system-version-label {{
      color: #59616d;
      font-size: 0.9rem;
    }}
    .system-action {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      padding: 16px;
      border-top: 1px solid #dfe6e3;
    }}
    .system-action:first-child {{
      border-top: 0;
    }}
    .system-action h3 {{
      margin: 0;
      font-size: 1rem;
    }}
    .system-action p {{
      margin: 5px 0 0;
      font-size: 0.9rem;
    }}
    .system-action > button {{
      width: auto;
      min-width: 112px;
      min-height: 40px;
      margin: 0;
      padding: 8px 14px;
    }}
    .danger-button {{
      background: #a33a3a;
    }}
    .danger-button:hover {{
      background: #872f2f;
    }}
    .confirmation-panel {{
      grid-column: 1 / -1;
      padding: 14px;
      border: 1px solid #e5c6c6;
      border-radius: 6px;
      background: #fff7f7;
    }}
    .confirmation-panel[hidden] {{
      display: none;
    }}
    .confirmation-panel strong {{
      display: block;
    }}
    .confirmation-actions {{
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 12px;
    }}
    .confirmation-actions form {{
      margin: 0;
    }}
    .confirmation-actions button {{
      width: auto;
      min-width: 96px;
      min-height: 38px;
      margin: 0;
      padding: 8px 12px;
    }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .status {{
      display: grid;
      grid-template-columns: 1fr;
      border: 1px solid #dfe6e3;
      border-radius: 8px;
      overflow: hidden;
    }}
    .status-row {{
      display: grid;
      grid-template-columns: minmax(140px, 180px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
      padding: 14px 16px;
      border-top: 1px solid #dfe6e3;
    }}
    .status-row:first-child {{ border-top: 0; }}
    .status-row:last-child {{
      padding: 16px;
    }}
    .status-label {{
      color: #59616d;
      font-size: 0.88rem;
    }}
    .status-value {{
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .status-value strong {{
      font-weight: 800;
    }}
    .now-playing-title {{
      font-weight: 800;
    }}
    .now-playing-meta {{
      color: #59616d;
      font-size: 0.92rem;
      margin-top: 4px;
    }}
    .hidden {{ display: none; }}
    .ok {{ color: #176c4f; }}
    .bad {{ color: #9b2c2c; }}
    code {{ background: #f1f1f1; padding: 2px 4px; border-radius: 4px; }}
    @media (max-width: 680px) {{
      main {{
        width: min(94vw, 520px);
        margin-top: 20px;
      }}
      .app-header {{
        display: block;
      }}
      .app-intro {{
        margin-top: 8px;
      }}
      .connection-grid {{
        grid-template-columns: 1fr;
      }}
      .card {{
        padding: 18px;
      }}
      .status {{
        grid-template-columns: 1fr;
      }}
      .status-row,
      .status-row:first-child {{
        grid-template-columns: 1fr;
        gap: 3px;
        border-top: 1px solid #dfe6e3;
      }}
      .status-row:first-child {{
        border-top: 0;
      }}
      .screen-saver-settings-form {{
        grid-template-columns: 1fr;
      }}
      .podcast-row {{
        grid-template-columns: 1fr;
      }}
      .podcast-row .small-button {{
        width: 100%;
      }}
      .system-action {{
        grid-template-columns: 1fr;
      }}
      .system-action > button {{
        width: 100%;
      }}
      .confirmation-actions {{
        display: grid;
        grid-template-columns: 1fr 1fr;
      }}
      .confirmation-actions button {{
        width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="app-header">
      <div class="app-brand">
        <img class="app-logo" src="/assets/chapter-logo.png" width="84" height="63" alt="">
        <h1>Chapter Player for Audiobookshelf</h1>
      </div>
    </header>
    {message}
    <nav class="tabs" role="tablist" aria-label="Player administration">
      <button class="tab-button is-active" id="tab-overview" type="button" role="tab" aria-selected="true" aria-controls="panel-overview" data-tab-target="overview">Overview</button>
      <button class="tab-button" id="tab-settings" type="button" role="tab" aria-selected="false" aria-controls="panel-settings" tabindex="-1" data-tab-target="settings">Settings</button>
      <button class="tab-button" id="tab-podcasts" type="button" role="tab" aria-selected="false" aria-controls="panel-podcasts" tabindex="-1" data-tab-target="podcasts">Podcasts</button>
      <button class="tab-button" id="tab-connections" type="button" role="tab" aria-selected="false" aria-controls="panel-connections" tabindex="-1" data-tab-target="connections">Setup</button>
      <button class="tab-button" id="tab-system" type="button" role="tab" aria-selected="false" aria-controls="panel-system" tabindex="-1" data-tab-target="system">System</button>
    </nav>
    <div class="tab-panel" id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" data-tab-panel="overview">
      {status_panel}
    </div>
    <div class="tab-panel" id="panel-settings" role="tabpanel" aria-labelledby="tab-settings" data-tab-panel="settings" hidden>
      {settings_card}
    </div>
    <div class="tab-panel" id="panel-podcasts" role="tabpanel" aria-labelledby="tab-podcasts" data-tab-panel="podcasts" hidden>
      {podcasts_card}
    </div>
    <div class="tab-panel connection-grid" id="panel-connections" role="tabpanel" aria-labelledby="tab-connections" data-tab-panel="connections" hidden>
      {wifi_card}
      <section class="card" aria-labelledby="audiobookshelf-heading">
        <h2 id="audiobookshelf-heading">Audiobookshelf</h2>
        <p class="hint">The password is sent only to your Audiobookshelf server. This player stores the returned user token.</p>
        <form method="post" action="/login">
          <label for="server_url">Audiobookshelf server URL</label>
          <input id="server_url" name="server_url" value="{server_url}" placeholder="https://books.example.com" required>

          <label for="username">Username</label>
          <input id="username" name="username" autocomplete="username" required>

          <label for="password">Password</label>
          <input id="password" name="password" type="password" autocomplete="current-password" required>

          <button type="submit">Log In Player</button>
        </form>
      </section>
    </div>
    <div class="tab-panel" id="panel-system" role="tabpanel" aria-labelledby="tab-system" data-tab-panel="system" hidden>
      {system_card}
    </div>
  </main>
  <script>
    var volumeSlider = document.querySelector("[data-volume-slider]");
    var volumePercent = document.querySelector("[data-volume-percent]");
    var playbackForm = document.querySelector("[data-playback-form]");
    var podcastRows = document.querySelector("[data-podcast-rows]");
    var addPodcastRowButton = document.querySelector("[data-add-podcast-row]");
    var tabButtons = document.querySelectorAll("[data-tab-target]");
    var tabPanels = document.querySelectorAll("[data-tab-panel]");
    var confirmationTriggers = document.querySelectorAll("[data-confirm-trigger]");
    var confirmationPanels = document.querySelectorAll("[data-confirm-panel]");
    var volumeTimer = null;
    var latestPlayerStatus = null;
    var pendingPlaybackAction = null;
    var sseStatusReceived = false;
    var sseFallbackTimer = null;
    var fallbackPollTimer = null;
    var tabStorageKey = "chapter-admin-tab";
    function tabExists(tabName) {{
      return Boolean(document.querySelector('[data-tab-target="' + tabName + '"]'));
    }}
    function activateTab(tabName, moveFocus) {{
      if (!tabExists(tabName)) {{
        tabName = "overview";
      }}
      tabButtons.forEach(function(button) {{
        var active = button.getAttribute("data-tab-target") === tabName;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.setAttribute("tabindex", active ? "0" : "-1");
        if (active && moveFocus) {{
          button.focus();
        }}
      }});
      tabPanels.forEach(function(panel) {{
        panel.hidden = panel.getAttribute("data-tab-panel") !== tabName;
      }});
      try {{
        window.localStorage.setItem(tabStorageKey, tabName);
      }} catch (error) {{}}
    }}
    function savedTab() {{
      try {{
        return window.localStorage.getItem(tabStorageKey) || "overview";
      }} catch (error) {{
        return "overview";
      }}
    }}
    tabButtons.forEach(function(button, index) {{
      button.addEventListener("click", function() {{
        activateTab(button.getAttribute("data-tab-target"), false);
      }});
      button.addEventListener("keydown", function(event) {{
        var nextIndex = index;
        if (event.key === "ArrowRight") {{
          nextIndex = (index + 1) % tabButtons.length;
        }} else if (event.key === "ArrowLeft") {{
          nextIndex = (index - 1 + tabButtons.length) % tabButtons.length;
        }} else if (event.key === "Home") {{
          nextIndex = 0;
        }} else if (event.key === "End") {{
          nextIndex = tabButtons.length - 1;
        }} else {{
          return;
        }}
        event.preventDefault();
        activateTab(tabButtons[nextIndex].getAttribute("data-tab-target"), true);
      }});
    }});
    activateTab(savedTab(), false);
    function closeConfirmation(panelName, restoreFocus) {{
      var panel = document.querySelector('[data-confirm-panel="' + panelName + '"]');
      var trigger = document.querySelector('[data-confirm-trigger="' + panelName + '"]');
      if (panel) {{
        panel.hidden = true;
      }}
      if (trigger) {{
        trigger.setAttribute("aria-expanded", "false");
        if (restoreFocus) {{
          trigger.focus();
        }}
      }}
    }}
    confirmationTriggers.forEach(function(trigger) {{
      trigger.addEventListener("click", function() {{
        var panelName = trigger.getAttribute("data-confirm-trigger");
        confirmationPanels.forEach(function(panel) {{
          closeConfirmation(panel.getAttribute("data-confirm-panel"), false);
        }});
        var panel = document.querySelector('[data-confirm-panel="' + panelName + '"]');
        if (!panel) {{
          return;
        }}
        panel.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        var cancelButton = panel.querySelector("[data-confirm-cancel]");
        if (cancelButton) {{
          cancelButton.focus();
        }}
      }});
    }});
    document.querySelectorAll("[data-confirm-cancel]").forEach(function(button) {{
      button.addEventListener("click", function() {{
        var panel = button.closest("[data-confirm-panel]");
        if (panel) {{
          closeConfirmation(panel.getAttribute("data-confirm-panel"), true);
        }}
      }});
    }});
    function encodeForm(fields) {{
      var parts = [];
      for (var key in fields) {{
        if (Object.prototype.hasOwnProperty.call(fields, key)) {{
          parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(fields[key]));
        }}
      }}
      return parts.join("&");
    }}
    function postPlayer(fields, callback) {{
      var request = new XMLHttpRequest();
      request.open("POST", "/player", true);
      request.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
      request.setRequestHeader("X-Requested-With", "fetch");
      request.onreadystatechange = function() {{
        if (request.readyState === 4 && callback) {{
          callback(request.status);
        }}
      }};
      request.send(encodeForm(fields));
    }}
    function sendVolume(value) {{
      postPlayer({{action: "volume", volume: value}});
    }}
    function applyPlayerStatus(status) {{
      latestPlayerStatus = status;
      var playerContainer = document.querySelector("[data-now-playing]");
      var title = document.querySelector("[data-now-playing-title]");
      var meta = document.querySelector("[data-now-playing-meta]");
      var actionInput = document.querySelector("[data-playback-action]");
      var actionButton = document.querySelector("[data-playback-button]");
      var playbackForm = document.querySelector("[data-playback-form]");
      var volumeForm = document.querySelector("[data-volume-form]");
      if (!status.hasSession) {{
        pendingPlaybackAction = null;
        if (playerContainer) {{
          playerContainer.setAttribute("data-has-session", "0");
        }}
        if (title) {{
          title.textContent = "Nothing playing";
        }}
        if (meta) {{
          meta.textContent = "";
        }}
        if (playbackForm) {{
          playbackForm.classList.add("hidden");
        }}
        if (volumeForm) {{
          volumeForm.classList.add("hidden");
        }}
        return;
      }}
      if (playerContainer) {{
        playerContainer.setAttribute("data-has-session", "1");
      }}
      if (playbackForm) {{
        playbackForm.classList.remove("hidden");
      }}
      if (volumeForm) {{
        volumeForm.classList.remove("hidden");
      }}
      if (title) {{
        title.textContent = status.title;
      }}
      renderLivePlayerTime();
      if (actionInput && actionButton) {{
        if (pendingPlaybackAction) {{
          var pendingReached = pendingPlaybackAction === "play" ? status.isPlaying : !status.isPlaying;
          if (pendingReached) {{
            pendingPlaybackAction = null;
            actionButton.disabled = false;
          }}
        }}
        if (pendingPlaybackAction) {{
          actionButton.disabled = true;
          actionButton.textContent = pendingPlaybackAction === "play" ? "Playing..." : "Pausing...";
        }} else {{
          actionInput.value = status.isPlaying ? "pause" : "play";
          actionButton.textContent = status.isPlaying ? "Pause" : "Play";
          actionButton.disabled = false;
        }}
      }}
      if (volumeSlider && volumePercent && document.activeElement !== volumeSlider) {{
        volumeSlider.value = status.volumePercent;
        volumePercent.textContent = status.volumePercent + "%";
      }}
    }}
    function twoDigit(value) {{
      value = String(value);
      return value.length < 2 ? "0" + value : value;
    }}
    function formatDuration(seconds) {{
      seconds = Math.max(0, Math.floor(seconds || 0));
      var hours = Math.floor(seconds / 3600);
      var minutes = Math.floor((seconds % 3600) / 60);
      var secs = seconds % 60;
      if (hours) {{
        return hours + ":" + twoDigit(minutes) + ":" + twoDigit(secs);
      }}
      return minutes + ":" + twoDigit(secs);
    }}
    function liveTimeInfo(status) {{
      var currentTime = Number(status.currentTime || 0);
      var duration = Number(status.duration || 0);
      if (status.isPlaying) {{
        var updatedAt = Number(status.updatedAt || 0);
        if (updatedAt > 0) {{
          currentTime += Math.max(0, Date.now() / 1000 - updatedAt);
        }}
      }}
      if (duration > 0) {{
        currentTime = Math.min(currentTime, duration);
        return formatDuration(currentTime) + " / " + formatDuration(duration);
      }}
      return formatDuration(currentTime);
    }}
    function renderLivePlayerTime() {{
      var meta = document.querySelector("[data-now-playing-meta]");
      if (!meta || !latestPlayerStatus || !latestPlayerStatus.hasSession) {{
        return;
      }}
      meta.textContent = latestPlayerStatus.state + " · " + liveTimeInfo(latestPlayerStatus);
    }}
    function setPendingPlayback(action) {{
      var actionInput = document.querySelector("[data-playback-action]");
      var actionButton = document.querySelector("[data-playback-button]");
      pendingPlaybackAction = action;
      if (actionInput && actionButton) {{
        actionButton.disabled = true;
        actionButton.textContent = action === "play" ? "Playing..." : "Pausing...";
      }}
    }}
    function refreshPlayerStatus() {{
      var request = new XMLHttpRequest();
      request.open("GET", "/player/status?_=" + Date.now(), true);
      request.onreadystatechange = function() {{
        if (request.readyState !== 4) {{
          return;
        }}
        if (request.status >= 200 && request.status < 300) {{
          try {{
            var status = JSON.parse(request.responseText);
            applyPlayerStatus(status);
          }} catch (error) {{}}
        }}
      }};
      request.send();
    }}
    function startFallbackPolling() {{
      if (fallbackPollTimer) {{
        return;
      }}
      fallbackPollTimer = window.setInterval(refreshPlayerStatus, 1000);
      refreshPlayerStatus();
    }}
    function startPlayerEventStream() {{
      if (!window.EventSource) {{
        startFallbackPolling();
        return false;
      }}
      try {{
        var source = new EventSource("/player/events");
        source.onmessage = function(event) {{
          try {{
            applyPlayerStatus(JSON.parse(event.data));
            sseStatusReceived = true;
            if (sseFallbackTimer) {{
              window.clearTimeout(sseFallbackTimer);
              sseFallbackTimer = null;
            }}
          }} catch (error) {{
            // Keep the fallback polling running.
          }}
        }};
        source.onerror = function() {{
          if (sseFallbackTimer) {{
            window.clearTimeout(sseFallbackTimer);
          }}
          sseFallbackTimer = window.setTimeout(function() {{
            if (!sseStatusReceived) {{
              startFallbackPolling();
            }}
          }}, 4000);
        }};
        return true;
      }} catch (error) {{
        startFallbackPolling();
        return false;
      }}
    }}
    function sendPlayerAction(action) {{
      postPlayer({{action: action}}, function() {{
          window.setTimeout(refreshPlayerStatus, 250);
          window.setTimeout(refreshPlayerStatus, 750);
      }});
    }}
    function addPodcastRow(value) {{
      if (!podcastRows) {{
        return;
      }}
      var row = document.createElement("div");
      row.className = "podcast-row";
      var inputWrap = document.createElement("div");
      var input = document.createElement("input");
      input.name = "podcast_url";
      input.type = "url";
      input.placeholder = "https://podcasts.apple.com/...";
      input.value = value || "";
      var meta = document.createElement("div");
      meta.className = "podcast-meta";
      meta.textContent = "Paste a show link from podcasts.apple.com";
      var remove = document.createElement("button");
      remove.className = "small-button secondary";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.setAttribute("data-remove-podcast-row", "1");
      inputWrap.appendChild(input);
      inputWrap.appendChild(meta);
      row.appendChild(inputWrap);
      row.appendChild(remove);
      podcastRows.appendChild(row);
      attachPodcastRemoveButtons();
      input.focus();
    }}
    function attachPodcastRemoveButtons() {{
      var buttons = document.querySelectorAll("[data-remove-podcast-row]");
      buttons.forEach(function(button) {{
        if (button.getAttribute("data-bound") === "1") {{
          return;
        }}
        button.setAttribute("data-bound", "1");
        button.addEventListener("click", function() {{
          var row = button.closest(".podcast-row");
          if (row) {{
            row.remove();
          }}
          if (podcastRows && !podcastRows.querySelector(".podcast-row")) {{
            addPodcastRow("");
          }}
        }});
      }});
    }}
    if (playbackForm) {{
      playbackForm.addEventListener("submit", function(event) {{
        event.preventDefault();
        var actionInput = document.querySelector("[data-playback-action]");
        var actionButton = document.querySelector("[data-playback-button]");
        if (!actionInput) {{
          return;
        }}
        setPendingPlayback(actionInput.value);
        sendPlayerAction(actionInput.value);
      }});
    }}
    if (volumeSlider && volumePercent) {{
      volumeSlider.addEventListener("input", function() {{
        volumePercent.textContent = volumeSlider.value + "%";
        window.clearTimeout(volumeTimer);
        volumeTimer = window.setTimeout(function() {{
          sendVolume(volumeSlider.value);
        }}, 120);
      }});
      volumeSlider.addEventListener("change", function() {{
        window.clearTimeout(volumeTimer);
        sendVolume(volumeSlider.value);
      }});
    }}
    if (addPodcastRowButton) {{
      addPodcastRowButton.addEventListener("click", function() {{
        addPodcastRow("");
      }});
    }}
    attachPodcastRemoveButtons();
    startPlayerEventStream();
    refreshPlayerStatus();
    window.setInterval(renderLivePlayerTime, 1000);
  </script>
</body>
</html>
"""


HEALTH_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Audiobookshelf Player Health</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      min-height: 100vh;
      background: #f3f0e8;
      color: #20242a;
      display: grid;
      place-items: center;
    }}
    main {{
      width: min(92vw, 560px);
      background: #fff;
      border: 1px solid #d9d3c7;
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 18px 48px rgba(0, 0, 0, 0.12);
    }}
    h1 {{ margin: 0 0 18px; font-size: 1.5rem; }}
    .row {{
      border-top: 1px solid #eee7dc;
      padding: 16px 0;
    }}
    .label {{
      color: #59616d;
      font-size: 0.92rem;
      margin-bottom: 4px;
    }}
    .value {{ font-size: 1.1rem; }}
    .value strong {{ font-weight: 800; }}
    .ok {{ color: #176c4f; }}
    .bad {{ color: #9b2c2c; }}
    code {{ background: #f1f1f1; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <main>
    <h1>Audiobookshelf Player Health</h1>
    <div class="row">
      <div class="label">Wi-Fi</div>
      <div class="value {wifi_class}">{wifi_value}</div>
    </div>
    <div class="row">
      <div class="label">Audiobookshelf</div>
      <div class="value {abs_class}">{abs_value}</div>
    </div>
    <div class="row">
      <div class="label">Software Version</div>
      <div class="value"><strong>v{version}</strong></div>
    </div>
    <div class="row">
      <div class="label">Setup Page</div>
      <div class="value"><a href="/">Open setup</a></div>
    </div>
  </main>
</body>
</html>
"""


class SetupHandler(BaseHTTPRequestHandler):
    server_version = f"ChapterPlayer/{__version__}"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/assets/chapter-logo.png":
            self.send_logo_png()
            return
        if path == "/player/events":
            self.send_player_events()
            return
        if path == "/player/status":
            self.send_player_status_json()
            return
        if path == "/health":
            self.send_health_page()
            return
        if path != "/":
            self.send_error(404)
            return
        self.send_page()

    def send_logo_png(self) -> None:
        body = LOGO_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/wifi":
            self.handle_wifi_post()
            return
        if path == "/wifi/forget":
            self.handle_forget_wifi_post()
            return
        if path == "/player":
            self.handle_player_post()
            return
        if path == "/settings/click":
            self.handle_click_setting_post()
            return
        if path == "/settings/library-order":
            self.handle_library_sort_setting_post()
            return
        if path == "/settings/screensaver":
            self.handle_screen_saver_setting_post()
            return
        if path == "/settings/sleep":
            self.handle_sleep_setting_post()
            return
        if path == "/podcasts":
            self.handle_podcasts_post()
            return
        if path == "/system/reboot":
            self.handle_system_reboot_post()
            return
        if path == "/system/reset":
            self.handle_system_reset_post()
            return
        if path != "/login":
            self.send_error(404)
            return

        self.handle_login_post()

    def handle_wifi_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        ssid = one(fields, "wifi_ssid")
        password = one(fields, "wifi_password")

        if not ssid:
            self.send_page(message="Wi-Fi network name is required.", is_error=True)
            return

        schedule_wifi_connect(ssid, password)
        self.send_page(
            message=(
                "Wi-Fi change submitted. The player will switch networks in a moment. "
                "Hold the volume knob for 10 seconds to show the new setup address."
            )
        )

    def handle_forget_wifi_post(self) -> None:
        schedule_wifi_forget()
        self.send_page(
            message=(
                f"Wi-Fi forget submitted. In about 5 seconds, connect to "
                f"{html.escape(SETUP_HOTSPOT_SSID)}, then browse to {html.escape(SETUP_HOTSPOT_URL)}."
            )
        )

    def handle_login_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        server_url = one(fields, "server_url")
        username = one(fields, "username")
        password = one(fields, "password")

        try:
            saved_config = login_and_refresh_player(server_url, username, password)
        except AudiobookshelfError as error:
            self.send_page(
                message=f"Login failed: {html.escape(str(error))}",
                is_error=True,
                server_url=server_url,
                library_id="",
            )
            return

        self.send_page(
            message="Player login saved. You can close this page and restart the player.",
            server_url=saved_config.server_url,
            library_id=saved_config.library_id,
        )

    def handle_player_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        action = one(fields, "action")

        if action in {"play", "pause"}:
            queue_web_player_command(action)
            self.send_player_command_response()
            return

        if action == "volume":
            try:
                volume = min(max(int(one(fields, "volume")), 0), 100)
            except ValueError:
                self.send_page(message="Volume must be between 0 and 100.", is_error=True)
                return
            queue_web_player_command("volume", volume)
            self.send_player_command_response()
            return

        self.send_page(message="Unknown player command.", is_error=True)

    def handle_click_setting_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        enabled = one(fields, "enabled") == "1"
        save_click_setting(enabled)
        self.redirect_home()

    def handle_library_sort_setting_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        save_library_sort_setting(one(fields, "library_sort_mode"))
        self.redirect_home()

    def handle_screen_saver_setting_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        mode = valid_screen_saver_mode(one(fields, "screen_saver_mode"))
        if "screen_saver_dim_percent" in fields:
            save_screen_saver_setting(
                mode,
                valid_screen_saver_dim_percent(one(fields, "screen_saver_dim_percent")),
            )
        else:
            save_screen_saver_setting(mode)
        self.redirect_home()

    def handle_sleep_setting_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        if "enabled" in fields:
            save_sleep_timer_setting(enabled=one(fields, "enabled") == "1")
            self.redirect_home()
            return
        try:
            minutes = int(one(fields, "minutes"))
        except ValueError:
            self.send_page(message="Sleep timer must be a whole number of minutes.", is_error=True)
            return
        save_sleep_timer_setting(minutes=minutes)
        self.redirect_home()

    def handle_podcasts_post(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        urls = fields.get("podcast_url", [])
        try:
            save_podcast_settings(urls)
        except PodcastError as error:
            self.send_page(message=f"Podcast save failed: {html.escape(str(error))}", is_error=True)
            return
        self.redirect_home()

    def handle_system_reboot_post(self) -> None:
        self.send_page(message="Rebooting the Chapter player. It will be available again shortly.")
        schedule_system_reboot()

    def handle_system_reset_post(self) -> None:
        restore_device_defaults()
        self.send_page(
            message=(
                f"Default settings restored. In about 5 seconds, connect to "
                f"{html.escape(SETUP_HOTSPOT_SSID)}, then browse to {html.escape(SETUP_HOTSPOT_URL)}."
            )
        )
        schedule_system_reset()

    def send_page(
        self,
        message: str = "",
        is_error: bool = False,
        server_url: str | None = None,
        library_id: str | None = None,
    ) -> None:
        config = load_config()
        message_html = ""
        if message:
            css_class = "message error" if is_error else "message"
            message_html = f'<div class="{css_class}">{message}</div>'

        wifi = wifi_status()
        body = PAGE.format(
            status_panel=render_status_panel(
                wifi,
                audiobookshelf_status(),
                load_web_player_status(),
                bluetooth_status(),
            ),
            settings_card=render_settings_card(config),
            podcasts_card=render_podcasts_card(config),
            wifi_card=render_wifi_card(wifi),
            system_card=render_system_card(),
            message=message_html,
            server_url=html.escape(server_url if server_url is not None else config.server_url),
            library_id=html.escape(library_id if library_id is not None else config.library_id),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect_home(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_player_command_response(self) -> None:
        if self.headers.get("X-Requested-With") == "fetch":
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self.redirect_home()

    def send_text(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_player_status_json(self) -> None:
        self.send_json(player_status_payload(load_web_player_status()))

    def send_player_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        last_payload = ""
        last_signature = ""
        last_sent = 0.0
        last_heartbeat = time.monotonic()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        while True:
            payload = player_status_payload(load_web_player_status())
            payload_json = json.dumps(payload, separators=(",", ":"))
            signature = player_status_event_signature(payload)
            now = time.monotonic()
            should_send = not last_payload
            should_send = should_send or signature != last_signature
            should_send = should_send or (payload_json != last_payload and now - last_sent >= PLAYER_EVENT_TIME_SECONDS)
            if should_send:
                try:
                    self.wfile.write(player_status_sse(payload_json))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return
                last_payload = payload_json
                last_signature = signature
                last_sent = now
                last_heartbeat = now
            elif now - last_heartbeat >= PLAYER_EVENT_HEARTBEAT_SECONDS:
                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return
                last_heartbeat = now
            time.sleep(PLAYER_EVENT_POLL_SECONDS)

    def send_health_page(self) -> None:
        wifi = wifi_status()
        abs_status = audiobookshelf_status()
        body = render_health_page(wifi, abs_status).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def one(fields: dict[str, list[str]], name: str) -> str:
    return fields.get(name, [""])[0].strip()


def schedule_wifi_connect(ssid: str, password: str) -> None:
    def worker() -> None:
        try:
            print(f"Wi-Fi connection starting for {ssid}", flush=True)
            connect_wifi(ssid, password)
            print(f"Wi-Fi connection complete for {ssid}", flush=True)
        except WifiError as error:
            print(f"Wi-Fi connection failed: {error}", flush=True)

    timer = threading.Timer(WIFI_CHANGE_DELAY_SECONDS, worker)
    timer.daemon = True
    timer.start()


def schedule_wifi_forget(delay_seconds: float = WIFI_CHANGE_DELAY_SECONDS) -> None:
    def worker() -> None:
        try:
            print(f"Wi-Fi forget starting; switching to {SETUP_HOTSPOT_SSID}", flush=True)
            forget_current_wifi_and_start_hotspot()
            print(f"Wi-Fi forget complete; {SETUP_HOTSPOT_SSID} should be active", flush=True)
        except WifiError as error:
            print(f"Wi-Fi forget failed: {error}", flush=True)

    timer = threading.Timer(delay_seconds, worker)
    timer.daemon = True
    timer.start()


SystemCommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


def run_system_command(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, check=True, text=True)


def schedule_system_reboot(
    delay_seconds: float = SYSTEM_ACTION_DELAY_SECONDS,
    runner: SystemCommandRunner = run_system_command,
) -> None:
    def worker() -> None:
        try:
            print("System reboot starting", flush=True)
            runner(["systemctl", "reboot"])
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"System reboot failed: {error}", flush=True)

    timer = threading.Timer(delay_seconds, worker)
    timer.daemon = True
    timer.start()


def restore_device_defaults() -> AppConfig:
    config = AppConfig()
    save_config(config)
    clear_cached_books()
    clear_last_playback()
    queue_web_player_command("refresh_library")
    return config


def schedule_system_reset(delay_seconds: float = WIFI_CHANGE_DELAY_SECONDS) -> None:
    def worker() -> None:
        try:
            print(f"System reset starting; switching to {SETUP_HOTSPOT_SSID}", flush=True)
            forget_all_wifi_connections_and_start_hotspot()
            print(f"System reset complete; {SETUP_HOTSPOT_SSID} should be active", flush=True)
        except WifiError as error:
            print(f"System reset Wi-Fi change failed: {error}", flush=True)

    timer = threading.Timer(delay_seconds, worker)
    timer.daemon = True
    timer.start()


def login_and_refresh_player(server_url: str, username: str, password: str) -> AppConfig:
    existing_config = load_config()
    client, login_data = AudiobookshelfClient.login(server_url, username, password)
    resolved_library_id = str(login_data.get("userDefaultLibraryId") or "")
    if not resolved_library_id:
        resolved_library_id = client.choose_library_id()
    config = replace(
        existing_config,
        server_url=server_url.strip(),
        token=client.token,
        refresh_token=getattr(client, "refresh_token", ""),
        library_id=resolved_library_id,
        username=login_username(login_data, username),
    )
    save_config(config)
    queue_web_player_command("pause")
    queue_web_player_command("refresh_library")
    return config


def save_click_setting(enabled: bool) -> AppConfig:
    config = load_config()
    updated = replace(
        config,
        control_click_enabled=enabled,
    )
    save_config(updated)
    return updated


def save_library_sort_setting(mode: str) -> AppConfig:
    config = load_config()
    updated = replace(config, library_sort_mode=valid_library_sort_mode(mode))
    save_config(updated)
    queue_web_player_command("resort_library")
    return updated


def save_screen_saver_setting(mode: str, dim_percent: int | None = None) -> AppConfig:
    config = load_config()
    updated = replace(
        config,
        screen_saver_mode=valid_screen_saver_mode(mode),
        screen_saver_dim_percent=(
            config.screen_saver_dim_percent
            if dim_percent is None
            else valid_screen_saver_dim_percent(dim_percent)
        ),
    )
    save_config(updated)
    return updated


def save_sleep_timer_setting(
    enabled: bool | None = None,
    minutes: int | None = None,
) -> AppConfig:
    config = load_config()
    updated = replace(
        config,
        sleep_timer_enabled=config.sleep_timer_enabled if enabled is None else enabled,
        sleep_timer_minutes=(
            config.sleep_timer_minutes
            if minutes is None
            else valid_sleep_timer_minutes(minutes)
        ),
    )
    save_config(updated)
    return updated


def save_podcast_settings(urls: list[str]) -> AppConfig:
    podcasts = [resolve_podcast_config(url) for url in normalized_podcast_urls(urls)]
    config = load_config()
    updated = replace(config, podcasts=podcasts)
    save_config(updated)
    queue_web_player_command("refresh_library")
    return updated


def normalized_podcast_urls(urls: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for url in urls:
        clean_url = url.strip()
        if not clean_url:
            continue
        key = clean_url.lower()
        if key in seen:
            continue
        normalized.append(clean_url)
        seen.add(key)
    return normalized


def audiobookshelf_status() -> tuple[bool, str]:
    config = load_config()
    if not config.is_ready:
        return False, "Not configured"

    try:
        client = client_from_config(config, AudiobookshelfClient)
        client.choose_library_id(config.library_id)
        username = saved_username(config.username)
        if not username:
            username = login_username(client.get_current_user(), "")
            if username:
                save_config(replace(config, username=username))
    except AudiobookshelfError as error:
        return False, str(error)

    if username:
        return True, f"Logged in to {config.server_url} as {username}"
    return True, f"Logged in to {config.server_url}"


def bluetooth_status() -> tuple[bool, str]:
    device = connected_bluetooth_audio_device()
    if device is None:
        return False, "Not connected"
    return True, f"Connected to {device.name}"


def render_health_page(wifi: WifiStatus, abs_status: tuple[bool, str]) -> str:
    abs_ok, abs_message = abs_status
    return HEALTH_PAGE.format(
        wifi_class="ok" if wifi.connected else "bad",
        wifi_value=render_wifi_status_value(wifi),
        abs_class="ok" if abs_ok else "bad",
        abs_value=render_audiobookshelf_status_value(abs_message),
        version=html.escape(__version__),
    )


def render_status_panel(
    wifi: WifiStatus,
    abs_status: tuple[bool, str],
    player_status: WebPlayerStatus | None = None,
    bt_status: tuple[bool, str] = (False, "Not connected"),
) -> str:
    abs_ok, abs_message = abs_status
    bt_ok, bt_message = bt_status
    player_status = player_status or WebPlayerStatus()
    return """
    <section class="card" aria-labelledby="status-heading">
      <h2 id="status-heading">Status</h2>
      <div class="status" aria-label="Player status">
        <div class="status-row">
          <div class="status-label">Wi-Fi</div>
          <div class="status-value {wifi_class}">{wifi_value}</div>
        </div>
        <div class="status-row">
          <div class="status-label">Audiobookshelf</div>
          <div class="status-value {abs_class}">{abs_value}</div>
        </div>
        <div class="status-row">
          <div class="status-label">Bluetooth</div>
          <div class="status-value {bt_class}">{bt_value}</div>
        </div>
        <div class="status-row">
          <div class="status-label">Currently Playing</div>
          {player_value}
        </div>
      </div>
    </section>
    """.format(
        wifi_class="ok" if wifi.connected else "bad",
        wifi_value=render_wifi_status_value(wifi),
        abs_class="ok" if abs_ok else "bad",
        abs_value=render_audiobookshelf_status_value(abs_message),
        bt_class="ok" if bt_ok else "bad",
        bt_value=render_bluetooth_status_value(bt_message),
        player_value=render_player_status_value(player_status),
    )


def render_system_card() -> str:
    return """
    <section class="card" aria-labelledby="system-heading">
      <h2 id="system-heading">System</h2>
      <div class="system-version">
        <span class="system-version-label">Software Version</span>
        <strong>v{version}</strong>
      </div>
      <div class="system-actions">
        <div class="system-action">
          <div>
            <h3>Reboot</h3>
            <p>Restart the Chapter player without changing its settings.</p>
          </div>
          <button class="secondary" type="button" aria-expanded="false" aria-controls="confirm-reboot" data-confirm-trigger="reboot">Reboot</button>
          <div class="confirmation-panel" id="confirm-reboot" data-confirm-panel="reboot" hidden>
            <strong>Are you sure you want to reboot?</strong>
            <p>Playback will stop while the device restarts.</p>
            <div class="confirmation-actions">
              <button class="secondary" type="button" data-confirm-cancel>Cancel</button>
              <form method="post" action="/system/reboot">
                <button type="submit">Reboot</button>
              </form>
            </div>
          </div>
        </div>
        <div class="system-action">
          <div>
            <h3>Restore Device to Default Settings</h3>
            <p>Clear this player and return it to Wi-Fi setup mode.</p>
          </div>
          <button class="danger-button" type="button" aria-expanded="false" aria-controls="confirm-restore" data-confirm-trigger="restore">Restore</button>
          <div class="confirmation-panel" id="confirm-restore" data-confirm-panel="restore" hidden>
            <strong>Are you sure you want to restore the device to default settings?</strong>
            <p>This clears the Audiobookshelf login, listening state, and all saved Wi-Fi networks, and restores podcasts and player settings to defaults. This cannot be undone.</p>
            <div class="confirmation-actions">
              <button class="secondary" type="button" data-confirm-cancel>Cancel</button>
              <form method="post" action="/system/reset">
                <button class="danger-button" type="submit">Restore Device</button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </section>
    """.format(version=html.escape(__version__))


def render_settings_card(config: AppConfig) -> str:
    enabled = config.control_click_enabled
    next_value = "0" if enabled else "1"
    toggle_class = " is-on" if enabled else ""
    aria_pressed = "true" if enabled else "false"
    button_label = "Disable control knob click sound" if enabled else "Enable control knob click sound"
    sleep_enabled = config.sleep_timer_enabled
    sleep_next_value = "0" if sleep_enabled else "1"
    sleep_toggle_class = " is-on" if sleep_enabled else ""
    sleep_aria_pressed = "true" if sleep_enabled else "false"
    sleep_button_label = "Disable sleep timer" if sleep_enabled else "Enable sleep timer"
    sleep_duration_controls = ""
    if sleep_enabled:
        sleep_duration_controls = """
          <form class="sleep-timer-duration-form" method="post" action="/settings/sleep">
            <span>Ask after</span>
            <input class="settings-number" name="minutes" type="number" min="{sleep_min}" max="{sleep_max}" step="1" value="{sleep_minutes}" aria-label="Sleep timer minutes">
            <span>minutes of listening</span>
            <button class="small-button secondary" type="submit">Save</button>
          </form>
        """.format(
            sleep_minutes=config.sleep_timer_minutes,
            sleep_min=MIN_SLEEP_TIMER_MINUTES,
            sleep_max=MAX_SLEEP_TIMER_MINUTES,
        )
    return """
    <section class="card" aria-labelledby="settings-heading">
      <h2 id="settings-heading">Settings</h2>
      <div class="settings-list">
        <div class="settings-row">
          <div>
            <div class="setting-name">Control knob click sound</div>
          </div>
          <form class="toggle-form" method="post" action="/settings/click">
            <input type="hidden" name="enabled" value="{next_value}">
            <button class="toggle-button{toggle_class}" type="submit" aria-pressed="{aria_pressed}">
              <span class="sr-only">{button_label}</span>
            </button>
          </form>
        </div>
        <div class="settings-row">
          <div>
            <div class="setting-name">Library order</div>
          </div>
          <form class="select-form" method="post" action="/settings/library-order">
            <select class="settings-select" name="library_sort_mode" aria-label="Library order">
              {library_sort_options}
            </select>
            <button class="small-button secondary" type="submit">Save</button>
          </form>
        </div>
        <div class="settings-row screen-saver-row">
          <div>
            <div class="setting-name">Screen saver</div>
          </div>
          <form class="screen-saver-settings-form" method="post" action="/settings/screensaver">
            <label>
              Style
              <select class="settings-select" name="screen_saver_mode" aria-label="Screen saver style">
                {screen_saver_options}
              </select>
            </label>
            <label>
              Dim level
              <select class="settings-select" name="screen_saver_dim_percent" aria-label="Screen saver dim level">
                {screen_saver_dim_options}
              </select>
            </label>
            <button class="small-button secondary" type="submit">Save</button>
          </form>
        </div>
        <div class="settings-row">
          <div class="sleep-timer-content">
            <div class="setting-name">Sleep timer</div>
            {sleep_duration_controls}
          </div>
          <form class="toggle-form" method="post" action="/settings/sleep">
            <input type="hidden" name="enabled" value="{sleep_next_value}">
            <button class="toggle-button{sleep_toggle_class}" type="submit" aria-pressed="{sleep_aria_pressed}">
              <span class="sr-only">{sleep_button_label}</span>
            </button>
          </form>
        </div>
      </div>
    </section>
    """.format(
        next_value=next_value,
        toggle_class=toggle_class,
        aria_pressed=aria_pressed,
        button_label=button_label,
        library_sort_options=render_library_sort_options(config.library_sort_mode),
        screen_saver_options=render_screen_saver_options(config.screen_saver_mode),
        screen_saver_dim_options=render_screen_saver_dim_options(config.screen_saver_dim_percent),
        sleep_next_value=sleep_next_value,
        sleep_toggle_class=sleep_toggle_class,
        sleep_aria_pressed=sleep_aria_pressed,
        sleep_button_label=sleep_button_label,
        sleep_duration_controls=sleep_duration_controls,
    )


def render_podcasts_card(config: AppConfig) -> str:
    rows = [render_podcast_row(index, podcast) for index, podcast in enumerate(config.podcasts)]
    rows.append(render_podcast_row(len(rows), None))
    return """
    <section class="card" aria-labelledby="podcasts-heading">
      <h2 id="podcasts-heading">Podcasts</h2>
      <p class="hint">Paste the show link from podcasts.apple.com. RSS feed URLs also work. The player will show each podcast as a title and play the latest episode.</p>
      <form class="podcast-form" method="post" action="/podcasts">
        <div class="podcast-table" data-podcast-rows>
          {rows}
        </div>
        <div class="podcast-actions">
          <button class="small-button secondary" type="button" data-add-podcast-row>Add row</button>
          <button class="podcast-save-button" type="submit">Save Podcasts</button>
        </div>
      </form>
    </section>
    """.format(rows="\n".join(rows))


def render_podcast_row(index: int, podcast: PodcastConfig | None) -> str:
    podcast = podcast or PodcastConfig(url="")
    metadata = podcast_metadata_label(podcast)
    return """
    <div class="podcast-row">
      <div>
        <label class="sr-only" for="podcast_url_{index}">Podcast URL</label>
        <input id="podcast_url_{index}" name="podcast_url" type="url" value="{url}" placeholder="https://podcasts.apple.com/...">
        <div class="podcast-meta">{metadata}</div>
      </div>
      <button class="small-button secondary" type="button" data-remove-podcast-row>Remove</button>
    </div>
    """.format(
        index=index,
        url=html.escape(podcast.url),
        metadata=html.escape(metadata),
    )


def podcast_metadata_label(podcast: PodcastConfig) -> str:
    if podcast.title and podcast.author:
        return f"{podcast.title} by {podcast.author}"
    if podcast.title:
        return podcast.title
    return "Paste a show link from podcasts.apple.com"


def render_screen_saver_options(selected_mode: str) -> str:
    options = (
        (SCREEN_SAVER_CHAPTER, "Chapter word"),
        (SCREEN_SAVER_BOOKS, "Book titles"),
        (SCREEN_SAVER_CLOCK, "Digital clock"),
    )
    return "\n".join(
        '<option value="{value}"{selected}>{label}</option>'.format(
            value=html.escape(value),
            selected=" selected" if value == selected_mode else "",
            label=html.escape(label),
        )
        for value, label in options
    )


def render_library_sort_options(selected_mode: str) -> str:
    options = (
        (LIBRARY_SORT_TITLE, "Title"),
        (LIBRARY_SORT_AUTHOR, "Author (last name)"),
    )
    return "\n".join(
        '<option value="{value}"{selected}>{label}</option>'.format(
            value=value,
            selected=" selected" if value == selected_mode else "",
            label=label,
        )
        for value, label in options
    )


def render_screen_saver_dim_options(selected_percent: int) -> str:
    labels = {
        10: "10% (darkest)",
        50: "50% (brightest)",
    }
    return "\n".join(
        '<option value="{value}"{selected}>{label}</option>'.format(
            value=value,
            selected=" selected" if value == selected_percent else "",
            label=labels.get(value, f"{value}%"),
        )
        for value in SCREEN_SAVER_DIM_LEVELS
    )


def render_player_status_value(status: WebPlayerStatus) -> str:
    volume = min(max(status.volume_percent, 0), 100)
    state = "Playing" if status.is_playing else "Paused"
    if status.muted or volume <= 0:
        state = "Muted"
    button_action = "pause" if status.is_playing else "play"
    button_text = "Pause" if status.is_playing else "Play"
    title = html.escape(status.title) if status.has_session else "Nothing playing"
    meta = f"{html.escape(state)} · {html.escape(render_time_info(status))}" if status.has_session else ""
    hidden_class = "" if status.has_session else " hidden"
    return """
    <div class="status-value" data-now-playing data-has-session="{has_session}">
      <div class="now-playing-title" data-now-playing-title>{title}</div>
      <div class="now-playing-meta" data-now-playing-meta>{meta}</div>
      <form class="playback-form{hidden_class}" data-playback-form method="post" action="/player">
        <input data-playback-action type="hidden" name="action" value="{button_action}">
        <button data-playback-button type="submit">{button_text}</button>
      </form>
      <form class="volume-form{hidden_class}" data-volume-form method="post" action="/player">
        <input type="hidden" name="action" value="volume">
        <div class="volume-icon" aria-hidden="true">&#128266;</div>
        <input class="volume-slider" data-volume-slider aria-label="Volume" name="volume" type="range" min="0" max="100" value="{volume}">
        <div class="volume-percent" data-volume-percent>{volume}%</div>
      </form>
    </div>
    """.format(
        has_session="1" if status.has_session else "0",
        title=title,
        meta=meta,
        hidden_class=hidden_class,
        volume=volume,
        button_action=button_action,
        button_text=button_text,
    )


def render_time_info(status: WebPlayerStatus) -> str:
    if status.duration <= 0:
        return format_duration(status.current_time)
    return f"{format_duration(status.current_time)} / {format_duration(status.duration)}"


def player_status_payload(status: WebPlayerStatus) -> dict:
    volume = min(max(status.volume_percent, 0), 100)
    state = "Playing" if status.is_playing else "Paused"
    if status.muted or volume <= 0:
        state = "Muted"
    return {
        "hasSession": status.has_session,
        "title": status.title,
        "state": state,
        "timeInfo": render_time_info(status),
        "currentTime": max(0, status.current_time),
        "duration": max(0, status.duration),
        "updatedAt": status.updated_at,
        "isPlaying": status.is_playing,
        "volumePercent": volume,
    }


def player_status_event_signature(payload: dict) -> str:
    important = {
        "hasSession": payload.get("hasSession"),
        "title": payload.get("title"),
        "state": payload.get("state"),
        "isPlaying": payload.get("isPlaying"),
        "volumePercent": payload.get("volumePercent"),
        "duration": payload.get("duration"),
    }
    return json.dumps(important, sort_keys=True, separators=(",", ":"))


def player_status_sse(payload_json: str) -> bytes:
    return f"data: {payload_json}\n\n".encode("utf-8")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def render_wifi_status_value(wifi: WifiStatus) -> str:
    if wifi.connected and wifi.ssid:
        return f"Connected to <strong>{html.escape(wifi.ssid)}</strong>"
    return html.escape(wifi.message or "Unknown")


def render_audiobookshelf_status_value(message: str) -> str:
    prefix = "Logged in to "
    if not message.startswith(prefix):
        return html.escape(message)

    login_target = message[len(prefix) :]
    if " as " in login_target:
        server_url, username = login_target.rsplit(" as ", 1)
        return (
            f"Logged in to <strong>{html.escape(server_url)}</strong> "
            f"as <strong>{html.escape(username)}</strong>"
        )
    return f"Logged in to <strong>{html.escape(login_target)}</strong>"


def render_bluetooth_status_value(message: str) -> str:
    prefix = "Connected to "
    if message.startswith(prefix):
        device_name = message[len(prefix) :]
        return f"Connected to <strong>{html.escape(device_name)}</strong>"
    return html.escape(message)


def render_wifi_card(wifi: WifiStatus) -> str:
    if wifi.connected and wifi.ssid and wifi.ssid != SETUP_HOTSPOT_SSID:
        return """
        <section class="card" aria-labelledby="wifi-heading">
          <h2 id="wifi-heading">Wi-Fi</h2>
          <p class="hint">Connected to <strong>{ssid}</strong>.</p>
          <p class="hint">Forgetting this network will make the device form its own open Wi-Fi network. Connect to <code>{hotspot_ssid}</code>, then browse to <code>{hotspot_url}</code>.</p>
          <form method="post" action="/wifi/forget">
            <button type="submit">Forget this WiFi network</button>
          </form>
        </section>
        """.format(
            ssid=html.escape(wifi.ssid),
            hotspot_ssid=html.escape(SETUP_HOTSPOT_SSID),
            hotspot_url=html.escape(SETUP_HOTSPOT_URL),
        )

    return """
    <section class="card" aria-labelledby="wifi-heading">
      <h2 id="wifi-heading">Wi-Fi</h2>
      <p class="hint">Connect to the open Wi-Fi network <code>{hotspot_ssid}</code>, then browse to <code>{hotspot_url}</code>.</p>
      <form method="post" action="/wifi">
        <label for="wifi_ssid">Wi-Fi network name</label>
        <input id="wifi_ssid" name="wifi_ssid" autocomplete="off" required>

        <label for="wifi_password">Wi-Fi password</label>
        <input id="wifi_password" name="wifi_password" type="password" autocomplete="current-password">

        <button type="submit">Connect to Wi-Fi</button>
      </form>
    </section>
    """.format(
        hotspot_ssid=html.escape(SETUP_HOTSPOT_SSID),
        hotspot_url=html.escape(SETUP_HOTSPOT_URL),
    )


def login_username(login_data: dict, fallback: str) -> str:
    user = login_data.get("user") or {}
    candidates = [
        user.get("username"),
        user.get("name"),
        user.get("displayName"),
        login_data.get("username"),
        login_data.get("name"),
        login_data.get("displayName"),
        fallback,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def saved_username(username: str) -> str:
    username = username.strip()
    if username.lower() == "unknown user":
        return ""
    return username


def run_setup_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), SetupHandler)
    print(f"Setup page listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Chapter Player for Audiobookshelf setup page.")
    parser.add_argument(
        "--ensure-wifi",
        action="store_true",
        help="Start the setup hotspot if no Wi-Fi connection is active.",
    )
    args = parser.parse_args()
    if args.ensure_wifi:
        try:
            print(ensure_wifi_or_hotspot())
        except WifiError as error:
            print(f"Wi-Fi setup mode could not start: {error}")
    run_setup_server()


if __name__ == "__main__":
    main()
