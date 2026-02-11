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

## 2026-02-03 - Playlist not looping — playbin gapless hangs pipeline (CRITICAL)
**Symptom:** First video plays, transitions to second video, then player freezes. Screen stays on last frame or goes black. No further playback occurs.
**Root Cause:** Multiple compounding issues:
1. **Playbin gapless hangs on Jetson**: Setting a new URI in playbin's `about-to-finish` signal for gapless transition causes the pipeline to hang silently on Jetson Orin Nano (GStreamer 1.20 + xvimagesink). Neither EOS nor stream-start fires after the gapless attempt — the pipeline enters a dead state.
2. **about-to-finish fired multiple times**: The position watchdog (500ms timer) and playbin's own signal both called `get_next_uri()`, consuming multiple playlist items and overwriting the queued URI.
3. **playlist reload() reset index**: Sync service calls `playlist_manager.reload()` every few minutes, which resets `_default_index = 0`. If the currently playing video is item[0], `get_next_uri()` returns the same video — triggering "same video can't gapless" which fell through to EOS, but only worked once.
**Fix:**
- Abandoned playbin gapless entirely. Pre-fetch the next URI (via watchdog or about-to-finish) but do NOT set it on playbin.
- On EOS, restart via `GLib.idle_add()` using READY→PLAYING for different videos, or `seek_simple(0)` for same-video loops (seamless, no pipeline state change).
- Added `_prefetched` flag to ensure pre-fetch runs exactly once per video.
- Separated `_playing_uri` (current) from `_next_uri` (pre-fetched for EOS).
**Key files:** `src/player/gstreamer_player.py`

## 2026-02-04 - Video stuttering / not smooth — playbin uses software decode (CRITICAL)
**Symptom:** Video playback on Jetson has visible stuttering, hickups, and stalls. CPU at 85%+.
**Root Cause:** `playbin` auto-inserts software `videoconvert` between `nvv4l2decoder` and `xvimagesink`, bypassing the hardware color conversion. Even with a custom video sink bin containing `nvvidconv`, playbin still adds its own software converter in the negotiation path. Result: ~85% CPU for software color space conversion instead of ~6% with hardware path.
**Diagnosis:** Tested raw `gst-launch-1.0` pipeline: `filesrc → qtdemux → h264parse → nvv4l2decoder → nvvidconv → xvimagesink` = 11% CPU. Same file through playbin = 86% CPU.
**Fix:** Replaced playbin entirely with a custom pipeline built element-by-element:
- Video: `filesrc → qtdemux → queue → h264parse → nvv4l2decoder → nvvidconv → xvimagesink`
- Audio: `qtdemux → queue → avdec_aac → audioconvert → audioresample → pulsesink`
- Dynamic pad linking from qtdemux for both branches
- Same-video loops use `seek_simple(0)` (no pipeline rebuild)
- Different-video transitions rebuild the full pipeline via `GLib.idle_add()`
**Result:** CPU dropped from 86% to 6.2%. Smooth, stutter-free playback.
**Key files:** `src/player/gstreamer_player.py`
