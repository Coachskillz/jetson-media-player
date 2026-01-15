"""
Alert Forwarder Service - Reliable alert forwarding to HQ.

This module provides the AlertForwarder class for forwarding alerts from
Jetson screens to the cloud HQ service. It handles:
- Forwarding alerts from the PendingAlerts queue to HQ
- Managing alert queue status (pending, sending, sent, failed)
- Retrying failed alerts with configurable intervals
- Tracking forwarding attempts and errors

CRITICAL: Alerts must NEVER be lost. This service ensures:
- Alerts remain in the queue until HQ confirms receipt
- Failed forwards are retried indefinitely every 30 seconds
- Queue state is persisted in the database

Example:
    from services.alert_forwarder import AlertForwarder
    from services.hq_client import HQClient
    from config import load_config

    config = load_config()
    hq_client = HQClient(config.hq_url, token='...')
    forwarder = AlertForwarder(hq_client, config)

    # Process all pending alerts
    result = forwarder.process_pending_alerts()
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from services import AlertForwardError
from services.hq_client import HQClient
from config import HubConfig


logger = logging.getLogger(__name__)


# Default retry interval in seconds
DEFAULT_RETRY_INTERVAL_SECONDS = 30

# Default batch size for processing alerts
DEFAULT_BATCH_SIZE = 100


class AlertForwarder:
    """
    Service for forwarding alerts from local queue to HQ.

    This service manages the reliable delivery of alerts from Jetson
    screens to the cloud HQ. Alerts are received by the local API
    and queued in PendingAlerts, then forwarded by this service.

    CRITICAL RELIABILITY GUARANTEES:
    - Alerts are NEVER deleted until HQ confirms receipt
    - Failed forwards are retried indefinitely
    - All errors are logged and tracked per-alert

    Attributes:
        hq_client: HQClient instance for HQ communication
        config: HubConfig instance for configuration
        retry_interval: Seconds between retry attempts (default 30)
    """

    def __init__(
        self,
        hq_client: HQClient,
        config: HubConfig,
        retry_interval: int = DEFAULT_RETRY_INTERVAL_SECONDS,
    ):
        """
        Initialize the alert forwarder service.

        Args:
            hq_client: HQClient instance (should be authenticated)
            config: HubConfig instance with configuration
            retry_interval: Seconds to wait before retrying failed alerts
        """
        self.hq_client = hq_client
        self.config = config
        self.retry_interval = retry_interval

        logger.info(
            f"AlertForwarder initialized with retry_interval={retry_interval}s"
        )

    def forward_alert(self, alert: Any) -> bool:
        """
        Forward a single alert to HQ.

        This method attempts to forward an alert to HQ and updates
        its status based on the result. On success, the alert is
        marked as sent. On failure, the alert is marked for retry.

        Args:
            alert: PendingAlert instance to forward

        Returns:
            True if forwarding succeeded, False otherwise

        Note:
            The alert status is updated in the database by this method.
            Alerts are NEVER deleted on failure - they will be retried.
        """
        from models.pending_alert import PendingAlert

        alert_id = alert.id
        alert_type = alert.alert_type

        logger.debug(f"Forwarding alert {alert_id} (type={alert_type})")

        # Mark alert as being sent
        try:
            alert.mark_sending()
        except Exception as e:
            logger.error(f"Failed to mark alert {alert_id} as sending: {e}")
            return False

        try:
            # Build HQ payload from alert
            hq_payload = alert.to_hq_payload()

            # Send to HQ
            endpoint = '/api/v1/alerts'
            response = self.hq_client.post(endpoint, data=hq_payload)

            # Check for successful acknowledgement
            if response.get('success') or response.get('ack') or response.get('status') == 'ok':
                # HQ confirmed receipt - mark as sent
                alert.mark_sent()
                logger.info(
                    f"Alert {alert_id} forwarded successfully to HQ "
                    f"(type={alert_type}, attempts={alert.attempts})"
                )
                return True
            else:
                # HQ did not confirm - treat as failure
                error_msg = response.get('error', 'HQ did not acknowledge alert')
                alert.mark_failed(
                    error_message=error_msg,
                    retry_delay_seconds=self.retry_interval,
                )
                logger.warning(
                    f"Alert {alert_id} not acknowledged by HQ: {error_msg}"
                )
                return False

        except Exception as e:
            # Any error - mark for retry, NEVER delete
            error_msg = str(e)
            alert.mark_failed(
                error_message=error_msg,
                retry_delay_seconds=self.retry_interval,
            )
            logger.error(
                f"Failed to forward alert {alert_id} to HQ: {error_msg} "
                f"(will retry in {self.retry_interval}s)"
            )
            return False

    def process_pending_alerts(
        self,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> Dict[str, Any]:
        """
        Process all pending alerts ready for forwarding.

        This method queries the PendingAlerts queue for alerts that
        are ready to be forwarded (pending/failed with retry time passed)
        and attempts to forward each one to HQ.

        Args:
            batch_size: Maximum number of alerts to process in one batch

        Returns:
            Dictionary with processing results:
            - processed: Number of alerts attempted
            - succeeded: Number successfully forwarded
            - failed: Number that failed (will be retried)
            - errors: List of error messages

        Note:
            This method should be called periodically by the background
            scheduler (every 30 seconds by default).
        """
        from models.pending_alert import PendingAlert

        result = {
            'processed': 0,
            'succeeded': 0,
            'failed': 0,
            'errors': [],
            'started_at': datetime.utcnow().isoformat(),
            'completed_at': None,
        }

        try:
            # Get alerts ready for processing
            alerts = PendingAlert.get_pending_alerts(limit=batch_size)

            if not alerts:
                logger.debug("No pending alerts to process")
                result['completed_at'] = datetime.utcnow().isoformat()
                return result

            logger.info(f"Processing {len(alerts)} pending alerts")

            # Process each alert
            for alert in alerts:
                result['processed'] += 1

                try:
                    success = self.forward_alert(alert)
                    if success:
                        result['succeeded'] += 1
                    else:
                        result['failed'] += 1
                except Exception as e:
                    result['failed'] += 1
                    error_msg = f"Alert {alert.id}: {str(e)}"
                    result['errors'].append(error_msg)
                    logger.error(f"Error processing alert {alert.id}: {e}")

            result['completed_at'] = datetime.utcnow().isoformat()

            logger.info(
                f"Alert processing completed: {result['succeeded']} succeeded, "
                f"{result['failed']} failed out of {result['processed']} processed"
            )

            return result

        except Exception as e:
            result['completed_at'] = datetime.utcnow().isoformat()
            result['errors'].append(str(e))
            logger.error(f"Error during alert processing: {e}")
            raise AlertForwardError(
                message="Alert processing failed",
                details={'error': str(e), 'result': result},
            )

    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current status of the alert queue.

        Returns:
            Dictionary with queue statistics:
            - pending_count: Total pending/failed alerts
            - by_status: Count by status (pending, failed, sending)
            - by_type: Count by alert type
            - oldest_pending: Timestamp of oldest pending alert
        """
        from models.pending_alert import PendingAlert

        # Get all pending alerts (not sent)
        all_pending = PendingAlert.get_all_pending()

        # Count by status
        by_status = {
            'pending': 0,
            'failed': 0,
            'sending': 0,
        }
        for alert in all_pending:
            status = alert.status
            if status in by_status:
                by_status[status] += 1

        # Count by alert type
        by_type: Dict[str, int] = {}
        for alert in all_pending:
            alert_type = alert.alert_type
            by_type[alert_type] = by_type.get(alert_type, 0) + 1

        # Find oldest pending alert
        oldest_pending = None
        if all_pending:
            oldest = min(all_pending, key=lambda a: a.created_at)
            oldest_pending = oldest.created_at.isoformat()

        return {
            'pending_count': len(all_pending),
            'by_status': by_status,
            'by_type': by_type,
            'oldest_pending': oldest_pending,
        }

    def get_alert_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get alert statistics for the specified time period.

        Args:
            hours: Number of hours to look back (default 24)

        Returns:
            Dictionary with alert statistics:
            - total_received: Total alerts received in period
            - total_sent: Successfully sent alerts in period
            - total_pending: Currently pending alerts
            - average_attempts: Average forwarding attempts
        """
        from datetime import timedelta
        from models.pending_alert import PendingAlert

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Query all alerts in time period
        all_alerts = PendingAlert.query.filter(
            PendingAlert.created_at >= cutoff
        ).all()

        total_received = len(all_alerts)
        total_sent = sum(1 for a in all_alerts if a.status == 'sent')
        total_pending = sum(1 for a in all_alerts if a.status in ('pending', 'failed'))

        # Calculate average attempts for sent alerts
        sent_alerts = [a for a in all_alerts if a.status == 'sent']
        if sent_alerts:
            average_attempts = sum(a.attempts for a in sent_alerts) / len(sent_alerts)
        else:
            average_attempts = 0

        return {
            'period_hours': hours,
            'total_received': total_received,
            'total_sent': total_sent,
            'total_pending': total_pending,
            'average_attempts': round(average_attempts, 2),
        }

    def cleanup_sent_alerts(self, older_than_hours: int = 24) -> int:
        """
        Remove successfully sent alerts older than specified hours.

        This method cleans up the database by removing alerts that
        have been successfully forwarded to HQ. Only sent alerts
        older than the specified threshold are deleted.

        Args:
            older_than_hours: Delete sent alerts older than this

        Returns:
            Number of alerts deleted

        Note:
            This does NOT delete pending/failed alerts. Those are
            NEVER deleted until successfully forwarded.
        """
        from models.pending_alert import PendingAlert

        deleted = PendingAlert.delete_sent_alerts(older_than_hours=older_than_hours)
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} sent alerts older than {older_than_hours} hours")
        return deleted

    def force_retry_all(self) -> int:
        """
        Force immediate retry of all pending/failed alerts.

        This method resets the next_retry_at time for all pending
        alerts, making them immediately eligible for processing.
        Useful for manual intervention or after connectivity restoration.

        Returns:
            Number of alerts reset for immediate retry
        """
        from models.pending_alert import PendingAlert
        from models import db

        # Get all pending alerts
        all_pending = PendingAlert.get_all_pending()

        if not all_pending:
            return 0

        now = datetime.utcnow()
        for alert in all_pending:
            alert.next_retry_at = now
            alert.status = 'pending' if alert.status == 'sending' else alert.status

        db.session.commit()

        logger.info(f"Reset {len(all_pending)} alerts for immediate retry")
        return len(all_pending)

    def forward_alert_by_id(self, alert_id: int) -> bool:
        """
        Forward a specific alert by its ID.

        This method allows manual forwarding of a specific alert,
        bypassing the normal queue processing order.

        Args:
            alert_id: ID of the alert to forward

        Returns:
            True if forwarding succeeded, False otherwise

        Raises:
            AlertForwardError: If alert is not found
        """
        from models.pending_alert import PendingAlert
        from models import db

        alert = db.session.get(PendingAlert, alert_id)
        if not alert:
            raise AlertForwardError(
                message=f"Alert not found: {alert_id}",
                details={'alert_id': alert_id},
            )

        return self.forward_alert(alert)

    def __repr__(self) -> str:
        """String representation."""
        return f"<AlertForwarder retry_interval={self.retry_interval}s>"
