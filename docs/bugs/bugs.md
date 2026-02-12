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

## 2026-02-11 - Jetson plays wrong playlist after CMS assignment (CRITICAL)
**Symptom:** Playlist 2 (4 videos) was assigned in CMS admin UI, but Jetson continued playing Playlist 1 (2 videos). Hub dashboard showed correct playlist, but Jetson never updated.
**Root Cause:** The Hub's `_get_playlist_for_screen()` function in `local_hub/routes/screens.py` queried the CMS directly via `/api/v1/devices/{hardware_id}/playlist`. However, the CMS had stale playlist assignment data. Meanwhile, the correct playlist was already cached in the Hub's local `Device.layout_json` field (synced via the layout sync service from CMS). The Hub was using two different data sources:
- Dashboard: Read from `Device.layout_json` (correct, showed "test 2")
- Sync API: Queried CMS directly (stale, returned "test 1")
**Fix:** Modified `_get_playlist_for_screen()` in `local_hub/routes/screens.py` to:
1. First check the `Device` model's `layout_json` for cached playlist data
2. Extract playlist items from the layout's content layer
3. Generate a version hash from content for change detection
4. Only fall back to CMS query if `layout_json` is unavailable
**Data Flow After Fix:**
```
CMS layout → Hub Device.layout_json cache → Hub /api/v1/by-device/{id}/config → Jetson sync → mpv playback
```
**Key files:** `local_hub/routes/screens.py`

## 2026-02-11 - Player crashes/stalls silently on playlist update (CRITICAL)
**Symptom:** When a new playlist is pushed from CMS, the Jetson screen goes white. Player process may still be running but video never plays. No error in logs — pipeline just freezes.
**Root Cause:** GStreamer pipeline can silently stall for various reasons (network glitch during playlist sync, race condition in pipeline rebuild, problematic video file). The existing position watchdog only did pre-fetch for gapless playback — it did NOT detect or recover from stalls.
**Fix:** Added stall detection to the position watchdog in `gstreamer_player.py`:
- Watchdog now tracks `_last_known_position` and `_last_position_change_time`
- If position hasn't advanced by >100ms in 5 seconds while state is PLAYING, considers it a stall
- On stall detection:
  1. Log warning with position and time stuck
  2. Attempt recovery by tearing down pipeline (NULL state) and rebuilding
  3. Up to 3 recovery attempts per stall
  4. If max attempts exceeded, notify error callback → player moves to next video
- Added `_handle_stall()` and `_recover_from_stall()` methods
- Added constants: `STALL_THRESHOLD_SECONDS=5`, `MAX_STALL_RECOVERY_ATTEMPTS=3`
**Result:** Player now auto-recovers from stalls. If a video consistently fails, it skips to the next one instead of freezing the display.
**Key files:** `src/player/gstreamer_player.py`

## 2026-02-11 - Pairing screen connects to CMS instead of Hub (CRITICAL)
**Symptom:** In hub mode, pairing screen shows "Connecting to CMS..." and tries to register with CMS instead of local Hub.
**Root Cause:** `_register_and_request_code()` in kiosk_player.py always used `self._cms_client` regardless of connection mode.
**Fix:** Modified `_register_and_request_code()` to check mode and create appropriate client:
- If mode == "hub" and hub_url is set: Create CMSClient with hub_url
- Otherwise: Use existing CMS client
Also store client in `self._pairing_client` for pairing status checks.
**Key files:** `src/player/kiosk_player.py`

## 2026-02-11 - Sync downloads from CMS URLs instead of Hub
**Symptom:** Player in hub mode was making download requests to CMS URLs (external internet) instead of Hub.
**Root Cause:** Download URLs in playlist items pointed to CMS. The `_download_content()` method preferred provided URLs over constructing Hub URLs.
**Fix:** Modified `_download_content()` to ALWAYS construct URL from Hub URL, ignoring any external URLs. Player should never connect to internet in hub mode.
**Key files:** `src/player/sync_service.py`

## 2026-02-11 - Playlist update doesn't purge old media files
**Symptom:** When a new playlist is assigned, old media files remain on disk and may continue playing.
**Root Cause:** `cleanup_orphaned_files()` only removed files not in new playlist, but if same filename appeared in both playlists, old file was kept.
**Fix:** Added `purge_all_media()` method that deletes ALL media files. Called when playlist version changes before downloading new content. Also added `force_download` parameter to `_sync_content()` to ensure fresh download of all files.
**Key files:** `src/player/sync_service.py`

## 2026-02-11 - Keyboard events not received by GTK window
**Symptom:** F1/Escape keys don't toggle menu. Player window doesn't receive keyboard input.
**Root Cause:** GStreamer's xvimagesink captures keyboard/mouse events by default, preventing GTK from receiving them.
**Fix:** Set `handle-events` property to False on xvimagesink:
```python
self._videosink.set_property('handle-events', False)
```
Also added focus grabber and global keyboard listener as fallbacks.
**Key files:** `src/player/gstreamer_player.py`, `src/player/ui/kiosk_window.py`, `src/player/kiosk_player.py`

## 2026-02-11 - Hub pairing fails with wrong endpoint (CRITICAL)
**Symptom:** Pairing screen shows "Could not connect to CMS" and no pairing code, even though Hub is reachable.
**Root Cause:** Multiple endpoint mismatches between CMSClient and Hub API:
1. CMSClient called `/api/v1/devices/pairing/request` but Hub uses `/api/v1/devices/register` which returns pairing_code directly
2. CMSClient's `check_pairing_status()` used `/api/v1/devices/pairing/status/{id}` but Hub has `/api/v1/pairing/status/{id}`
3. Status messages showed "CMS" instead of Hub IP in hub mode
**Fix:**
1. Modified `_register_and_request_code()` in kiosk_player.py to extract pairing_code from `register_device()` response for hub mode
2. Added `is_hub` flag to CMSClient to use correct endpoint for pairing status checks
3. Updated all status/error messages to show Hub IP when in hub mode
**Key files:** `src/common/cms_client.py`, `src/player/kiosk_player.py`
