"""
Full system integration test.
Runs trigger engine + playback service together.
"""

import time
import threading
from src.playback_service.playlist import Playlist, MediaItem
from src.playback_service.content_manager import ContentManager
from src.playback_service.playback_controller import PlaybackController
from src.playback_service.playback_service import PlaybackService
from src.trigger_engine.trigger_service import TriggerService

print("=" * 60)
print("FULL SYSTEM INTEGRATION TEST")
print("=" * 60)

# Create playlist with age-appropriate content
playlist = Playlist("live_playlist")
playlist.add_item(MediaItem(
    "default_001", 
    "default_content.mp4", 
    "/media/ssd/default_content.mp4", 
    30.0, 
    ["default", "age:under_27"],  # Safety content
    {"title": "Safe/Default Content"}
))
playlist.add_item(MediaItem(
    "adult_001",
    "adult_content.mp4",
    "/media/ssd/adult_content.mp4",
    20.0,
    ["age:adult"],
    {"title": "Adult Content (27-60)"}
))
playlist.add_item(MediaItem(
    "senior_001",
    "senior_content.mp4",
    "/media/ssd/senior_content.mp4",
    25.0,
    ["age:senior"],
    {"title": "Senior Content (61+)"}
))

print(f"\n✅ Created playlist with {len(playlist)} items")

# Create content manager
content_mgr = ContentManager("test_content")

# Create playback controller
controller = PlaybackController(content_mgr, playlist)

# Create playback service
playback_service = PlaybackService(
    controller,
    publish_port=5555,      # Status updates
    trigger_port=5556,      # Listens for triggers HERE
    command_port=5557       # Control commands
)

print("✅ Playback service created")

# Start playback service in background
def run_playback():
    playback_service.start()

playback_thread = threading.Thread(target=run_playback, daemon=True)
playback_thread.start()

time.sleep(2)  # Let playback service start
print("✅ Playback service running")

# Create trigger service
trigger_service = TriggerService(
    camera_id=0,
    trigger_publish_port=5556,  # Publishes triggers HERE
    analytics_publish_port=5558
)

print("✅ Trigger service created")
print("\n" + "=" * 60)
print("SYSTEM IS LIVE!")
print("=" * 60)
print("\nWhat's happening:")
print("  1. Camera detects faces and estimates age")
print("  2. Trigger engine sends age triggers")
print("  3. Playback service receives triggers")
print("  4. Content switches based on detected age!")
print("\nTrigger Rules:")
print("  • Under 27: Safe/default content")
print("  • 27-60: Adult content")
print("  • 61+: Senior content")
print("\nPress Ctrl+C to stop")
print("=" * 60)

try:
    # Start trigger service (blocking)
    trigger_service.start()
except KeyboardInterrupt:
    print("\n\nShutting down...")
    trigger_service.stop()
    playback_service.stop()
    print("✅ System stopped")
