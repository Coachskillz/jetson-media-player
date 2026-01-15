# Skillz Media Player - Jetson Orin Nano

A production-ready, offline-first media player for Jetson Orin Nano devices at retail screen locations. Uses GStreamer with NVIDIA hardware acceleration for seamless video playback, supports dynamic content triggering via ZeroMQ, and synchronizes with a local hub.

## Overview

The Skillz Media Player is designed to run indefinitely on Jetson Orin Nano edge devices without requiring constant connectivity. It provides:

- **Hardware-Accelerated Playback**: Uses NVIDIA's `nv3dsink` and `nvv4l2decoder` for GPU-accelerated video
- **Gapless Transitions**: Seamless video loops with no black frames using GStreamer's `playbin3`
- **Trigger-Based Content**: Switches playlists based on demographic/loyalty events via ZeroMQ
- **Offline-First Design**: Operates indefinitely using cached content when hub is unreachable
- **Auto-Recovery**: Systemd service with automatic restart on crash

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         SkillzPlayer                               │
│                    (Main Orchestrator)                             │
├───────────────┬───────────────┬──────────────┬────────────────────┤
│  GStreamer    │   Playlist    │   Trigger    │  Communication     │
│   Player      │   Manager     │   Listener   │   Services         │
│               │               │              │                    │
│  - playbin3   │  - Position   │  - ZeroMQ    │  - SyncService     │
│  - nv3dsink   │    tracking   │    SUB       │    (5 min sync)    │
│  - Gapless    │  - Trigger    │  - Demo/     │  - Heartbeat       │
│    playback   │    matching   │    Loyalty/  │    (60 sec POST)   │
│               │               │    NCMEC     │                    │
└───────────────┴───────────────┴──────────────┴────────────────────┘
                              │
                              ▼
                  ┌─────────────────────┐
                  │   PlayerConfig      │
                  │                     │
                  │  - device.json      │
                  │  - playlist.json    │
                  │  - settings.json    │
                  └─────────────────────┘
```

## Modules

### `player.py` - Main Orchestrator

The `SkillzPlayer` class coordinates all components:

```python
from src.player.player import SkillzPlayer, get_skillz_player

# Initialize and run (blocking)
player = SkillzPlayer()
player.run()

# Or non-blocking start/stop
player.start()
# ... later
player.stop()
```

**Startup Flow:**
1. Load configuration from JSON files
2. Initialize all components
3. Start playback IMMEDIATELY from cached content
4. Start background services (sync, heartbeat, trigger listener)

### `gstreamer_player.py` - Playback Engine

Hardware-accelerated video playback using GStreamer:

```python
from src.player.gstreamer_player import GStreamerPlayer, get_gstreamer_player

player = get_gstreamer_player()
player.play("file:///home/skillz/media/promo.mp4")
player.pause()
player.stop()
```

**Key Features:**
- Uses `playbin3` for gapless playback via `about-to-finish` signal
- NVIDIA hardware sink: `nv3dsink` (NOT `nvoverlaysink` - deprecated on Orin)
- Automatic pipeline state management
- Handles edge cases: missing files, corrupt videos, consecutive same video

### `playlist_manager.py` - Content Scheduling

Manages playlists and trigger rule matching:

```python
from src.player.playlist_manager import PlaylistManager, get_playlist_manager

pm = get_playlist_manager()

# Get next URI for gapless playback callback
next_uri = pm.get_next_uri()

# Handle demographic trigger
pm.handle_trigger({
    "type": "demographic",
    "age": 35,
    "gender": "male"
})
```

**Trigger Rule Matching:**
- Demographic: age_min, age_max, gender
- Loyalty: member_id matching
- NCMEC: Log-only alerts

### `trigger_listener.py` - ZeroMQ Events

Listens for external trigger events:

```python
from src.player.trigger_listener import TriggerListener, get_trigger_listener

listener = get_trigger_listener()
listener.set_callback(on_trigger_received)
listener.start()
```

**Message Format:**
```json
{
  "type": "demographic",
  "age": 35,
  "gender": "male",
  "confidence": 0.92
}
```

### `sync_service.py` - Hub Synchronization

Syncs with local hub every 5 minutes:

```python
from src.player.sync_service import SyncService, get_sync_service

sync = get_sync_service()
sync.start()  # Background sync every 5 min
sync.sync_now()  # Immediate sync
```

**Features:**
- Playlist version comparison
- Content download with SHA256 hash verification
- Graceful offline operation
- Disk space checking

### `heartbeat.py` - Status Reporter

Reports device status to hub every 60 seconds:

```python
from src.player.heartbeat import HeartbeatReporter

hb = HeartbeatReporter(hub_url, screen_id)
hb.set_status_callback(get_current_status)
hb.start()
```

**Payload:**
```json
{
  "status": "playing",
  "current_content": "promo1.mp4",
  "cpu_temp": 45,
  "memory_usage_percent": 35,
  "disk_free_gb": 12,
  "uptime_seconds": 3600
}
```

### `config.py` - Configuration Management

Loads and saves JSON configuration files:

```python
from src.player.config import PlayerConfig, get_player_config

config = get_player_config()

# Access device config
hub_url = config.hub_url
screen_id = config.screen_id

# Access playlist
default_playlist = config.default_playlist

# Access settings
if config.demographics_enabled:
    # Handle demographics
```

## Configuration Files

All config files are stored in `/home/skillz/config/` on target devices.

### `device.json`

Device identity and hub connection:

```json
{
  "screen_id": "uuid-string",
  "hardware_id": "mac-address-or-uuid",
  "hub_url": "http://192.168.1.100:5000",
  "name": "Pump 3",
  "location_in_store": "Gas pump area"
}
```

### `playlist.json`

Content schedule and trigger rules:

```json
{
  "default_playlist": {
    "id": "uuid",
    "items": [
      {"content_id": "uuid", "filename": "promo1.mp4", "duration": 30},
      {"content_id": "uuid", "filename": "promo2.mp4", "duration": 15}
    ]
  },
  "triggered_playlists": [
    {
      "playlist_id": "uuid",
      "rule": {"type": "demographic", "age_min": 21, "age_max": 35, "gender": "any"},
      "items": [{"content_id": "uuid", "filename": "beer_ad.mp4", "duration": 30}]
    }
  ],
  "version": 5,
  "updated_at": "2026-01-15T12:00:00Z"
}
```

### `settings.json`

Feature toggles:

```json
{
  "camera_enabled": true,
  "ncmec_enabled": true,
  "loyalty_enabled": false,
  "demographics_enabled": true,
  "ncmec_db_version": 12,
  "loyalty_db_version": 3
}
```

## Installation

### Quick Install on Jetson

```bash
cd /path/to/jetson-media-player
sudo ./install.sh
```

This will:
1. Install GStreamer and NVIDIA plugins via apt
2. Install Python dependencies (pyzmq, requests)
3. Create the skillz user and directory structure
4. Copy source files to `/home/skillz/src/player/`
5. Install config templates (without overwriting existing configs)
6. Set up systemd service with auto-start

### Verify Installation

```bash
sudo ./install.sh --verify
```

### Uninstall

```bash
sudo ./install.sh --uninstall
```

## Usage

### Development Mode

Run directly without systemd:

```bash
cd /home/skillz
python3 src/player/player.py
```

### Production Mode (systemd)

```bash
# Start the service
sudo systemctl start skillz-player

# Stop the service
sudo systemctl stop skillz-player

# Check status
sudo systemctl status skillz-player

# View logs
sudo journalctl -u skillz-player -f
```

### Service Configuration

The systemd service is configured with:
- `Restart=always` - Auto-restart on crash
- `RestartSec=5` - 5-second restart delay
- Memory limit: 1GB
- CPU limit: 80%
- Security hardening enabled

## Directory Structure

On target Jetson device:

```
/home/skillz/
├── config/
│   ├── device.json          # Screen identity, hub URL
│   ├── playlist.json        # Current playlist data
│   └── settings.json        # Feature toggles
├── media/                   # Downloaded video files
├── logs/                    # Application logs
├── databases/               # FAISS files (face detection)
└── src/
    └── player/              # Application source code
        ├── __init__.py
        ├── config.py
        ├── gstreamer_player.py
        ├── heartbeat.py
        ├── player.py
        ├── playlist_manager.py
        ├── sync_service.py
        └── trigger_listener.py
```

## Testing

### Run Unit Tests

```bash
cd /path/to/jetson-media-player
python3 -m pytest tests/test_player_*.py tests/test_playlist_manager.py tests/test_trigger_listener.py tests/test_sync_service.py -v
```

### Run Integration Tests

```bash
python3 -m pytest tests/test_player_integration.py -v
```

### Verify GStreamer Plugins (on Jetson)

```bash
# Check NVIDIA decoder
gst-inspect-1.0 nvv4l2decoder

# Check NVIDIA sink
gst-inspect-1.0 nv3dsink

# Test video playback
gst-launch-1.0 filesrc location=/path/to/video.mp4 ! qtdemux ! nvv4l2decoder ! nv3dsink
```

## ZeroMQ Integration

The trigger listener subscribes to ZeroMQ messages on `tcp://localhost:5555`.

### Message Types

**Demographic Trigger:**
```json
{"type": "demographic", "age": 35, "gender": "male", "confidence": 0.92}
```

**Loyalty Trigger:**
```json
{"type": "loyalty", "member_id": "uuid", "member_name": "John", "playlist_id": "uuid"}
```

**NCMEC Alert (log only):**
```json
{"type": "ncmec_alert", "case_id": "12345"}
```

### Sending Test Triggers

```python
import zmq
import json

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:5555")

# Send demographic trigger
socket.send_string(json.dumps({
    "type": "demographic",
    "age": 30,
    "gender": "male"
}))
```

## Hub API Integration

### Endpoints Used

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/screens/{id}/config` | GET | Fetch playlist and settings |
| `/api/v1/content/{id}/download` | GET | Download media files |
| `/api/v1/screens/{id}/heartbeat` | POST | Report device status |
| `/api/v1/pairing/request` | POST | Initial device registration |

## Troubleshooting

### Video not playing

1. Check GStreamer plugins are installed:
   ```bash
   gst-inspect-1.0 nv3dsink
   ```

2. Verify media files exist:
   ```bash
   ls -la /home/skillz/media/
   ```

3. Check logs:
   ```bash
   sudo journalctl -u skillz-player -n 100
   ```

### Hub sync failing

1. Verify hub URL in device.json
2. Check network connectivity:
   ```bash
   curl http://192.168.1.100:5000/api/v1/health
   ```

3. Player continues with cached content when hub is unreachable (by design)

### ZeroMQ triggers not received

1. Ensure trigger source is publishing to correct port
2. Check ZeroMQ subscription:
   ```bash
   # Test listener
   python3 -c "
   import zmq
   ctx = zmq.Context()
   s = ctx.socket(zmq.SUB)
   s.connect('tcp://localhost:5555')
   s.setsockopt_string(zmq.SUBSCRIBE, '')
   print(s.recv_string())
   "
   ```

### High CPU usage

- Verify hardware acceleration is working (CPU should be <20% during playback)
- Check for software fallback in logs
- Ensure nv3dsink is being used, not software sink

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SKILLZ_CONFIG_DIR` | Config directory path | `/home/skillz/config` |
| `SKILLZ_MEDIA_DIR` | Media files directory | `/home/skillz/media` |
| `SKILLZ_LOG_DIR` | Log files directory | `/home/skillz/logs` |
| `SKILLZ_HUB_URL` | Override hub URL | From device.json |
| `SKILLZ_ZMQ_PORT` | ZeroMQ trigger port | `5555` |

## Performance Notes

- **Gapless Playback**: The `about-to-finish` signal fires ~2 seconds before video ends
- **Consecutive Same Video**: Requires pipeline reset due to GStreamer limitation
- **Memory Usage**: Typically 200-400MB with hardware acceleration
- **Startup Time**: Playback begins within 2-3 seconds of service start

## License

Proprietary - Skillz Media
