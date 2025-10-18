"""
Playback Service with IPC integration.
This wraps the PlaybackController and adds network communication.
"""

import time
import threading
from typing import Optional
from src.playback_service.playback_controller import PlaybackController, PlaybackState
from src.playback_service.playlist import Playlist
from src.playback_service.content_manager import ContentManager
from src.common.ipc import (
    MessagePublisher,
    MessageSubscriber,
    ReplyServer,
    MessageType,
    Message
)
from src.common.config import get_config
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class PlaybackService:
    """
    Playback service with IPC communication.
    
    This service:
    - Publishes playback status updates
    - Listens for trigger events
    - Responds to control commands
    """
    
    def __init__(
        self,
        controller: PlaybackController,
        publish_port: int = 5555,
        trigger_port: int = 5556,
        command_port: int = 5557
    ):
        """
        Initialize playback service.
        
        Args:
            controller: PlaybackController instance
            publish_port: Port to publish status updates
            trigger_port: Port to listen for triggers
            command_port: Port to listen for commands
        """
        self.controller = controller
        self.running = False
        
        # Set up IPC
        self.publisher = MessagePublisher(
            port=publish_port,
            service_name="playback_service"
        )
        
        self.trigger_subscriber = MessageSubscriber(
            host="localhost",
            port=trigger_port,
            service_name="playback_service"
        )
        # Only listen for trigger messages
        self.trigger_subscriber.subscribe_to(MessageType.TRIGGER)
        
        self.command_server = ReplyServer(
            port=command_port,
            service_name="playback_service",
            handler=self._handle_command
        )
        
        # Set content change callback
        self.controller.on_content_change = self._on_content_change
        
        logger.info("Playback service initialized")
    
    def _on_content_change(self, item, trigger):
        """Called when content changes - publish update."""
        self.publisher.publish(
            MessageType.CONTENT_CHANGE,
            {
                "content_id": item.id,
                "filename": item.filename,
                "trigger": trigger,
                "timestamp": time.time()
            }
        )
        logger.info(f"Published content change: {item.filename}")
    
    def _handle_command(self, request: Message) -> dict:
        """
        Handle incoming commands.
        
        Args:
            request: Command message
            
        Returns:
            Reply data
        """
        command = request.data.get("command")
        logger.info(f"Received command: {command}")
        
        if command == "play":
            success = self.controller.start()
            return {"status": "ok" if success else "error", "command": "play"}
        
        elif command == "pause":
            success = self.controller.pause()
            return {"status": "ok" if success else "error", "command": "pause"}
        
        elif command == "resume":
            success = self.controller.resume()
            return {"status": "ok" if success else "error", "command": "resume"}
        
        elif command == "stop":
            success = self.controller.stop()
            return {"status": "ok" if success else "error", "command": "stop"}
        
        elif command == "get_status":
            status = self.controller.get_status()
            return {
                "status": "ok",
                "state": status.state.value,
                "content": status.current_item.filename if status.current_item else None,
                "trigger": status.trigger,
                "position": status.position
            }
        
        else:
            return {"status": "error", "message": f"Unknown command: {command}"}
    
    def _trigger_listener_loop(self):
        """Listen for trigger events in a loop."""
        logger.info("Trigger listener started")
        
        while self.running:
            message = self.trigger_subscriber.receive(timeout_ms=1000)
            
            if message and message.msg_type == MessageType.TRIGGER:
                trigger = message.data.get("trigger")
                if trigger:
                    logger.info(f"Received trigger: {trigger}")
                    # Handle the trigger
                    self.controller.handle_trigger(trigger)
        
        logger.info("Trigger listener stopped")
    
    def _status_publisher_loop(self):
        """Publish status updates periodically."""
        logger.info("Status publisher started")
        
        while self.running:
            # Publish status every 2 seconds
            status = self.controller.get_status()
            self.publisher.publish(
                MessageType.PLAYBACK_STATUS,
                {
                    "state": status.state.value,
                    "content": status.current_item.filename if status.current_item else None,
                    "trigger": status.trigger,
                    "position": status.position,
                    "timestamp": time.time()
                }
            )
            
            time.sleep(2)
        
        logger.info("Status publisher stopped")
    
    def start(self):
        """Start the playback service."""
        if self.running:
            logger.warning("Service already running")
            return
        
        self.running = True
        
        # Start the playback
        self.controller.start()
        
        # Start trigger listener thread
        self.trigger_thread = threading.Thread(
            target=self._trigger_listener_loop,
            daemon=True
        )
        self.trigger_thread.start()
        
        # Start status publisher thread
        self.status_thread = threading.Thread(
            target=self._status_publisher_loop,
            daemon=True
        )
        self.status_thread.start()
        
        # Start command server (blocking)
        logger.info("Playback service started")
        try:
            self.command_server.start()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
            self.stop()
    
    def stop(self):
        """Stop the playback service."""
        if not self.running:
            return
        
        logger.info("Stopping playback service...")
        self.running = False
        
        # Stop controller
        self.controller.stop()
        
        # Close IPC
        self.publisher.close()
        self.trigger_subscriber.close()
        self.command_server.stop()
        
        logger.info("Playback service stopped")


def main():
    """Main entry point for playback service."""
    # Load config
    config = get_config()
    
    # Create content manager
    content_dir = config.get('playback.content_dir', '/media/ssd')
    content_mgr = ContentManager(content_dir)
    
    # Load or create playlist
    # For now, create a test playlist
    from src.playback_service.playlist import MediaItem
    
    playlist = Playlist("default")
    playlist.add_item(MediaItem(
        "ad_001", "default_ad.mp4", "/media/ssd/default_ad.mp4",
        30.0, ["default"], {}
    ))
    playlist.add_item(MediaItem(
        "ad_002", "kids_ad.mp4", "/media/ssd/kids_ad.mp4",
        15.0, ["age:child", "age:teen"], {}
    ))
    playlist.add_item(MediaItem(
        "ad_003", "adult_ad.mp4", "/media/ssd/adult_ad.mp4",
        20.0, ["age:adult", "age:senior"], {}
    ))
    
    # Create controller
    controller = PlaybackController(content_mgr, playlist)
    
    # Create and start service
    service = PlaybackService(
        controller,
        publish_port=config.get('ipc.playback_port', 5555),
        trigger_port=config.get('ipc.trigger_port', 5556),
        command_port=config.get('ipc.ui_port', 5557)
    )
    
    logger.info("Starting playback service...")
    service.start()


if __name__ == "__main__":
    main()
