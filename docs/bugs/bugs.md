# Bugs and Solutions Log

<!-- Auto-Claude will record bugs and solutions here -->

## 2026-01-29 - Service uses wrong code path (CRITICAL)
**Symptom:** All git pull / code fixes had zero effect on the running player
**Root Cause:** systemd service had `WorkingDirectory=/home/skillz` and `PYTHONPATH=/home/skillz`, so it loaded code from `/home/skillz/src/player/`. The git repo lives at `/home/skillz/jetson-media-player/`. Every `git pull` updated the repo but the service never saw the changes.
**Fix:** Changed service file to `WorkingDirectory=/home/skillz/jetson-media-player` and `PYTHONPATH=/home/skillz/jetson-media-player`. Also copied fixed files to `/home/skillz/src/player/` as immediate fix.
**Prevention:** After committing the service file change, run `sudo cp skillz-player.service /etc/systemd/system/ && sudo systemctl daemon-reload` on the Jetson.

## 2026-01-29 - Sync race condition (dual downloads)
**Symptom:** Two syncs ran simultaneously on startup — one from the sync loop, one from the network monitor. Both downloaded the same files, causing `[Errno 2] No such file or directory` when the second thread tried to rename an already-moved .tmp file.
**Root Cause:** `_on_network_state_changed()` calls `sync_now()` in a new thread, which races with the sync loop's initial sync.
**Fix:** Added `_sync_lock = threading.Lock()` with non-blocking acquire in `sync_now()`. Second caller sees "Sync already in progress — skipping".

## 2026-01-29 - Files re-downloaded every 5 minutes
**Symptom:** All 3 video files (20MB total) re-downloaded on every sync cycle.
**Root Cause:** CMS returns `file_hash: ""` (empty string). The old code only skipped download if the hash matched — but empty hash never matches, so it always re-downloaded.
**Fix:** If file exists and no hash is provided, skip the download and trust the existing file.

## 2026-01-29 - Content downloads but video never plays
**Symptom:** Sync downloads all files, playlist.json is populated, but GStreamer never starts and screen stays black.
**Root Cause:** `_on_content_updated()` only called `playlist_manager.reload()` — it never initialized GStreamer or started playback. If the Jetson booted with no content, GStreamer was never created, and when content arrived there was no code path to create it.
**Fix:** Added `_late_start_playback()` method that initializes GStreamer and starts playback. Called from `_on_content_updated()` via `GLib.idle_add()` when content arrives and GStreamer hasn't been initialized yet.
