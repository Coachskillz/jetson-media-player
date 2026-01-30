# Deployment Guide — Skillz Media Player (Jetson Orin Nano)

## Prerequisites

- NVIDIA Jetson Orin Nano (8GB) with JetPack 6.x
- Monitor connected via HDMI (1920x1080 minimum)
- Network connectivity (Ethernet or WiFi)
- SSH access to the Jetson device
- CMS server running and accessible from the device's network

## Quick Start

```bash
# SSH into the Jetson
ssh skillz@<device-ip>

# Clone the repo
git clone https://github.com/Coachskillz/jetson-media-player.git /home/skillz/jetson-media-player

# Run the installer (as root)
cd /home/skillz/jetson-media-player
sudo ./install.sh

# Configure the CMS URL
sudo systemctl edit skillz-player
# Add under [Service]:
#   Environment=JMP_CMS_URL=http://your-cms-server:5002

# Start the player
sudo systemctl start skillz-player
```

## Detailed Installation

### 1. System Setup

The install script handles:
- System dependencies (GStreamer, Python GObject bindings, ZeroMQ)
- Creating the `skillz` user with video/audio group access
- Directory structure under `/home/skillz/`
- Python pip dependencies
- systemd service installation

```bash
sudo ./install.sh
```

To verify the installation without running:
```bash
sudo ./install.sh --verify
```

### 2. Directory Structure

After installation:
```
/home/skillz/
├── config/          # device.json, playlist.json, settings.json
├── media/           # Downloaded video/image content
├── logs/            # Application logs (10MB rotation, 5 backups)
├── databases/       # FAISS indexes (NCMEC, loyalty)
└── src/
    ├── player/      # Media player code
    └── common/      # Shared utilities
```

### 3. Configuration

#### Environment Variables (systemd override)

The player reads configuration from `/home/skillz/config/device.json`, but
you can override values via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `JMP_CMS_URL` | CMS server URL | `http://localhost:5002` |
| `JMP_HUB_URL` | Local hub URL | `http://192.168.1.100:5000` |
| `JMP_CONNECTION_MODE` | `hub` or `direct` | `direct` |
| `JMP_SCREEN_ID` | Screen identifier | (from device.json) |

Set via systemd override:
```bash
sudo systemctl edit skillz-player
```
Add:
```ini
[Service]
Environment=JMP_CMS_URL=http://192.168.1.50:5002
Environment=JMP_CONNECTION_MODE=direct
```

#### device.json

Created automatically during pairing. Manual example:
```json
{
  "screen_id": "screen-001",
  "hardware_id": "jetson-abc123def456",
  "hub_url": "http://192.168.1.100:5000",
  "cms_url": "http://cms.example.com:5002",
  "connection_mode": "direct",
  "paired": false
}
```

#### settings.json

Feature flags:
```json
{
  "camera_enabled": true,
  "ncmec_enabled": true,
  "loyalty_enabled": false,
  "demographics_enabled": true
}
```

### 4. Pairing a Device

1. Start the player: `sudo systemctl start skillz-player`
2. The screen displays a **6-digit pairing code**
3. In the CMS web interface, go to **Devices → Add Device**
4. Enter the 6-digit code shown on the Jetson's screen
5. Once approved, the player transitions to content playback
6. If the CMS is unreachable, the player retries every 30 seconds
7. Pairing times out after 10 minutes and auto-retries

### 5. Connection Modes

**Direct Mode** (default): Jetson connects directly to the CMS server.
Best for small deployments or testing.

**Hub Mode**: Jetson connects to a Local Hub (small PC in-store) which
caches content and databases from the Central Hub. Best for production
deployments with multiple screens per location.

## Operations

### Service Management

```bash
# Start
sudo systemctl start skillz-player

# Stop
sudo systemctl stop skillz-player

# Restart
sudo systemctl restart skillz-player

# Status
sudo systemctl status skillz-player

# Enable auto-start on boot
sudo systemctl enable skillz-player

# Disable auto-start
sudo systemctl disable skillz-player
```

### Viewing Logs

```bash
# Live logs
sudo journalctl -u skillz-player -f

# Last 100 lines
sudo journalctl -u skillz-player -n 100

# Logs since last boot
sudo journalctl -u skillz-player -b

# Application log files
ls -la /home/skillz/logs/
```

### Health Dashboard

When the player is running, a health dashboard is available at:
```
http://<device-ip>:8080/
```

API endpoints:
- `GET /api/health` — Quick health check
- `GET /api/system` — CPU, memory, disk, GPU, temperatures
- `GET /api/player` — Player status, device ID, pairing info
- `GET /api/logs` — Recent log entries

Remote commands:
- `POST /api/command/minimize` — Minimize player window
- `POST /api/command/maximize` — Restore fullscreen
- `POST /api/command/restart` — Restart player process
- `POST /api/command/reboot` — Reboot the device

### Re-pairing a Device

From the device screen:
1. Press Escape or tap the top-right corner to open the menu
2. Select "Re-pair Device"

From remote:
```bash
curl -X POST http://<device-ip>:8080/api/command/show_pairing
```

Or delete the pairing state and restart:
```bash
ssh skillz@<device-ip>
python3 -c "
import json
with open('/home/skillz/config/device.json', 'r+') as f:
    d = json.load(f); d['paired'] = False
    f.seek(0); json.dump(d, f, indent=2); f.truncate()
"
sudo systemctl restart skillz-player
```

### Factory Reset

```bash
ssh skillz@<device-ip>
sudo systemctl stop skillz-player
rm -rf /home/skillz/config/*
rm -rf /home/skillz/media/*
rm -rf /home/skillz/databases/*
rm -rf /home/skillz/logs/*
sudo systemctl start skillz-player
```

## Troubleshooting

### Player won't start

```bash
# Check service status
sudo systemctl status skillz-player

# Check for display issues
echo $DISPLAY    # Should be :0
ls -la /home/skillz/.Xauthority

# Verify GStreamer
gst-inspect-1.0 playbin3
gst-inspect-1.0 nv3dsink     # Jetson only

# Verify Python modules
python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; print('GTK OK')"
python3 -c "import zmq; print('ZMQ OK')"
python3 -c "import requests; print('Requests OK')"
```

### Black screen (no video)

- Check media directory has content: `ls /home/skillz/media/`
- If empty, the player is waiting for the sync service to download content
- Check CMS connectivity: `curl http://<cms-url>/api/health`
- Check sync logs: `journalctl -u skillz-player | grep -i sync`

### Pairing screen stuck

- Verify CMS is reachable: `curl http://<cms-url>/api/v1/devices/pairing/status/<device-id>`
- The player auto-retries every 30 seconds if CMS is unreachable
- Pairing times out after 10 minutes and restarts automatically
- Check network: `ping <cms-ip>`

### Content not updating

- Check network monitor status: `curl http://<device-ip>:8080/api/player`
- Manual sync trigger: restart the player service
- Verify content on CMS: check the device's assigned playlist has content
- Check disk space: `df -h /home/skillz/media/`

### High CPU/memory

- Check with: `curl http://<device-ip>:8080/api/system`
- Service is limited to 2GB RAM and 90% CPU by systemd
- If watchdog restarts keep happening, check for GStreamer pipeline leaks

## Uninstall

```bash
sudo ./install.sh --uninstall
```

This stops the service, removes systemd files, and optionally removes
all data under `/home/skillz/`.
