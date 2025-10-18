# Jetson Media Player

Open-source media player for NVIDIA Jetson Orin Nano with AI-powered content switching.

## Features
- Dual CSI camera support
- Real-time face recognition and age estimation
- Hardware-accelerated video playback
- RTSP streaming
- CMS integration
- Touch screen UI

## Development Setup (Mac)

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run tests:
```bash
pytest tests/
```

## Project Structure
- `src/playback_service/` - Video playback and content switching
- `src/trigger_engine/` - ML inference (face recognition, age estimation)
- `src/rtsp_service/` - RTSP streaming server
- `src/ui_service/` - Qt/QML touchscreen interface
- `src/cms_client/` - CMS API integration
- `src/common/` - Shared utilities (IPC, config, logging)

## License
MIT License
