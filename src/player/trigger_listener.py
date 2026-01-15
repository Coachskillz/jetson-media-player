"""
Trigger Listener for Jetson Media Player.
Listens for ZeroMQ trigger messages (demographic, loyalty, NCMEC).
"""

import threading
import time
from typing import Callable, Dict, Any, Optional

from src.common.ipc import MessageSubscriber, MessageType, Message
from src.common.config import get_config
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class TriggerListener:
    """
    Listens for trigger events via ZeroMQ.

    Handles three types of triggers:
    - demographic: Age/gender-based targeting
    - loyalty: Member recognition events
    - ncmec_alert: Missing child alerts (log only)
    """

    # Default port for trigger messages (matches trigger_service.py)
    DEFAULT_TRIGGER_PORT = 5556

    def __init__(
        self,
        host: str = "localhost",
        port: Optional[int] = None,
        on_trigger: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        Initialize trigger listener.

        Args:
            host: Host to connect to for trigger messages
            port: Port to connect to (uses config or default if None)
            on_trigger: Callback function for trigger events
        """
        self.host = host
        self.config = get_config()

        # Get port from config or use provided/default
        if port is not None:
            self.port = port
        else:
            self.port = self.config.get('ipc.trigger_port', self.DEFAULT_TRIGGER_PORT)

        self._on_trigger = on_trigger
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._subscriber: Optional[MessageSubscriber] = None

        # Statistics
        self._stats = {
            "demographic_count": 0,
            "loyalty_count": 0,
            "ncmec_count": 0,
            "unknown_count": 0,
            "last_trigger_time": None
        }

        logger.info(f"TriggerListener initialized (host={host}, port={self.port})")

    def set_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Set or update the trigger callback.

        Args:
            callback: Function to call when a trigger is received
        """
        self._on_trigger = callback
        logger.debug("Trigger callback set")

    def start(self) -> None:
        """
        Start listening for trigger events.
        Runs in a background thread.
        """
        if self._running:
            logger.warning("TriggerListener already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            name="TriggerListener",
            daemon=True
        )
        self._thread.start()
        logger.info(f"TriggerListener started on {self.host}:{self.port}")

    def stop(self) -> None:
        """Stop listening for trigger events."""
        if not self._running:
            return

        logger.info("Stopping TriggerListener...")
        self._running = False

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        # Close subscriber
        if self._subscriber:
            try:
                self._subscriber.close()
            except Exception as e:
                logger.error(f"Error closing subscriber: {e}")
            self._subscriber = None

        logger.info("TriggerListener stopped")

    def _listen_loop(self) -> None:
        """Main listening loop (runs in background thread)."""
        # Initialize subscriber
        try:
            self._subscriber = MessageSubscriber(
                host=self.host,
                port=self.port,
                service_name="media_player"
            )
            # Subscribe specifically to trigger messages
            self._subscriber.subscribe_to(MessageType.TRIGGER)
        except Exception as e:
            logger.error(f"Failed to initialize subscriber: {e}")
            self._running = False
            return

        logger.info("TriggerListener connected, waiting for messages...")

        while self._running:
            try:
                # Receive with timeout so we can check _running flag
                message = self._subscriber.receive(timeout_ms=1000)

                if message is not None:
                    self._handle_message(message)

            except Exception as e:
                logger.error(f"Error in trigger listener loop: {e}")
                # Brief pause before retry
                time.sleep(0.5)

    def _handle_message(self, message: Message) -> None:
        """
        Handle a received message.

        Args:
            message: The received Message object
        """
        if message.msg_type != MessageType.TRIGGER:
            logger.debug(f"Ignoring non-trigger message: {message.msg_type}")
            return

        trigger_data = message.data
        trigger_type = trigger_data.get('type', 'unknown')

        logger.debug(f"Received trigger: {trigger_type}")

        # Update statistics
        self._stats["last_trigger_time"] = time.time()

        # Route based on trigger type
        if trigger_type == 'demographic':
            self._handle_demographic_trigger(trigger_data)
        elif trigger_type == 'loyalty':
            self._handle_loyalty_trigger(trigger_data)
        elif trigger_type == 'ncmec_alert':
            self._handle_ncmec_trigger(trigger_data)
        else:
            # Handle legacy format (trigger in data instead of type)
            if 'trigger' in trigger_data:
                self._handle_legacy_trigger(trigger_data)
            else:
                logger.warning(f"Unknown trigger type: {trigger_type}")
                self._stats["unknown_count"] += 1

    def _handle_demographic_trigger(self, trigger_data: Dict[str, Any]) -> None:
        """
        Handle demographic trigger event.

        Args:
            trigger_data: Trigger data containing age, gender, confidence
        """
        self._stats["demographic_count"] += 1

        age = trigger_data.get('age')
        gender = trigger_data.get('gender')
        confidence = trigger_data.get('confidence', 0.0)

        logger.info(
            f"Demographic trigger: age={age}, gender={gender}, "
            f"confidence={confidence:.2f}"
        )

        self._invoke_callback(trigger_data)

    def _handle_loyalty_trigger(self, trigger_data: Dict[str, Any]) -> None:
        """
        Handle loyalty member trigger event.

        Args:
            trigger_data: Trigger data containing member info
        """
        self._stats["loyalty_count"] += 1

        member_id = trigger_data.get('member_id')
        member_name = trigger_data.get('member_name')
        playlist_id = trigger_data.get('playlist_id')

        logger.info(
            f"Loyalty trigger: member_id={member_id}, "
            f"member_name={member_name}, playlist_id={playlist_id}"
        )

        self._invoke_callback(trigger_data)

    def _handle_ncmec_trigger(self, trigger_data: Dict[str, Any]) -> None:
        """
        Handle NCMEC (National Center for Missing & Exploited Children) alert.
        These are logged but do not change playback.

        Args:
            trigger_data: Trigger data containing case_id
        """
        self._stats["ncmec_count"] += 1

        case_id = trigger_data.get('case_id', 'unknown')

        # Log NCMEC alerts at warning level (important but not playback-related)
        logger.warning(f"NCMEC ALERT - case_id: {case_id}")

        # Invoke callback for logging/telemetry purposes
        # The playlist manager will decide not to change playlist for ncmec_alert
        self._invoke_callback(trigger_data)

    def _handle_legacy_trigger(self, trigger_data: Dict[str, Any]) -> None:
        """
        Handle legacy trigger format from trigger_service.py.
        Format: {trigger: "age:child", confidence: 0.92, timestamp: ...}

        Args:
            trigger_data: Trigger data in legacy format
        """
        trigger_str = trigger_data.get('trigger', '')
        confidence = trigger_data.get('confidence', 0.0)

        logger.debug(f"Legacy trigger: {trigger_str} (confidence={confidence:.2f})")

        # Convert legacy format to standard format
        converted_data = self._convert_legacy_trigger(trigger_str, confidence)

        if converted_data:
            self._invoke_callback(converted_data)

    def _convert_legacy_trigger(
        self,
        trigger_str: str,
        confidence: float
    ) -> Optional[Dict[str, Any]]:
        """
        Convert legacy trigger string to standard format.

        Legacy format: "age:child", "age:adult", "age:default"
        Standard format: {"type": "demographic", "age": 8, ...}

        Args:
            trigger_str: Legacy trigger string
            confidence: Confidence score

        Returns:
            Converted trigger data or None
        """
        if not trigger_str:
            return None

        # Parse "category:value" format
        parts = trigger_str.split(':', 1)
        if len(parts) != 2:
            return None

        category, value = parts

        if category == 'age':
            # Map age categories to representative ages
            age_mapping = {
                'child': 8,
                'teen': 16,
                'adult': 35,
                'senior': 70,
                'default': None
            }

            if value == 'default':
                # Default doesn't trigger playlist change
                return None

            age = age_mapping.get(value)
            if age is not None:
                return {
                    'type': 'demographic',
                    'age': age,
                    'gender': 'any',
                    'confidence': confidence
                }

        return None

    def _invoke_callback(self, trigger_data: Dict[str, Any]) -> None:
        """
        Invoke the registered callback with trigger data.

        Args:
            trigger_data: Trigger data to pass to callback
        """
        if self._on_trigger is None:
            logger.debug("No trigger callback registered")
            return

        try:
            self._on_trigger(trigger_data)
        except Exception as e:
            logger.error(f"Error in trigger callback: {e}")

    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._running

    @property
    def stats(self) -> Dict[str, Any]:
        """Get listener statistics."""
        return self._stats.copy()

    def get_status(self) -> Dict[str, Any]:
        """
        Get listener status for health reporting.

        Returns:
            Dictionary with status information
        """
        return {
            "running": self._running,
            "host": self.host,
            "port": self.port,
            "stats": self._stats.copy()
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"TriggerListener(host={self.host}, port={self.port}, "
            f"running={self._running})"
        )


# Global trigger listener instance
_global_trigger_listener: Optional[TriggerListener] = None


def get_trigger_listener(
    host: str = "localhost",
    port: Optional[int] = None,
    on_trigger: Optional[Callable[[Dict[str, Any]], None]] = None
) -> TriggerListener:
    """
    Get the global trigger listener instance.

    Args:
        host: Host to connect to (only used on first call)
        port: Port to connect to (only used on first call)
        on_trigger: Callback for trigger events (only used on first call)

    Returns:
        TriggerListener instance
    """
    global _global_trigger_listener

    if _global_trigger_listener is None:
        _global_trigger_listener = TriggerListener(
            host=host,
            port=port,
            on_trigger=on_trigger
        )

    return _global_trigger_listener
