"""Test the integrated playback service with IPC."""

import time
import threading
from src.playback_service.playlist import Playlist, MediaItem
from src.playback_service.content_manager import ContentManager
from src.playback_service.playback_controller import PlaybackController
from src.playback_service.playback_service import PlaybackService
from src.common.ipc import (
    MessagePublisher,
    MessageSubscriber,
    RequestClient,
    MessageType
)

print("=" * 60)
print("Testing Integrated Playback Service")
print("=" * 60)

# Create playlist
playlist = Playlist("test")
playlist.add_item(MediaItem("ad_001", "default_ad.mp4", "/media/ssd/default_ad.mp4", 30.0, ["default"], {}))
playlist.add_item(MediaItem("ad_002", "kids_ad.mp4", "/media/ssd/kids_ad.mp4", 15.0, ["age:child"], {}))
playlist.add_item(MediaItem("ad_003", "adult_ad.mp4", "/media/ssd/adult_ad.mp4", 20.0, ["age:adult"], {}))

# Create content manager
content_mgr = ContentManager("test_content")

# Create controller
controller = PlaybackController(content_mgr, playlist)

# Create playback service
service = PlaybackService(
    controller,
    publish_port=5555,
    trigger_port=5556,
    command_port=5557
)

# Start service in background thread
def run_service():
    service.start()

service_thread = threading.Thread(target=run_service, daemon=True)
service_thread.start()

time.sleep(1)

print("\n✅ Playback service running")

# Create subscribers to listen for updates
status_subscriber = MessageSubscriber("localhost", 5555, "test_client")
print("✅ Subscribed to status updates")

# Create trigger publisher (simulates trigger engine)
trigger_publisher = MessagePublisher(5556, "trigger_engine")
print("✅ Trigger publisher ready")

# Create command client (simulates UI)
command_client = RequestClient("localhost", 5557, "ui_client")
print("✅ Command client ready")

time.sleep(1)

# Test 1: Check initial status
print("\n--- Test 1: Get Status ---")
reply = command_client.send_request(
    MessageType.COMMAND,
    {"command": "get_status"}
)
if reply:
    print(f"Status: {reply.data}")

time.sleep(1)

# Test 2: Send triggers
print("\n--- Test 2: Send Triggers ---")

print("\nSending trigger: age:child")
trigger_publisher.publish(
    MessageType.TRIGGER,
    {"trigger": "age:child", "confidence": 0.95}
)

time.sleep(2)

print("\nListening for status updates...")
for i in range(2):
    msg = status_subscriber.receive(timeout_ms=2000)
    if msg:
        print(f"  Status update: {msg.data}")

print("\nSending trigger: age:adult")
trigger_publisher.publish(
    MessageType.TRIGGER,
    {"trigger": "age:adult", "confidence": 0.92}
)

time.sleep(2)

# Check status
print("\n--- Current Status ---")
reply = command_client.send_request(
    MessageType.COMMAND,
    {"command": "get_status"}
)
if reply:
    print(f"Now playing: {reply.data.get('content')}")
    print(f"State: {reply.data.get('state')}")

# Test 3: Control commands
print("\n--- Test 3: Control Commands ---")

print("\nSending pause command")
reply = command_client.send_request(
    MessageType.COMMAND,
    {"command": "pause"}
)
print(f"Response: {reply.data if reply else 'No response'}")

time.sleep(1)

print("\nSending resume command")
reply = command_client.send_request(
    MessageType.COMMAND,
    {"command": "resume"}
)
print(f"Response: {reply.data if reply else 'No response'}")

# Cleanup
print("\n--- Cleaning Up ---")
command_client.close()
trigger_publisher.close()
status_subscriber.close()
service.stop()

print("\n" + "=" * 60)
print("✅ Integration test completed!")
print("=" * 60)
