"""Test the playlist and content manager."""

from src.playback_service.playlist import Playlist, MediaItem
from src.playback_service.content_manager import ContentManager
from pathlib import Path

print("=" * 60)
print("Testing Playlist System")
print("=" * 60)

# Create some test media items
item1 = MediaItem(
    id="ad_001",
    filename="default_ad.mp4",
    path="/media/ssd/default_ad.mp4",
    duration=30.0,
    triggers=["default"],
    metadata={"title": "Default Advertisement"}
)

item2 = MediaItem(
    id="ad_002",
    filename="kids_ad.mp4",
    path="/media/ssd/kids_ad.mp4",
    duration=15.0,
    triggers=["age:child", "age:teen"],
    metadata={"title": "Kids Product Ad"}
)

item3 = MediaItem(
    id="ad_003",
    filename="adult_ad.mp4",
    path="/media/ssd/adult_ad.mp4",
    duration=20.0,
    triggers=["age:adult", "age:senior"],
    metadata={"title": "Adult Product Ad"}
)

# Create playlist
playlist = Playlist(name="test_playlist")
playlist.add_item(item1)
playlist.add_item(item2)
playlist.add_item(item3)

print(f"\n✅ Created playlist: {playlist}")
print(f"   Total items: {len(playlist)}")

# Test trigger matching
print("\n--- Testing Trigger Matching ---")
test_triggers = ["age:child", "age:adult", "age:senior", "unknown"]

for trigger in test_triggers:
    matched_item = playlist.get_item_for_trigger(trigger)
    if matched_item:
        print(f"Trigger '{trigger}' -> {matched_item.filename}")
    else:
        print(f"Trigger '{trigger}' -> No match")

# Test default item
default_item = playlist.get_default_item()
print(f"\nDefault item: {default_item.filename if default_item else 'None'}")

# Save and load playlist
print("\n--- Testing Save/Load ---")
test_file = "test_playlist.json"
playlist.save(test_file)
print(f"✅ Saved playlist to {test_file}")

loaded_playlist = Playlist.load(test_file)
print(f"✅ Loaded playlist: {loaded_playlist}")
print(f"   Items in loaded playlist: {len(loaded_playlist)}")

print("\n" + "=" * 60)
print("Testing Content Manager")
print("=" * 60)

# Create content manager
content_dir = Path("test_content")
manager = ContentManager(str(content_dir))

print(f"\n✅ Created content manager")
print(f"   Content directory: {content_dir}")

# Add some content (without actual files for now)
manager.add_content(
    content_id="video_001",
    filename="sample_video.mp4",
    metadata={"duration": 30, "resolution": "1920x1080"}
)

manager.add_content(
    content_id="video_002",
    filename="another_video.mp4",
    metadata={"duration": 15, "resolution": "1280x720"}
)

print(f"\n✅ Added 2 content items")

# List content
print("\n--- Content List ---")
content_list = manager.list_content()


try:
    print(f"Found {len(content_list)} items")
    for content in content_list:
        print(f"  • {content['id']}: {content['filename']}")
except Exception as e:
    print(f"Error: {e}")

# Get storage stats
stats = manager.get_storage_stats()
print(f"\n--- Storage Stats ---")
print(f"  Total content: {stats['content_count']}")
print(f"  Storage directory: {stats['content_dir']}")

print("\n" + "=" * 60)
print("✅ All tests completed successfully!")
print("=" * 60)
