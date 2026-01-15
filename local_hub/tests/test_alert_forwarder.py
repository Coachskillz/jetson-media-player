"""
Integration tests for AlertForwarder service - Alert queue reliability.

Tests the AlertForwarder service to ensure:
- Alerts are forwarded reliably to HQ
- Failed alerts are retried with proper intervals
- Alerts are NEVER lost (critical reliability)
- Queue status and statistics are accurate
- Cleanup operations work correctly

CRITICAL: These tests verify the reliability guarantees of the alert
queue system. Alerts must remain in the queue until HQ confirms receipt.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from models import db, PendingAlert
from services import AlertForwardError, HQConnectionError, HQTimeoutError
from services.alert_forwarder import AlertForwarder


# =============================================================================
# AlertForwarder Initialization Tests
# =============================================================================

class TestAlertForwarderInitialization:
    """Tests for AlertForwarder initialization."""

    def test_initialization_with_defaults(self, app, db_session):
        """AlertForwarder should initialize with default retry interval."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)

        assert forwarder.hq_client is mock_hq_client
        assert forwarder.config is mock_config
        assert forwarder.retry_interval == 30  # Default

    def test_initialization_with_custom_retry_interval(self, app, db_session):
        """AlertForwarder should accept custom retry interval."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config, retry_interval=60)

        assert forwarder.retry_interval == 60

    def test_repr(self, app, db_session):
        """__repr__ should include retry interval."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config, retry_interval=45)

        repr_str = repr(forwarder)
        assert 'AlertForwarder' in repr_str
        assert '45' in repr_str


# =============================================================================
# Forward Single Alert Tests
# =============================================================================

class TestForwardAlert:
    """Tests for forward_alert() method - single alert forwarding."""

    def test_forward_alert_success(self, app, db_session):
        """forward_alert() should mark alert as sent on HQ success."""
        # Create alert
        alert = PendingAlert.create_alert(
            screen_id=1,
            alert_type='ncmec_match',
            payload_dict={'match_id': 'test-123', 'confidence': 0.95}
        )
        assert alert.status == 'pending'

        # Mock HQ client with successful response
        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'success': True, 'alert_id': 'hq-001'}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)

        # Forward alert
        result = forwarder.forward_alert(alert)

        assert result is True
        assert alert.status == 'sent'
        assert alert.attempts == 1
        assert alert.error_message is None
        mock_hq_client.post.assert_called_once()

    def test_forward_alert_success_with_ack_response(self, app, db_session):
        """forward_alert() should accept 'ack' response from HQ."""
        alert = PendingAlert.create_alert(
            screen_id=2,
            alert_type='face_match',
            payload_dict={'data': 'test'}
        )

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'ack': True}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert(alert)

        assert result is True
        assert alert.status == 'sent'

    def test_forward_alert_success_with_status_ok(self, app, db_session):
        """forward_alert() should accept 'status: ok' response from HQ."""
        alert = PendingAlert.create_alert(
            screen_id=3,
            alert_type='system_error',
            payload_dict={'error': 'test'}
        )

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'status': 'ok'}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert(alert)

        assert result is True
        assert alert.status == 'sent'

    def test_forward_alert_hq_not_acknowledged(self, app, db_session):
        """forward_alert() should mark as failed when HQ doesn't acknowledge."""
        alert = PendingAlert.create_alert(
            screen_id=4,
            alert_type='ncmec_match',
            payload_dict={'match_id': 'test-456'}
        )

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'error': 'Invalid payload'}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config, retry_interval=60)
        result = forwarder.forward_alert(alert)

        assert result is False
        assert alert.status == 'failed'
        assert 'Invalid payload' in alert.error_message
        # Alert is NOT deleted - will be retried
        assert PendingAlert.query.get(alert.id) is not None

    def test_forward_alert_connection_error(self, app, db_session):
        """forward_alert() should mark as failed on connection error."""
        alert = PendingAlert.create_alert(
            screen_id=5,
            alert_type='face_match',
            payload_dict={'data': 'test'}
        )

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = HQConnectionError("Connection refused")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config, retry_interval=30)
        result = forwarder.forward_alert(alert)

        assert result is False
        assert alert.status == 'failed'
        assert 'Connection refused' in alert.error_message
        # CRITICAL: Alert is NOT deleted - will be retried
        assert PendingAlert.query.get(alert.id) is not None

    def test_forward_alert_timeout_error(self, app, db_session):
        """forward_alert() should mark as failed on timeout."""
        alert = PendingAlert.create_alert(
            screen_id=6,
            alert_type='system_error',
            payload_dict={'error': 'test'}
        )

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = HQTimeoutError("Request timed out")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert(alert)

        assert result is False
        assert alert.status == 'failed'
        # CRITICAL: Alert is NOT deleted - will be retried
        assert PendingAlert.query.get(alert.id) is not None

    def test_forward_alert_increments_attempts(self, app, db_session):
        """forward_alert() should increment attempts counter."""
        alert = PendingAlert.create_alert(
            screen_id=7,
            alert_type='ncmec_match',
            payload_dict={}
        )
        assert alert.attempts == 0

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = Exception("Random error")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)

        # First attempt
        forwarder.forward_alert(alert)
        assert alert.attempts == 1

        # Manually reset status for retry simulation
        alert.status = 'pending'
        db_session.commit()

        # Second attempt
        forwarder.forward_alert(alert)
        assert alert.attempts == 2

    def test_forward_alert_sets_retry_time(self, app, db_session):
        """forward_alert() should schedule retry on failure."""
        alert = PendingAlert.create_alert(
            screen_id=8,
            alert_type='face_match',
            payload_dict={}
        )
        original_retry = alert.next_retry_at

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = Exception("Error")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config, retry_interval=120)
        forwarder.forward_alert(alert)

        # Retry time should be set to ~120 seconds from now
        assert alert.next_retry_at > original_retry
        time_diff = (alert.next_retry_at - datetime.utcnow()).total_seconds()
        assert 110 < time_diff < 130  # Allow some tolerance


# =============================================================================
# Process Pending Alerts Tests
# =============================================================================

class TestProcessPendingAlerts:
    """Tests for process_pending_alerts() method - batch processing."""

    def test_process_no_pending_alerts(self, app, db_session):
        """process_pending_alerts() should handle empty queue gracefully."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.process_pending_alerts()

        assert result['processed'] == 0
        assert result['succeeded'] == 0
        assert result['failed'] == 0
        assert result['errors'] == []

    def test_process_single_alert_success(self, app, db_session):
        """process_pending_alerts() should process single alert successfully."""
        alert = PendingAlert.create_alert(
            screen_id=10,
            alert_type='ncmec_match',
            payload_dict={'test': 'data'}
        )

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'success': True}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.process_pending_alerts()

        assert result['processed'] == 1
        assert result['succeeded'] == 1
        assert result['failed'] == 0
        assert alert.status == 'sent'

    def test_process_multiple_alerts(self, app, db_session):
        """process_pending_alerts() should process all pending alerts."""
        # Create multiple alerts
        for i in range(5):
            PendingAlert.create_alert(
                screen_id=i,
                alert_type='face_match',
                payload_dict={'id': i}
            )

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'success': True}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.process_pending_alerts()

        assert result['processed'] == 5
        assert result['succeeded'] == 5
        assert result['failed'] == 0

    def test_process_mixed_success_and_failure(self, app, db_session):
        """process_pending_alerts() should handle mixed results."""
        # Create 3 alerts
        for i in range(3):
            PendingAlert.create_alert(
                screen_id=i,
                alert_type='ncmec_match',
                payload_dict={'id': i}
            )

        mock_hq_client = MagicMock()
        # First call succeeds, second fails, third succeeds
        mock_hq_client.post.side_effect = [
            {'success': True},
            Exception("Network error"),
            {'success': True}
        ]
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.process_pending_alerts()

        assert result['processed'] == 3
        assert result['succeeded'] == 2
        assert result['failed'] == 1

    def test_process_respects_batch_size(self, app, db_session):
        """process_pending_alerts() should respect batch_size limit."""
        # Create 10 alerts
        for i in range(10):
            PendingAlert.create_alert(
                screen_id=i,
                alert_type='face_match',
                payload_dict={'id': i}
            )

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'success': True}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.process_pending_alerts(batch_size=3)

        assert result['processed'] == 3
        assert result['succeeded'] == 3

    def test_process_skips_alerts_not_ready_for_retry(self, app, db_session):
        """process_pending_alerts() should skip alerts with future retry time."""
        # Create alert ready for retry
        ready_alert = PendingAlert.create_alert(
            screen_id=20,
            alert_type='ncmec_match',
            payload_dict={}
        )

        # Create alert not ready (future retry)
        not_ready_alert = PendingAlert.create_alert(
            screen_id=21,
            alert_type='ncmec_match',
            payload_dict={}
        )
        not_ready_alert.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'success': True}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.process_pending_alerts()

        assert result['processed'] == 1
        assert ready_alert.status == 'sent'
        assert not_ready_alert.status == 'pending'

    def test_process_skips_sent_alerts(self, app, db_session):
        """process_pending_alerts() should skip already sent alerts."""
        # Create pending alert
        pending_alert = PendingAlert.create_alert(
            screen_id=22,
            alert_type='ncmec_match',
            payload_dict={}
        )

        # Create sent alert
        sent_alert = PendingAlert.create_alert(
            screen_id=23,
            alert_type='ncmec_match',
            payload_dict={}
        )
        sent_alert.mark_sent()

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'success': True}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.process_pending_alerts()

        assert result['processed'] == 1


# =============================================================================
# Queue Status Tests
# =============================================================================

class TestGetQueueStatus:
    """Tests for get_queue_status() method."""

    def test_queue_status_empty(self, app, db_session):
        """get_queue_status() should handle empty queue."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        status = forwarder.get_queue_status()

        assert status['pending_count'] == 0
        assert status['by_status']['pending'] == 0
        assert status['by_status']['failed'] == 0
        assert status['by_type'] == {}
        assert status['oldest_pending'] is None

    def test_queue_status_with_pending(self, app, db_session):
        """get_queue_status() should count pending alerts correctly."""
        PendingAlert.create_alert(screen_id=30, alert_type='ncmec_match', payload_dict={})
        PendingAlert.create_alert(screen_id=31, alert_type='ncmec_match', payload_dict={})
        PendingAlert.create_alert(screen_id=32, alert_type='face_match', payload_dict={})

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        status = forwarder.get_queue_status()

        assert status['pending_count'] == 3
        assert status['by_status']['pending'] == 3
        assert status['by_type']['ncmec_match'] == 2
        assert status['by_type']['face_match'] == 1
        assert status['oldest_pending'] is not None

    def test_queue_status_with_failed(self, app, db_session):
        """get_queue_status() should count failed alerts correctly."""
        pending_alert = PendingAlert.create_alert(
            screen_id=33,
            alert_type='ncmec_match',
            payload_dict={}
        )

        failed_alert = PendingAlert.create_alert(
            screen_id=34,
            alert_type='face_match',
            payload_dict={}
        )
        failed_alert.mark_failed(error_message='Test error')

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        status = forwarder.get_queue_status()

        assert status['pending_count'] == 2
        assert status['by_status']['pending'] == 1
        assert status['by_status']['failed'] == 1

    def test_queue_status_excludes_sent(self, app, db_session):
        """get_queue_status() should exclude sent alerts from count."""
        pending_alert = PendingAlert.create_alert(
            screen_id=35,
            alert_type='ncmec_match',
            payload_dict={}
        )

        sent_alert = PendingAlert.create_alert(
            screen_id=36,
            alert_type='ncmec_match',
            payload_dict={}
        )
        sent_alert.mark_sent()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        status = forwarder.get_queue_status()

        assert status['pending_count'] == 1


# =============================================================================
# Alert Statistics Tests
# =============================================================================

class TestGetAlertStats:
    """Tests for get_alert_stats() method."""

    def test_stats_empty(self, app, db_session):
        """get_alert_stats() should handle no alerts gracefully."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        stats = forwarder.get_alert_stats(hours=24)

        assert stats['total_received'] == 0
        assert stats['total_sent'] == 0
        assert stats['total_pending'] == 0
        assert stats['average_attempts'] == 0

    def test_stats_with_alerts(self, app, db_session):
        """get_alert_stats() should calculate statistics correctly."""
        # Create pending alerts
        PendingAlert.create_alert(screen_id=40, alert_type='ncmec_match', payload_dict={})
        PendingAlert.create_alert(screen_id=41, alert_type='face_match', payload_dict={})

        # Create sent alert
        sent_alert = PendingAlert.create_alert(
            screen_id=42,
            alert_type='system_error',
            payload_dict={}
        )
        sent_alert.mark_sending()  # Sets attempts to 1
        sent_alert.mark_sent()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        stats = forwarder.get_alert_stats(hours=24)

        assert stats['total_received'] == 3
        assert stats['total_sent'] == 1
        assert stats['total_pending'] == 2
        assert stats['average_attempts'] == 1.0

    def test_stats_respects_time_period(self, app, db_session):
        """get_alert_stats() should only count alerts within time period."""
        # Create recent alert
        recent_alert = PendingAlert.create_alert(
            screen_id=43,
            alert_type='ncmec_match',
            payload_dict={}
        )

        # Create old alert (modify created_at to be 48 hours ago)
        old_alert = PendingAlert.create_alert(
            screen_id=44,
            alert_type='ncmec_match',
            payload_dict={}
        )
        old_alert.created_at = datetime.utcnow() - timedelta(hours=48)
        db_session.commit()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        stats = forwarder.get_alert_stats(hours=24)

        assert stats['total_received'] == 1  # Only the recent alert


# =============================================================================
# Cleanup Tests
# =============================================================================

class TestCleanupSentAlerts:
    """Tests for cleanup_sent_alerts() method."""

    def test_cleanup_removes_old_sent_alerts(self, app, db_session):
        """cleanup_sent_alerts() should remove old sent alerts."""
        # Create old sent alert
        old_alert = PendingAlert.create_alert(
            screen_id=50,
            alert_type='ncmec_match',
            payload_dict={}
        )
        old_alert.mark_sending()
        old_alert.mark_sent()
        old_alert.last_attempt_at = datetime.utcnow() - timedelta(hours=48)
        db_session.commit()
        old_alert_id = old_alert.id

        # Create recent sent alert
        recent_alert = PendingAlert.create_alert(
            screen_id=51,
            alert_type='ncmec_match',
            payload_dict={}
        )
        recent_alert.mark_sending()
        recent_alert.mark_sent()
        recent_alert_id = recent_alert.id

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        deleted = forwarder.cleanup_sent_alerts(older_than_hours=24)

        assert deleted == 1
        assert PendingAlert.query.get(old_alert_id) is None
        assert PendingAlert.query.get(recent_alert_id) is not None

    def test_cleanup_never_removes_pending_alerts(self, app, db_session):
        """cleanup_sent_alerts() should NEVER remove pending/failed alerts."""
        # Create pending alert (old)
        pending_alert = PendingAlert.create_alert(
            screen_id=52,
            alert_type='ncmec_match',
            payload_dict={}
        )
        pending_alert.created_at = datetime.utcnow() - timedelta(hours=100)
        db_session.commit()
        pending_id = pending_alert.id

        # Create failed alert (old)
        failed_alert = PendingAlert.create_alert(
            screen_id=53,
            alert_type='face_match',
            payload_dict={}
        )
        failed_alert.mark_failed(error_message='Test')
        failed_alert.last_attempt_at = datetime.utcnow() - timedelta(hours=100)
        db_session.commit()
        failed_id = failed_alert.id

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        deleted = forwarder.cleanup_sent_alerts(older_than_hours=24)

        # CRITICAL: Neither alert should be deleted
        assert deleted == 0
        assert PendingAlert.query.get(pending_id) is not None
        assert PendingAlert.query.get(failed_id) is not None


# =============================================================================
# Force Retry Tests
# =============================================================================

class TestForceRetryAll:
    """Tests for force_retry_all() method."""

    def test_force_retry_all_empty(self, app, db_session):
        """force_retry_all() should handle empty queue gracefully."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        count = forwarder.force_retry_all()

        assert count == 0

    def test_force_retry_all_resets_retry_time(self, app, db_session):
        """force_retry_all() should reset next_retry_at for all pending."""
        # Create alert with future retry time
        alert1 = PendingAlert.create_alert(
            screen_id=60,
            alert_type='ncmec_match',
            payload_dict={}
        )
        alert1.next_retry_at = datetime.utcnow() + timedelta(hours=10)
        db_session.commit()

        # Create failed alert with future retry time
        alert2 = PendingAlert.create_alert(
            screen_id=61,
            alert_type='face_match',
            payload_dict={}
        )
        alert2.mark_failed(error_message='Test')
        alert2.next_retry_at = datetime.utcnow() + timedelta(hours=5)
        db_session.commit()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        count = forwarder.force_retry_all()

        assert count == 2

        # Both alerts should now be ready for immediate retry
        now = datetime.utcnow()
        assert alert1.next_retry_at <= now + timedelta(seconds=5)
        assert alert2.next_retry_at <= now + timedelta(seconds=5)

    def test_force_retry_all_excludes_sent(self, app, db_session):
        """force_retry_all() should not affect sent alerts."""
        pending_alert = PendingAlert.create_alert(
            screen_id=62,
            alert_type='ncmec_match',
            payload_dict={}
        )
        pending_alert.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()

        sent_alert = PendingAlert.create_alert(
            screen_id=63,
            alert_type='ncmec_match',
            payload_dict={}
        )
        sent_alert.mark_sent()

        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        count = forwarder.force_retry_all()

        assert count == 1


# =============================================================================
# Forward Alert By ID Tests
# =============================================================================

class TestForwardAlertById:
    """Tests for forward_alert_by_id() method."""

    def test_forward_by_id_success(self, app, db_session):
        """forward_alert_by_id() should forward specific alert."""
        alert = PendingAlert.create_alert(
            screen_id=70,
            alert_type='ncmec_match',
            payload_dict={'test': 'data'}
        )
        alert_id = alert.id

        mock_hq_client = MagicMock()
        mock_hq_client.post.return_value = {'success': True}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert_by_id(alert_id)

        assert result is True
        assert alert.status == 'sent'

    def test_forward_by_id_not_found(self, app, db_session):
        """forward_alert_by_id() should raise error for non-existent alert."""
        mock_hq_client = MagicMock()
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)

        with pytest.raises(AlertForwardError) as exc_info:
            forwarder.forward_alert_by_id(99999)

        assert 'not found' in str(exc_info.value).lower()


# =============================================================================
# Alert Reliability Tests (CRITICAL)
# =============================================================================

class TestAlertReliability:
    """
    CRITICAL tests for alert queue reliability guarantees.

    These tests verify that alerts are NEVER lost under any circumstances.
    """

    def test_alerts_never_deleted_on_hq_failure(self, app, db_session):
        """Alerts MUST remain in queue when HQ forwarding fails."""
        alert = PendingAlert.create_alert(
            screen_id=80,
            alert_type='ncmec_match',
            payload_dict={'critical': 'data'}
        )
        alert_id = alert.id

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = HQConnectionError("Network down")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert(alert)

        assert result is False
        # CRITICAL: Alert must still exist
        persisted_alert = PendingAlert.query.get(alert_id)
        assert persisted_alert is not None
        assert persisted_alert.status == 'failed'

    def test_alerts_never_deleted_on_timeout(self, app, db_session):
        """Alerts MUST remain in queue when HQ request times out."""
        alert = PendingAlert.create_alert(
            screen_id=81,
            alert_type='face_match',
            payload_dict={'important': 'info'}
        )
        alert_id = alert.id

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = HQTimeoutError("Timeout")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert(alert)

        assert result is False
        # CRITICAL: Alert must still exist
        assert PendingAlert.query.get(alert_id) is not None

    def test_alerts_never_deleted_on_exception(self, app, db_session):
        """Alerts MUST remain in queue on any exception."""
        alert = PendingAlert.create_alert(
            screen_id=82,
            alert_type='system_error',
            payload_dict={'error': 'critical'}
        )
        alert_id = alert.id

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = Exception("Unexpected error")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert(alert)

        assert result is False
        # CRITICAL: Alert must still exist
        assert PendingAlert.query.get(alert_id) is not None

    def test_alerts_only_deleted_after_hq_confirmation(self, app, db_session):
        """Alerts should only be marked sent after HQ confirms receipt."""
        alert = PendingAlert.create_alert(
            screen_id=83,
            alert_type='ncmec_match',
            payload_dict={'data': 'test'}
        )
        alert_id = alert.id

        mock_hq_client = MagicMock()
        # First call: HQ doesn't confirm
        mock_hq_client.post.return_value = {}
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)
        result = forwarder.forward_alert(alert)

        # Alert should NOT be marked as sent
        assert result is False
        assert alert.status == 'failed'

        # Now simulate HQ confirming
        mock_hq_client.post.return_value = {'success': True}
        # Reset status for retry
        alert.status = 'pending'
        db_session.commit()

        result = forwarder.forward_alert(alert)
        assert result is True
        assert alert.status == 'sent'

    def test_retry_persists_through_multiple_failures(self, app, db_session):
        """Alerts should be retryable through multiple failures."""
        alert = PendingAlert.create_alert(
            screen_id=84,
            alert_type='ncmec_match',
            payload_dict={'persistent': 'alert'}
        )
        alert_id = alert.id

        mock_hq_client = MagicMock()
        mock_hq_client.post.side_effect = Exception("Error")
        mock_config = MagicMock()

        forwarder = AlertForwarder(mock_hq_client, mock_config)

        # Simulate 10 failed attempts
        for i in range(10):
            alert.status = 'pending'  # Reset for retry
            db_session.commit()
            forwarder.forward_alert(alert)

        # CRITICAL: Alert must still exist after 10 failures
        persisted = PendingAlert.query.get(alert_id)
        assert persisted is not None
        assert persisted.attempts == 10

        # Now succeed
        mock_hq_client.post.side_effect = None
        mock_hq_client.post.return_value = {'success': True}
        alert.status = 'pending'
        db_session.commit()

        result = forwarder.forward_alert(alert)
        assert result is True
        assert alert.status == 'sent'
