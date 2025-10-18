"""Test the IPC messaging system."""

import time
import threading
from src.common.ipc import (
    MessagePublisher,
    MessageSubscriber,
    MessageType,
    RequestClient,
    ReplyServer,
    Message
)

print("=" * 60)
print("Testing IPC System")
print("=" * 60)

# Test 1: Publisher/Subscriber Pattern
print("\n--- Test 1: Publisher/Subscriber ---")

# Create publisher
publisher = MessagePublisher(port=5555, service_name="playback_service")
print("✅ Publisher created on port 5555")

# Create subscriber
subscriber = MessageSubscriber(host="localhost", port=5555, service_name="ui_service")
print("✅ Subscriber created")

# Give ZeroMQ time to establish connections
time.sleep(0.5)

# Publish some messages
print("\nPublishing messages...")
publisher.publish(
    MessageType.TRIGGER,
    {"trigger": "age:child", "confidence": 0.95}
)

publisher.publish(
    MessageType.PLAYBACK_STATUS,
    {"state": "playing", "content": "kids_ad.mp4"}
)

publisher.publish(
    MessageType.CONTENT_CHANGE,
    {"from": "default_ad.mp4", "to": "kids_ad.mp4", "trigger": "age:child"}
)

# Receive messages
print("\nReceiving messages...")
for i in range(3):
    message = subscriber.receive(timeout_ms=1000)
    if message:
        print(f"  📨 Received: {message.msg_type.value} from {message.sender}")
        print(f"     Data: {message.data}")
    else:
        print(f"  ⏰ Timeout waiting for message {i+1}")

# Clean up
publisher.close()
subscriber.close()
print("\n✅ Publisher/Subscriber test completed")

# Test 2: Request/Reply Pattern
print("\n--- Test 2: Request/Reply ---")

# Handler function for the server
def handle_request(request: Message) -> dict:
    """Handle incoming requests."""
    print(f"  🔧 Server handling: {request.msg_type.value}")
    print(f"     Request data: {request.data}")
    
    if request.msg_type == MessageType.COMMAND:
        command = request.data.get("command")
        if command == "get_status":
            return {
                "status": "ok",
                "state": "playing",
                "content": "adult_ad.mp4"
            }
    
    return {"status": "unknown_command"}

# Start server in a separate thread
server = ReplyServer(port=5556, service_name="playback_service", handler=handle_request)

def run_server():
    server.start()

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

time.sleep(0.5)

# Create client
client = RequestClient(host="localhost", port=5556, service_name="ui_service")
print("✅ Request client created")

# Send request
print("\nSending request: get_status")
reply = client.send_request(
    MessageType.COMMAND,
    {"command": "get_status"}
)

if reply:
    print(f"  📬 Reply received from {reply.sender}")
    print(f"     Reply data: {reply.data}")
else:
    print("  ❌ No reply received")

# Clean up
client.close()
server.stop()
print("\n✅ Request/Reply test completed")

print("\n" + "=" * 60)
print("✅ All IPC tests completed!")
print("=" * 60)
