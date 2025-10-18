"""
IPC (Inter-Process Communication) using ZeroMQ.
Enables services to communicate via message passing.
"""

import zmq
import json
import time
from typing import Callable, Optional, Dict, Any
from enum import Enum
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class MessageType(Enum):
    """Types of messages that can be sent between services."""
    TRIGGER = "trigger"           # ML trigger events (age:child, face:recognized, etc.)
    PLAYBACK_STATUS = "status"    # Playback state updates
    CONTENT_CHANGE = "content"    # Content switched notification
    COMMAND = "command"           # Control commands (play, pause, stop)
    TELEMETRY = "telemetry"       # Stats and metrics
    HEARTBEAT = "heartbeat"       # Keep-alive messages


class Message:
    """Standard message format for IPC."""
    
    def __init__(
        self,
        msg_type: MessageType,
        data: Dict[str, Any],
        sender: str,
        timestamp: Optional[float] = None
    ):
        """
        Create a message.
        
        Args:
            msg_type: Type of message
            data: Message payload
            sender: Service name that sent the message
            timestamp: Unix timestamp (auto-generated if None)
        """
        self.msg_type = msg_type
        self.data = data
        self.sender = sender
        self.timestamp = timestamp or time.time()
    
    def to_json(self) -> str:
        """Serialize message to JSON string."""
        return json.dumps({
            "type": self.msg_type.value,
            "data": self.data,
            "sender": self.sender,
            "timestamp": self.timestamp
        })
    
    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        """Deserialize message from JSON string."""
        obj = json.loads(json_str)
        return cls(
            msg_type=MessageType(obj["type"]),
            data=obj["data"],
            sender=obj["sender"],
            timestamp=obj["timestamp"]
        )
    
    def __repr__(self) -> str:
        """String representation."""
        return f"Message(type={self.msg_type.value}, sender={self.sender}, data={self.data})"


class MessagePublisher:
    """Publishes messages to subscribers (PUB socket)."""
    
    def __init__(self, port: int, service_name: str):
        """
        Initialize publisher.
        
        Args:
            port: Port to publish on
            service_name: Name of this service
        """
        self.port = port
        self.service_name = service_name
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{port}")
        
        # Give subscribers time to connect
        time.sleep(0.1)
        
        logger.info(f"Publisher started: {service_name} on port {port}")
    
    def publish(self, msg_type: MessageType, data: Dict[str, Any]) -> None:
        """
        Publish a message.
        
        Args:
            msg_type: Type of message
            data: Message payload
        """
        message = Message(msg_type, data, self.service_name)
        json_str = message.to_json()
        
        # Send message type as topic, then message
        self.socket.send_string(f"{msg_type.value} {json_str}")
        logger.debug(f"Published: {message}")
    
    def close(self) -> None:
        """Close the publisher."""
        self.socket.close()
        self.context.term()
        logger.info(f"Publisher closed: {self.service_name}")


class MessageSubscriber:
    """Subscribes to messages from publishers (SUB socket)."""
    
    def __init__(self, host: str, port: int, service_name: str):
        """
        Initialize subscriber.
        
        Args:
            host: Host to connect to (usually 'localhost')
            port: Port to connect to
            service_name: Name of this service
        """
        self.host = host
        self.port = port
        self.service_name = service_name
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(f"tcp://{host}:{port}")
        
        # Subscribe to all message types by default
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        
        logger.info(f"Subscriber started: {service_name} connected to {host}:{port}")
    
    def subscribe_to(self, msg_type: MessageType) -> None:
        """
        Subscribe to specific message type.
        
        Args:
            msg_type: Message type to subscribe to
        """
        self.socket.setsockopt_string(zmq.SUBSCRIBE, msg_type.value)
        logger.debug(f"Subscribed to: {msg_type.value}")
    
    def receive(self, timeout_ms: int = 1000) -> Optional[Message]:
        """
        Receive a message (blocking with timeout).
        
        Args:
            timeout_ms: Timeout in milliseconds
            
        Returns:
            Message or None if timeout
        """
        # Set receive timeout
        self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        
        try:
            raw_message = self.socket.recv_string()
            # Split topic and message
            parts = raw_message.split(' ', 1)
            if len(parts) == 2:
                json_str = parts[1]
                message = Message.from_json(json_str)
                logger.debug(f"Received: {message}")
                return message
        except zmq.Again:
            # Timeout
            return None
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return None
    
    def close(self) -> None:
        """Close the subscriber."""
        self.socket.close()
        self.context.term()
        logger.info(f"Subscriber closed: {self.service_name}")


class RequestClient:
    """Sends requests and waits for replies (REQ socket)."""
    
    def __init__(self, host: str, port: int, service_name: str):
        """
        Initialize request client.
        
        Args:
            host: Host to connect to
            port: Port to connect to
            service_name: Name of this service
        """
        self.host = host
        self.port = port
        self.service_name = service_name
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect(f"tcp://{host}:{port}")
        
        logger.info(f"Request client started: {service_name} connected to {host}:{port}")
    
    def send_request(
        self,
        msg_type: MessageType,
        data: Dict[str, Any],
        timeout_ms: int = 5000
    ) -> Optional[Message]:
        """
        Send a request and wait for reply.
        
        Args:
            msg_type: Type of message
            data: Request payload
            timeout_ms: Timeout in milliseconds
            
        Returns:
            Reply message or None if timeout
        """
        message = Message(msg_type, data, self.service_name)
        json_str = message.to_json()
        
        # Send request
        self.socket.send_string(json_str)
        logger.debug(f"Sent request: {message}")
        
        # Wait for reply
        self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        
        try:
            reply_str = self.socket.recv_string()
            reply = Message.from_json(reply_str)
            logger.debug(f"Received reply: {reply}")
            return reply
        except zmq.Again:
            logger.warning("Request timeout")
            return None
        except Exception as e:
            logger.error(f"Error in request/reply: {e}")
            return None
    
    def close(self) -> None:
        """Close the client."""
        self.socket.close()
        self.context.term()
        logger.info(f"Request client closed: {self.service_name}")


class ReplyServer:
    """Receives requests and sends replies (REP socket)."""
    
    def __init__(
        self,
        port: int,
        service_name: str,
        handler: Callable[[Message], Dict[str, Any]]
    ):
        """
        Initialize reply server.
        
        Args:
            port: Port to listen on
            service_name: Name of this service
            handler: Function to handle requests and generate replies
        """
        self.port = port
        self.service_name = service_name
        self.handler = handler
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind(f"tcp://*:{port}")
        self.running = False
        
        logger.info(f"Reply server started: {service_name} on port {port}")
    
    def start(self) -> None:
        """Start listening for requests (blocking)."""
        self.running = True
        logger.info(f"Reply server listening: {self.service_name}")
        
        while self.running:
            try:
                # Receive request
                request_str = self.socket.recv_string()
                request = Message.from_json(request_str)
                logger.debug(f"Received request: {request}")
                
                # Handle request
                reply_data = self.handler(request)
                
                # Send reply
                reply = Message(request.msg_type, reply_data, self.service_name)
                self.socket.send_string(reply.to_json())
                logger.debug(f"Sent reply: {reply}")
                
            except Exception as e:
                logger.error(f"Error handling request: {e}")
                # Send error reply
                error_reply = Message(
                    MessageType.COMMAND,
                    {"error": str(e)},
                    self.service_name
                )
                self.socket.send_string(error_reply.to_json())
    
    def stop(self) -> None:
        """Stop the server."""
        self.running = False
        self.socket.close()
        self.context.term()
        logger.info(f"Reply server stopped: {self.service_name}")
