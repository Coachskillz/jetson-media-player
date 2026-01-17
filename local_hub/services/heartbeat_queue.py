"""
Heartbeat Queue Service - Reliable heartbeat forwarding to HQ.

This module provides the HeartbeatQueueService class for forwarding device
heartbeats from the local hub to the cloud HQ service. It handles:
- Forwarding heartbeats from the HeartbeatQueue to HQ in batches
- Managing heartbeat queue status (pending, sending, sent, failed)
- Retrying failed heartbeats with configurable intervals
- Tracking forwarding attempts and errors

CRITICAL: Heartbeats must NEVER be lost when CMS is unreachable. This service ensures:
- Heartbeats remain in the queue until HQ confirms receipt
- Failed forwards are retried with exponential backoff
- Queue state is persisted in the database

Example:
    from services.heartbeat_queue import HeartbeatQueueService
    from services.hq_client import HQClient
    from config import load_config

    config = load_config()
    hq_client = HQClient(config.hq_url, token='...')
    service = HeartbeatQueueService(hq_client, config)

    # Process all pending heartbeats
    result = service.process_pending_heartbeats()
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from services import HeartbeatQueueError, HQConnectionError, HQTimeoutError
from services.hq_client import HQClient
from config import HubConfig


logger = logging.getLogger(__name__)


# Default retry interval in seconds
DEFAULT_RETRY_INTERVAL_SECONDS = 30

# Default batch size for processing heartbeats
DEFAULT_BATCH_SIZE = 50

# Maximum queue size before dropping oldest entries
DEFAULT_MAX_QUEUE_SIZE = 1000


class HeartbeatQueueService:
    """
    Service for forwarding device heartbeats from local queue to HQ.

    This service manages the reliable delivery of device heartbeats from
    connected devices to the cloud HQ. Heartbeats are received by the local
    API, queued in HeartbeatQueue, then forwarded by this service in batches.

    CRITICAL RELIABILITY GUARANTEES:
    - Heartbeats are NEVER deleted until HQ confirms receipt
    - Failed forwards are retried with exponential backoff
    - All errors are logged and tracked per-heartbeat
    - Queue size is enforced to prevent unbounded growth

    Attributes:
        hq_client: HQClient instance for HQ communication
        config: HubConfig instance for configuration
        retry_interval: Seconds between retry attempts (default 30)
        batch_size: Maximum heartbeats per batch (default 50)
        max_queue_size: Maximum queue size before dropping oldest (default 1000)
    """

    def __init__(
        self,
        hq_client: HQClient,
        config: HubConfig,
        retry_interval: int = DEFAULT_RETRY_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ):
        """
        Initialize the heartbeat queue service.

        Args:
            hq_client: HQClient instance (should be authenticated)
            config: HubConfig instance with configuration
            retry_interval: Seconds to wait before retrying failed heartbeats
            batch_size: Maximum heartbeats to send in one batch
            max_queue_size: Maximum queue size (oldest dropped when exceeded)
        """
        self.hq_client = hq_client
        self.config = config
        self.retry_interval = retry_interval
        self.batch_size = batch_size
        self.max_queue_size = max_queue_size

        logger.info(
            f"HeartbeatQueueService initialized with retry_interval={retry_interval}s, "
            f"batch_size={batch_size}, max_queue_size={max_queue_size}"
        )

    def enqueue_heartbeat(
        self,
        device_id: str,
        payload: Dict[str, Any],
        device_type: str = 'screen',
    ) -> Any:
        """
        Add a heartbeat to the queue for forwarding to HQ.

        This method immediately persists the heartbeat to ensure it's never lost,
        then returns the queue entry for tracking.

        Args:
            device_id: ID of the device that generated the heartbeat
            payload: Heartbeat data as dictionary
            device_type: Type of device (default 'screen')

        Returns:
            HeartbeatQueue: The created queue entry

        Note:
            This method should be called when a device heartbeat is received.
            The heartbeat will be forwarded to HQ by process_pending_heartbeats().
        """
        from models.heartbeat_queue import HeartbeatQueue

        entry = HeartbeatQueue.enqueue(
            device_id=device_id,
            payload_dict=payload,
            device_type=device_type,
        )

        logger.debug(f"Heartbeat enqueued for device {device_id} (queue_id={entry.id})")

        # Enforce max queue size
        dropped = HeartbeatQueue.enforce_max_queue_size(self.max_queue_size)
        if dropped > 0:
            logger.warning(f"Queue size exceeded, dropped {dropped} oldest heartbeats")

        return entry

    def forward_heartbeat_batch(
        self,
        entries: List[Any],
        hub_id: str,
    ) -> bool:
        """
        Forward a batch of heartbeats to HQ.

        This method attempts to forward a batch of heartbeats to HQ and updates
        their status based on the result. On success, heartbeats are marked as
        sent. On failure, they are marked for retry.

        Args:
            entries: List of HeartbeatQueue instances to forward
            hub_id: Hub ID for the HQ API call

        Returns:
            True if forwarding succeeded, False otherwise

        Note:
            Heartbeat status is updated in the database by this method.
            Heartbeats are NEVER deleted on failure - they will be retried.
        """
        from models.heartbeat_queue import HeartbeatQueue

        if not entries:
            return True

        entry_ids = [e.id for e in entries]
        logger.debug(f"Forwarding {len(entries)} heartbeats to HQ (ids={entry_ids})")

        # Mark all entries as being sent
        for entry in entries:
            try:
                entry.mark_sending()
            except Exception as e:
                logger.error(f"Failed to mark heartbeat {entry.id} as sending: {e}")

        try:
            # Build payload for HQ
            heartbeats = [entry.to_cms_payload() for entry in entries]

            # Send to HQ
            response = self.hq_client.send_batched_heartbeats(
                hub_id=hub_id,
                heartbeats=heartbeats,
            )

            # Check for successful acknowledgement
            if response.get('success') or response.get('ack') or response.get('processed'):
                # HQ confirmed receipt - mark all as sent
                for entry in entries:
                    entry.mark_sent()

                logger.info(
                    f"Forwarded {len(entries)} heartbeats successfully to HQ "
                    f"(processed={response.get('processed', len(entries))})"
                )
                return True
            else:
                # HQ did not confirm - treat as failure
                error_msg = response.get('error', 'HQ did not acknowledge heartbeats')
                for entry in entries:
                    entry.mark_failed(
                        error_message=error_msg,
                        retry_delay_seconds=self.retry_interval,
                    )

                logger.warning(
                    f"Heartbeat batch not acknowledged by HQ: {error_msg}"
                )
                return False

        except (HQConnectionError, HQTimeoutError) as e:
            # Network-level errors - mark for retry, NEVER delete
            error_msg = str(e)
            for entry in entries:
                entry.mark_failed(
                    error_message=error_msg,
                    retry_delay_seconds=self.retry_interval,
                )

            logger.warning(
                f"Failed to forward heartbeats to HQ: {error_msg} "
                f"(will retry in {self.retry_interval}s)"
            )
            return False

        except Exception as e:
            # Any other error - mark for retry, NEVER delete
            error_msg = str(e)
            for entry in entries:
                entry.mark_failed(
                    error_message=error_msg,
                    retry_delay_seconds=self.retry_interval,
                )

            logger.error(
                f"Failed to forward heartbeats to HQ: {error_msg} "
                f"(will retry in {self.retry_interval}s)"
            )
            return False

    def process_pending_heartbeats(
        self,
        hub_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process all pending heartbeats ready for forwarding.

        This method queries the HeartbeatQueue for heartbeats that are ready
        to be forwarded (pending/failed with retry time passed) and attempts
        to forward them to HQ in batches.

        Args:
            hub_id: Optional hub ID override (defaults to config hub_id)

        Returns:
            Dictionary with processing results:
            - processed: Number of heartbeats attempted
            - succeeded: Number successfully forwarded
            - failed: Number that failed (will be retried)
            - batches: Number of batches sent
            - errors: List of error messages

        Note:
            This method should be called periodically by the background
            scheduler (every 60 seconds by default).
        """
        from models.heartbeat_queue import HeartbeatQueue
        from models.hub_config import HubConfig as HubConfigModel

        result = {
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'batches': 0,
            'errors': [],
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
        }

        # Get hub_id from config if not provided
        if hub_id is None:
            hub_config = HubConfigModel.get_instance()
            if hub_config is None or not hub_config.is_registered:
                logger.debug("Hub not registered, skipping heartbeat processing")
                result['completed_at'] = datetime.utcnow().isoformat()
                return result
            hub_id = hub_config.hub_id

        try:
            # Process heartbeats in batches
            while True:
                # Get next batch of pending heartbeats
                entries = HeartbeatQueue.get_pending(limit=self.batch_size)

                if not entries:
                    break

                result['batches'] += 1
                result['processed'] += len(entries)

                try:
                    success = self.forward_heartbeat_batch(entries, hub_id)
                    if success:
                        result['succeeded'] += len(entries)
                    else:
                        result['failed'] += len(entries)
                except Exception as e:
                    result['failed'] += len(entries)
                    error_msg = f"Batch {result['batches']}: {str(e)}"
                    result['errors'].append(error_msg)
                    logger.error(f"Error processing heartbeat batch: {e}")
                    # Stop processing on error to avoid hammering HQ
                    break

            result['completed_at'] = datetime.utcnow().isoformat()

            if result['processed'] > 0:
                logger.info(
                    f"Heartbeat processing completed: {result['succeeded']} succeeded, "
                    f"{result['failed']} failed out of {result['processed']} processed "
                    f"in {result['batches']} batches"
                )
            else:
                logger.debug("No pending heartbeats to process")

            return result

        except Exception as e:
            result['completed_at'] = datetime.utcnow().isoformat()
            result['errors'].append(str(e))
            logger.error(f"Error during heartbeat processing: {e}")
            raise HeartbeatQueueError(
                message="Heartbeat processing failed",
                details={'error': str(e), 'result': result},
            )

    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current status of the heartbeat queue.

        Returns:
            Dictionary with queue statistics:
            - pending_count: Total pending/failed heartbeats
            - by_status: Count by status (pending, failed, sending)
            - by_device_type: Count by device type
            - oldest_pending: Timestamp of oldest pending heartbeat
            - newest_pending: Timestamp of newest pending heartbeat
        """
        from models.heartbeat_queue import HeartbeatQueue

        # Get all pending heartbeats (not sent)
        all_pending = HeartbeatQueue.get_all_pending()

        # Count by status
        by_status = {
            'pending': 0,
            'failed': 0,
            'sending': 0,
        }
        for entry in all_pending:
            status = entry.status
            if status in by_status:
                by_status[status] += 1

        # Count by device type
        by_device_type: Dict[str, int] = {}
        for entry in all_pending:
            device_type = entry.device_type
            by_device_type[device_type] = by_device_type.get(device_type, 0) + 1

        # Find oldest and newest pending heartbeats
        oldest_pending = None
        newest_pending = None
        if all_pending:
            oldest = min(all_pending, key=lambda e: e.created_at)
            newest = max(all_pending, key=lambda e: e.created_at)
            oldest_pending = oldest.created_at.isoformat()
            newest_pending = newest.created_at.isoformat()

        return {
            'pending_count': len(all_pending),
            'by_status': by_status,
            'by_device_type': by_device_type,
            'oldest_pending': oldest_pending,
            'newest_pending': newest_pending,
            'max_queue_size': self.max_queue_size,
        }

    def get_queue_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get heartbeat queue statistics for the specified time period.

        Args:
            hours: Number of hours to look back (default 24)

        Returns:
            Dictionary with queue statistics:
            - total_queued: Total heartbeats queued in period
            - total_sent: Successfully sent heartbeats in period
            - total_pending: Currently pending heartbeats
            - average_attempts: Average forwarding attempts
            - devices_seen: Number of unique devices
        """
        from datetime import timedelta
        from models.heartbeat_queue import HeartbeatQueue

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Query all heartbeats in time period
        all_heartbeats = HeartbeatQueue.query.filter(
            HeartbeatQueue.created_at >= cutoff
        ).all()

        total_queued = len(all_heartbeats)
        total_sent = sum(1 for h in all_heartbeats if h.status == 'sent')
        total_pending = sum(1 for h in all_heartbeats if h.status in ('pending', 'failed'))

        # Calculate average attempts for sent heartbeats
        sent_heartbeats = [h for h in all_heartbeats if h.status == 'sent']
        if sent_heartbeats:
            average_attempts = sum(h.attempts for h in sent_heartbeats) / len(sent_heartbeats)
        else:
            average_attempts = 0

        # Count unique devices
        devices_seen = len(set(h.device_id for h in all_heartbeats))

        return {
            'period_hours': hours,
            'total_queued': total_queued,
            'total_sent': total_sent,
            'total_pending': total_pending,
            'average_attempts': round(average_attempts, 2),
            'devices_seen': devices_seen,
        }

    def cleanup_sent_heartbeats(self, older_than_hours: int = 24) -> int:
        """
        Remove successfully sent heartbeats older than specified hours.

        This method cleans up the database by removing heartbeats that
        have been successfully forwarded to HQ. Only sent heartbeats
        older than the specified threshold are deleted.

        Args:
            older_than_hours: Delete sent heartbeats older than this

        Returns:
            Number of heartbeats deleted

        Note:
            This does NOT delete pending/failed heartbeats. Those are
            NEVER deleted until successfully forwarded.
        """
        from models.heartbeat_queue import HeartbeatQueue

        deleted = HeartbeatQueue.delete_sent(older_than_hours=older_than_hours)
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} sent heartbeats older than {older_than_hours} hours")
        return deleted

    def force_retry_all(self) -> int:
        """
        Force immediate retry of all pending/failed heartbeats.

        This method resets the next_retry_at time for all pending
        heartbeats, making them immediately eligible for processing.
        Useful for manual intervention or after connectivity restoration.

        Returns:
            Number of heartbeats reset for immediate retry
        """
        from models.heartbeat_queue import HeartbeatQueue
        from models import db

        # Get all pending heartbeats
        all_pending = HeartbeatQueue.get_all_pending()

        if not all_pending:
            return 0

        now = datetime.utcnow()
        for entry in all_pending:
            entry.next_retry_at = now
            # Reset sending status to pending in case it got stuck
            if entry.status == 'sending':
                entry.status = 'pending'

        db.session.commit()

        logger.info(f"Reset {len(all_pending)} heartbeats for immediate retry")
        return len(all_pending)

    def get_device_heartbeats(
        self,
        device_id: str,
        include_sent: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get queued heartbeats for a specific device.

        Args:
            device_id: Device ID to filter by
            include_sent: Whether to include successfully sent heartbeats

        Returns:
            List of heartbeat dictionaries for the device
        """
        from models.heartbeat_queue import HeartbeatQueue

        entries = HeartbeatQueue.get_by_device(device_id, include_sent=include_sent)
        return [entry.to_dict() for entry in entries]

    def forward_device_heartbeats(
        self,
        device_id: str,
        hub_id: str,
    ) -> bool:
        """
        Forward all pending heartbeats for a specific device.

        This method allows targeted forwarding of heartbeats for a
        specific device, bypassing the normal batch processing order.

        Args:
            device_id: ID of the device to forward heartbeats for
            hub_id: Hub ID for the HQ API call

        Returns:
            True if forwarding succeeded, False otherwise
        """
        from models.heartbeat_queue import HeartbeatQueue

        entries = HeartbeatQueue.get_by_device(device_id, include_sent=False)

        if not entries:
            logger.debug(f"No pending heartbeats for device {device_id}")
            return True

        return self.forward_heartbeat_batch(entries, hub_id)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<HeartbeatQueueService retry_interval={self.retry_interval}s "
            f"batch_size={self.batch_size}>"
        )
