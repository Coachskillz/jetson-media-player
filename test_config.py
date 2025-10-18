"""Quick test of our configuration system."""

from src.common.config import Config

# Load config
config = Config()

# Print some values
print("=" * 50)
print("Configuration Test")
print("=" * 50)
print(f"Device ID: {config.device_id}")
print(f"CMS URL: {config.cms_base_url}")
print(f"Content Dir: {config.content_dir}")
print(f"RTSP Enabled: {config.get('rtsp.enabled')}")
print(f"ML Face Recognition: {config.get('ml.face_recognition.enabled')}")
print(f"Transition Time: {config.get('playback.transition_time')}s")
print("=" * 50)
print("✅ Configuration loaded successfully!")
