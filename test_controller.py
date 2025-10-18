"""Test the playback controller."""

from src.playback_service.playlist import Playlist, MediaItem
from src.playback_service.content_manager import ContentManager
from src.playback_service.playback_controller import PlaybackController
import time

print("=" * 60)
print("Testing Playback Controller")
print("=" * 60)

# Create test playlist
item1 = MediaItem("ad_001", "default_ad.mp4", "/media/ssd/default_ad.mp4", 30.0, ["default"], {})
item2 = MediaItem("ad_002", "kids_ad.mp4", "/media/ssd/kids_ad.mp4", 15.0, ["age:child"], {})
item3 = MediaItem("ad_003", "adult_ad.mp4", "/media/ssd/adult_ad.mp4", 20.0, ["age:adult"], {})

playlist = Playlist("test")
playlist.add_item(item1)
playlist.add_item(item2)
playlist.add_item(item3)

# Create content manager
content_mgr = ContentManager("test_content")

# Callback for content changes
def on_change(item, trigger):
    print(f"  📺 Content changed: {item.filename} (trigger: {trigger})")

# Create controller
controller = PlaybackController(content_mgr, playlist, on_content_change=on_change)

print(f"\n✅ Created controller: {controller}")

# Start playback
print("\n--- Starting Playback ---")
controller.start()
status = controller.get_status()
print(f"State: {status.state.value}")
print(f"Playing: {status.current_item.filename if status.current_item else 'None'}")

time.sleep(1)

# Simulate triggers
print("\n--- Simulating Trigger: age:child ---")
controller.handle_trigger("age:child")
status = controller.get_status()
print(f"Now playing: {status.current_item.filename if status.current_item else 'None'}")

time.sleep(1)

print("\n--- Simulating Trigger: age:adult ---")
controller.handle_trigger("age:adult")
status = controller.get_status()
print(f"Now playing: {status.current_item.filename if status.current_item else 'None'}")

time.sleep(1)

print("\n--- Simulating Same Trigger Again (should not switch) ---")
switched = controller.handle_trigger("age:adult")
print(f"Switched: {switched}")

print("\n--- Pausing Playback ---")
controller.pause()
status = controller.get_status()
print(f"State: {status.state.value}")

print("\n--- Resuming Playback ---")
controller.resume()
status = controller.get_status()
print(f"State: {status.state.value}")

print("\n--- Stopping Playback ---")
controller.stop()
status = controller.get_status()
print(f"State: {status.state.value}")

print("\n" + "=" * 60)
print("✅ Playback controller test completed!")
print("=" * 60)
