# Quick Start Guide

## Resume Development

1. Open Terminal
2. Navigate to project:
```bash
   cd ~/jetson-media-player
```
3. Activate virtual environment:
```bash
   source venv/bin/activate
```
4. You should see `(venv)` at the start of your prompt

## What Works Right Now

### Run Tests
```bash
# Test configuration
python test_config.py

# Test playlist and content manager
python test_playback.py

# Test playback controller
python test_controller.py

# Test IPC system
python test_ipc.py

# Test full integration (THIS IS THE BEST ONE!)
python test_integrated_playback.py
```

### Current System Capabilities

Your media player can now:
- ✅ Load playlists with trigger-based content
- ✅ Switch content based on age triggers (age:child, age:adult, etc.)
- ✅ Communicate between services via ZeroMQ messaging
- ✅ Respond to commands (play, pause, resume, stop)
- ✅ Broadcast status updates
- ✅ React to triggers in real-time

## Next Steps

The next components to build are:
1. **Mock Trigger Engine** - Simulates ML face/age detection
2. **CMS API Client** - Downloads content from server
3. **RTSP Service** - Streams second camera
4. **UI Service** - Touchscreen interface
5. **Real ML Integration** - ArcFace + age estimation on Jetson
6. **GStreamer Integration** - Hardware-accelerated video on Jetson

## Project Structure
```
jetson-media-player/
├── src/
│   ├── common/           # Shared utilities
│   │   ├── config.py     # Configuration management
│   │   ├── logger.py     # Logging system
│   │   └── ipc.py        # ZeroMQ messaging
│   ├── playback_service/ # Video playback
│   │   ├── playlist.py           # Playlist management
│   │   ├── content_manager.py    # Local storage
│   │   ├── playback_controller.py # Playback logic
│   │   └── playback_service.py   # IPC-enabled service
│   ├── trigger_engine/   # ML inference (TODO)
│   ├── rtsp_service/     # Camera streaming (TODO)
│   ├── ui_service/       # User interface (TODO)
│   └── cms_client/       # CMS integration (TODO)
├── config/
│   └── default_config.yaml
├── tests/                # Unit tests
└── test_*.py            # Integration tests
```

## Getting Help

- Check `PROGRESS.md` for detailed status
- All code has docstrings explaining what it does
- Tests show examples of how to use each component
