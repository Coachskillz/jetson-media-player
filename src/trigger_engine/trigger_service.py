"""
Trigger Engine Service - The brain of the system.
Detects faces, estimates demographics, sends triggers to playback.
"""

import cv2
import time
import threading
from typing import Optional, Dict, Any
from src.trigger_engine.age_detector import AgeDetector
from src.common.ipc import MessagePublisher, MessageType
from src.common.config import get_config
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class TriggerService:
    """
    Trigger engine service that:
    1. Captures camera frames
    2. Detects faces and estimates demographics
    3. Sends triggers to playback service
    4. Collects analytics (if enabled)
    """
    
    def __init__(
        self,
        camera_id: int = 0,
        trigger_publish_port: int = 5556,
        analytics_publish_port: int = 5558
    ):
        """Initialize trigger service."""
        self.camera_id = camera_id
        self.running = False
        self.config = get_config()
        
        # State
        self.last_trigger = None
        self.last_trigger_time = 0
        self.trigger_cooldown = 2.0
        
        # Analytics
        self.analytics_buffer = []
        self.last_analytics_send = time.time()
        self.analytics_interval = self.config.get('ml.analytics.send_interval', 60)
        self.analytics_enabled = self.config.get('ml.analytics.enabled', True)
        
        # Will be initialized in start()
        self.camera = None
        self.detector = None
        self.trigger_publisher = None
        self.analytics_publisher = None
        
        # Store ports for later
        self.trigger_publish_port = trigger_publish_port
        self.analytics_publish_port = analytics_publish_port
        
        logger.info(f"Trigger service initialized (analytics: {self.analytics_enabled})")
    
    def _open_camera(self) -> bool:
        """Open camera connection."""
        try:
            self.camera = cv2.VideoCapture(self.camera_id)
            
            if not self.camera.isOpened():
                logger.error("Failed to open camera")
                return False
            
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.camera.set(cv2.CAP_PROP_FPS, 30)
            
            logger.info("Camera opened successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error opening camera: {e}")
            return False
    
    def _process_frame(self, frame):
        """Process a single frame."""
        detections = self.detector.detect_and_estimate(frame)
        
        if not detections:
            self._send_trigger_if_changed("age:default", 1.0)
            return
        
        trigger, confidence = self.detector.determine_trigger(detections)
        self._send_trigger_if_changed(trigger, confidence)
        
        if self.analytics_enabled:
            self._collect_analytics(detections)
    
    def _send_trigger_if_changed(self, trigger: str, confidence: float):
        """Send trigger only if it changed (with cooldown)."""
        current_time = time.time()
        
        if (trigger != self.last_trigger and 
            current_time - self.last_trigger_time >= self.trigger_cooldown):
            
            logger.info(f"Sending trigger: {trigger} (confidence: {confidence:.2f})")
            
            self.trigger_publisher.publish(
                MessageType.TRIGGER,
                {
                    "trigger": trigger,
                    "confidence": confidence,
                    "timestamp": current_time
                }
            )
            
            self.last_trigger = trigger
            self.last_trigger_time = current_time
    
    def _collect_analytics(self, detections):
        """Collect analytics data (demographics only, no faces)."""
        collect_gender = self.config.get('ml.analytics.collect_gender', True)
        collect_age = self.config.get('ml.analytics.collect_age', True)
        
        for detection in detections:
            analytics_entry = {
                "timestamp": time.time(),
                "device_id": self.config.get('device.id', 'unknown'),
                "location": self.config.get('device.location', 'unknown')
            }
            
            if collect_age:
                analytics_entry["age"] = detection.age
                analytics_entry["age_confidence"] = detection.age_confidence
                
                if detection.age < 27:
                    analytics_entry["age_range"] = "under_27"
                elif detection.age <= 60:
                    analytics_entry["age_range"] = "27-60"
                else:
                    analytics_entry["age_range"] = "61+"
            
            if collect_gender:
                analytics_entry["gender"] = detection.gender
                analytics_entry["gender_confidence"] = detection.gender_confidence
            
            self.analytics_buffer.append(analytics_entry)
        
        current_time = time.time()
        if current_time - self.last_analytics_send >= self.analytics_interval:
            self._send_analytics()
    
    def _send_analytics(self):
        """Send collected analytics to CMS."""
        if not self.analytics_buffer:
            return
        
        logger.info(f"Sending {len(self.analytics_buffer)} analytics entries")
        
        self.analytics_publisher.publish(
            MessageType.TELEMETRY,
            {
                "type": "demographics",
                "entries": self.analytics_buffer,
                "summary": self._summarize_analytics()
            }
        )
        
        self.analytics_buffer = []
        self.last_analytics_send = time.time()
    
    def _summarize_analytics(self) -> Dict[str, Any]:
        """Create summary statistics from analytics buffer."""
        if not self.analytics_buffer:
            return {}
        
        total = len(self.analytics_buffer)
        summary = {"total_detections": total, "time_window": self.analytics_interval}
        
        if self.config.get('ml.analytics.collect_age', True):
            age_ranges = {}
            for entry in self.analytics_buffer:
                age_range = entry.get("age_range", "unknown")
                age_ranges[age_range] = age_ranges.get(age_range, 0) + 1
            summary["age_distribution"] = age_ranges
        
        if self.config.get('ml.analytics.collect_gender', True):
            genders = {}
            for entry in self.analytics_buffer:
                gender = entry.get("gender", "unknown")
                genders[gender] = genders.get(gender, 0) + 1
            summary["gender_distribution"] = genders
        
        return summary
    
    def start(self):
        """Start the trigger service."""
        if self.running:
            logger.warning("Service already running")
            return
        
        # Initialize detector
        self.detector = AgeDetector(use_gpu=False)
        
        # Open camera
        if not self._open_camera():
            logger.error("Cannot start without camera")
            return
        
        # Initialize IPC publishers AFTER camera opens (macOS requirement)
        self.trigger_publisher = MessagePublisher(
            port=self.trigger_publish_port,
            service_name="trigger_engine"
        )
        
        if self.analytics_enabled:
            self.analytics_publisher = MessagePublisher(
                port=self.analytics_publish_port,
                service_name="analytics_engine"
            )
        
        self.running = True
        logger.info("Trigger service started")
        
        try:
            frame_count = 0
            fps_start = time.time()
            
            while self.running:
                ret, frame = self.camera.read()
                
                if not ret:
                    logger.warning("Failed to read frame")
                    time.sleep(0.1)
                    continue
                
                self._process_frame(frame)
                
                frame_count += 1
                if frame_count % 30 == 0:
                    elapsed = time.time() - fps_start
                    fps = 30 / elapsed
                    logger.debug(f"Processing at {fps:.1f} FPS")
                    fps_start = time.time()
                
                time.sleep(0.033)
                
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the trigger service."""
        if not self.running:
            return
        
        logger.info("Stopping trigger service...")
        self.running = False
        
        if self.analytics_enabled and self.analytics_buffer:
            self._send_analytics()
        
        if self.camera:
            self.camera.release()
        
        if self.trigger_publisher:
            self.trigger_publisher.close()
        if self.analytics_enabled and self.analytics_publisher:
            self.analytics_publisher.close()
        
        logger.info("Trigger service stopped")


def main():
    """Main entry point."""
    service = TriggerService(
        camera_id=0,
        trigger_publish_port=5556,
        analytics_publish_port=5558
    )
    
    logger.info("Starting trigger service...")
    service.start()


if __name__ == "__main__":
    main()
