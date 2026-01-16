"""
Integration tests for CMS Audit Logs API endpoints.

Tests all audit log API routes:
- GET /api/v1/audit-logs - List audit logs with filtering and pagination
- GET /api/v1/audit-logs/<id> - Get a specific audit log detail
- GET /api/v1/audit-logs/logins - Login history (auth-related actions)
- GET /api/v1/audit-logs/export - Export audit logs as CSV
- GET /api/v1/audit-logs/summary - Dashboard summary statistics
- GET /api/v1/audit-logs/users/<id>/activity - Get a specific user's activity

Each test class covers a specific operation with comprehensive
endpoint validation including success cases, error handling,
and permission enforcement.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta

from cms.models import db, AuditLog, User
from cms.tests.conftest import create_test_session, create_test_audit_log, create_test_user


# =============================================================================
# Helper Functions
# =============================================================================

def _get_auth_headers(session):
    """Create authorization headers with session token."""
    return {'Authorization': f'Bearer {session.token}'}


def _create_multiple_audit_logs(db_session, admin, count=10, category='users'):
    """Helper to create multiple audit logs for testing."""
    logs = []
    for i in range(count):
        log = create_test_audit_log(
            db_session,
            user_id=admin.id,
            user_email=admin.email,
            action=f'user.test_{i}',
            action_category=category,
            user_name=admin.name,
            user_role=admin.role,
            resource_type='user',
            resource_id=f'resource-{i}',
            resource_name=f'Test Resource {i}',
            details=json.dumps({'index': i}),
            ip_address=f'192.168.1.{i % 256}'
        )
        logs.append(log)
    return logs


# =============================================================================
# List Audit Logs API Tests (GET /api/v1/audit-logs)
# =============================================================================

class TestListAuditLogsAPI:
    """Tests for GET /api/v1/audit-logs endpoint."""

    # -------------------------------------------------------------------------
    # Successful List Tests
    # -------------------------------------------------------------------------

    def test_list_audit_logs_success(
        self, client, app, db_session, sample_super_admin, sample_audit_log
    ):
        """GET /audit-logs should return paginated audit logs."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'audit_logs' in data
        assert 'pagination' in data
        assert data['pagination']['page'] == 1
        assert len(data['audit_logs']) >= 1

    def test_list_audit_logs_default_pagination(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs should return default pagination of 50 per page."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['pagination']['per_page'] == 50

    def test_list_audit_logs_custom_pagination(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs should respect custom pagination parameters."""
        session = create_test_session(db_session, sample_super_admin.id)
        _create_multiple_audit_logs(db_session, sample_super_admin, count=20)

        response = client.get(
            '/api/v1/audit-logs?page=2&per_page=5',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['pagination']['page'] == 2
        assert data['pagination']['per_page'] == 5

    def test_list_audit_logs_max_per_page(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs should enforce max per_page of 100."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs?per_page=500',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['pagination']['per_page'] == 100

    # -------------------------------------------------------------------------
    # Filter Tests
    # -------------------------------------------------------------------------

    def test_list_audit_logs_filter_by_user_email(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs?user_email=X should filter by user email."""
        session = create_test_session(db_session, sample_super_admin.id)

        # Create logs for different users
        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='user.test',
            action_category='users'
        )

        response = client.get(
            f'/api/v1/audit-logs?user_email={sample_admin.email}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['audit_logs']:
            assert sample_admin.email in log['user_email']

    def test_list_audit_logs_filter_by_user_id(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs?user_id=X should filter by exact user ID."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='user.test',
            action_category='users'
        )

        response = client.get(
            f'/api/v1/audit-logs?user_id={sample_admin.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['audit_logs']:
            assert log['user_id'] == sample_admin.id

    def test_list_audit_logs_filter_by_action(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?action=X should filter by action name."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.create',
            action_category='users'
        )

        response = client.get(
            '/api/v1/audit-logs?action=user.create',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['audit_logs']:
            assert 'user.create' in log['action']

    def test_list_audit_logs_filter_by_action_category(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?action_category=X should filter by category."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='auth.login',
            action_category='auth'
        )
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.create',
            action_category='users'
        )

        response = client.get(
            '/api/v1/audit-logs?action_category=auth',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['audit_logs']:
            assert log['action_category'] == 'auth'

    def test_list_audit_logs_filter_by_resource_type(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?resource_type=X should filter by resource type."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='device.create',
            action_category='devices',
            resource_type='device',
            resource_id='device-123'
        )

        response = client.get(
            '/api/v1/audit-logs?resource_type=device',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['audit_logs']:
            assert log['resource_type'] == 'device'

    def test_list_audit_logs_filter_by_resource_id(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?resource_id=X should filter by resource ID."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='device.update',
            action_category='devices',
            resource_type='device',
            resource_id='device-456'
        )

        response = client.get(
            '/api/v1/audit-logs?resource_id=device-456',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['audit_logs']:
            assert log['resource_id'] == 'device-456'

    def test_list_audit_logs_filter_by_ip_address(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?ip_address=X should filter by IP address."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.test',
            action_category='users',
            ip_address='10.0.0.100'
        )

        response = client.get(
            '/api/v1/audit-logs?ip_address=10.0.0',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['audit_logs']:
            assert '10.0.0' in log['ip_address']

    def test_list_audit_logs_filter_by_date_range(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs should filter by date range."""
        session = create_test_session(db_session, sample_super_admin.id)

        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=1)).isoformat()
        end_date = (now + timedelta(days=1)).isoformat()

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.test',
            action_category='users'
        )

        response = client.get(
            f'/api/v1/audit-logs?start_date={start_date}&end_date={end_date}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert len(data['audit_logs']) >= 1

    # -------------------------------------------------------------------------
    # Validation Error Tests
    # -------------------------------------------------------------------------

    def test_list_audit_logs_invalid_action_category(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?action_category=invalid should return 400."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs?action_category=invalid',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid action_category' in data['error']

    def test_list_audit_logs_invalid_start_date_format(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?start_date=invalid should return 400."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs?start_date=invalid-date',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid start_date format' in data['error']

    def test_list_audit_logs_invalid_end_date_format(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs?end_date=invalid should return 400."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs?end_date=invalid-date',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid end_date format' in data['error']

    # -------------------------------------------------------------------------
    # Permission Tests
    # -------------------------------------------------------------------------

    def test_list_audit_logs_requires_authentication(self, client, app):
        """GET /audit-logs should reject unauthenticated requests."""
        response = client.get('/api/v1/audit-logs')

        assert response.status_code == 401
        data = response.get_json()
        assert data['code'] == 'missing_token'

    def test_list_audit_logs_requires_admin_role(
        self, client, app, db_session, sample_viewer
    ):
        """GET /audit-logs should reject non-admin users."""
        session = create_test_session(db_session, sample_viewer.id)

        response = client.get(
            '/api/v1/audit-logs',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403
        data = response.get_json()
        assert 'Insufficient permissions' in data['error']

    def test_list_audit_logs_content_manager_forbidden(
        self, client, app, db_session, sample_content_manager
    ):
        """GET /audit-logs should reject content managers."""
        session = create_test_session(db_session, sample_content_manager.id)

        response = client.get(
            '/api/v1/audit-logs',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403


# =============================================================================
# Get Audit Log Detail API Tests (GET /api/v1/audit-logs/<id>)
# =============================================================================

class TestGetAuditLogAPI:
    """Tests for GET /api/v1/audit-logs/<id> endpoint."""

    def test_get_audit_log_success(
        self, client, app, db_session, sample_super_admin, sample_audit_log
    ):
        """GET /audit-logs/<id> should return audit log details."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            f'/api/v1/audit-logs/{sample_audit_log.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_audit_log.id
        assert data['action'] == sample_audit_log.action
        assert data['action_category'] == sample_audit_log.action_category
        assert data['user_email'] == sample_audit_log.user_email
        assert 'created_at' in data

    def test_get_audit_log_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/<id> should return 404 for non-existent log."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/non-existent-log-id',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error'].lower()

    def test_get_audit_log_requires_authentication(self, client, app, sample_audit_log):
        """GET /audit-logs/<id> should reject unauthenticated requests."""
        response = client.get(f'/api/v1/audit-logs/{sample_audit_log.id}')

        assert response.status_code == 401

    def test_get_audit_log_requires_admin_role(
        self, client, app, db_session, sample_viewer, sample_audit_log
    ):
        """GET /audit-logs/<id> should reject non-admin users."""
        session = create_test_session(db_session, sample_viewer.id)

        response = client.get(
            f'/api/v1/audit-logs/{sample_audit_log.id}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403


# =============================================================================
# Login History API Tests (GET /api/v1/audit-logs/logins)
# =============================================================================

class TestLoginHistoryAPI:
    """Tests for GET /api/v1/audit-logs/logins endpoint."""

    def test_list_login_history_success(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/logins should return auth-related logs."""
        session = create_test_session(db_session, sample_super_admin.id)

        # Create auth logs
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.success',
            action_category='auth'
        )
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.failed',
            action_category='auth'
        )

        response = client.get(
            '/api/v1/audit-logs/logins',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'logins' in data
        assert 'pagination' in data
        for log in data['logins']:
            assert log['action_category'] == 'auth'

    def test_list_login_history_filter_by_user_email(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs/logins?user_email=X should filter by email."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='login.success',
            action_category='auth'
        )

        response = client.get(
            f'/api/v1/audit-logs/logins?user_email={sample_admin.email}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['logins']:
            assert sample_admin.email in log['user_email']

    def test_list_login_history_success_only(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/logins?success_only=true should filter successful logins."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.success',
            action_category='auth'
        )
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.failed',
            action_category='auth'
        )

        response = client.get(
            '/api/v1/audit-logs/logins?success_only=true',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for log in data['logins']:
            assert log['action'] == 'login.success'

    def test_list_login_history_date_range(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/logins should filter by date range."""
        session = create_test_session(db_session, sample_super_admin.id)

        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=1)).isoformat()
        end_date = (now + timedelta(days=1)).isoformat()

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.success',
            action_category='auth'
        )

        response = client.get(
            f'/api/v1/audit-logs/logins?start_date={start_date}&end_date={end_date}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert len(data['logins']) >= 1

    def test_list_login_history_invalid_date(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/logins should reject invalid date formats."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/logins?start_date=invalid',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400

    def test_list_login_history_requires_admin(
        self, client, app, db_session, sample_content_manager
    ):
        """GET /audit-logs/logins should reject non-admin users."""
        session = create_test_session(db_session, sample_content_manager.id)

        response = client.get(
            '/api/v1/audit-logs/logins',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403


# =============================================================================
# Export Audit Logs API Tests (GET /api/v1/audit-logs/export)
# =============================================================================

class TestExportAuditLogsAPI:
    """Tests for GET /api/v1/audit-logs/export endpoint."""

    def test_export_audit_logs_success(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/export should return CSV file."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.export_test',
            action_category='users'
        )

        response = client.get(
            '/api/v1/audit-logs/export',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        assert response.content_type == 'text/csv; charset=utf-8'
        assert 'attachment' in response.headers.get('Content-Disposition', '')
        assert 'audit_logs_' in response.headers.get('Content-Disposition', '')

    def test_export_audit_logs_csv_contains_headers(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/export should return CSV with proper headers."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.test',
            action_category='users'
        )

        response = client.get(
            '/api/v1/audit-logs/export',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        csv_content = response.data.decode('utf-8')
        # Check for expected CSV headers
        assert 'ID' in csv_content
        assert 'Timestamp' in csv_content
        assert 'User Email' in csv_content
        assert 'Action' in csv_content
        assert 'Category' in csv_content

    def test_export_audit_logs_filter_by_category(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/export?action_category=X should filter export."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='auth.login',
            action_category='auth'
        )
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.create',
            action_category='users'
        )

        response = client.get(
            '/api/v1/audit-logs/export?action_category=auth',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        csv_content = response.data.decode('utf-8')
        # Should contain auth category
        assert 'auth' in csv_content.lower()

    def test_export_audit_logs_filter_by_date_range(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/export should filter by date range."""
        session = create_test_session(db_session, sample_super_admin.id)

        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=1)).isoformat()
        end_date = (now + timedelta(days=1)).isoformat()

        response = client.get(
            f'/api/v1/audit-logs/export?start_date={start_date}&end_date={end_date}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        assert response.content_type == 'text/csv; charset=utf-8'

    def test_export_audit_logs_invalid_category(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/export?action_category=invalid should return 400."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/export?action_category=invalid',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400

    def test_export_audit_logs_requires_admin(
        self, client, app, db_session, sample_viewer
    ):
        """GET /audit-logs/export should reject non-admin users."""
        session = create_test_session(db_session, sample_viewer.id)

        response = client.get(
            '/api/v1/audit-logs/export',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403


# =============================================================================
# Audit Summary API Tests (GET /api/v1/audit-logs/summary)
# =============================================================================

class TestAuditSummaryAPI:
    """Tests for GET /api/v1/audit-logs/summary endpoint."""

    def test_get_audit_summary_success(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/summary should return summary statistics."""
        session = create_test_session(db_session, sample_super_admin.id)

        # Create some audit logs
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.success',
            action_category='auth'
        )
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.create',
            action_category='users'
        )

        response = client.get(
            '/api/v1/audit-logs/summary',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'period_days' in data
        assert 'total_actions' in data
        assert 'by_category' in data
        assert 'by_action' in data
        assert 'login_stats' in data
        assert 'recent_activity' in data

    def test_get_audit_summary_default_days(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/summary should default to 7 days."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/summary',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['period_days'] == 7

    def test_get_audit_summary_custom_days(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/summary?days=X should accept custom days."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/summary?days=14',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['period_days'] == 14

    def test_get_audit_summary_max_days(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/summary should enforce max 30 days."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/summary?days=100',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['period_days'] == 30

    def test_get_audit_summary_min_days(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/summary should enforce min 1 day."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/summary?days=0',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['period_days'] == 1

    def test_get_audit_summary_login_stats(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/summary should include login statistics."""
        session = create_test_session(db_session, sample_super_admin.id)

        # Create login logs
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.success',
            action_category='auth'
        )
        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='login.failed',
            action_category='auth'
        )

        response = client.get(
            '/api/v1/audit-logs/summary',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        login_stats = data['login_stats']
        assert 'successful_logins' in login_stats
        assert 'failed_logins' in login_stats
        assert 'unique_users' in login_stats

    def test_get_audit_summary_recent_activity(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/summary should include recent activity."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_super_admin.id,
            user_email=sample_super_admin.email,
            action='user.test',
            action_category='users'
        )

        response = client.get(
            '/api/v1/audit-logs/summary',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data['recent_activity'], list)

    def test_get_audit_summary_requires_admin(
        self, client, app, db_session, sample_content_manager
    ):
        """GET /audit-logs/summary should reject non-admin users."""
        session = create_test_session(db_session, sample_content_manager.id)

        response = client.get(
            '/api/v1/audit-logs/summary',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403


# =============================================================================
# User Activity API Tests (GET /api/v1/audit-logs/users/<id>/activity)
# =============================================================================

class TestUserActivityAPI:
    """Tests for GET /api/v1/audit-logs/users/<id>/activity endpoint."""

    def test_get_user_activity_success(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs/users/<id>/activity should return user's activity."""
        session = create_test_session(db_session, sample_super_admin.id)

        # Create activity for the admin user
        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='user.activity_test',
            action_category='users'
        )

        response = client.get(
            f'/api/v1/audit-logs/users/{sample_admin.id}/activity',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert 'user' in data
        assert 'activity' in data
        assert 'pagination' in data
        assert data['user']['id'] == sample_admin.id
        assert data['user']['email'] == sample_admin.email

    def test_get_user_activity_filters_by_user(
        self, client, app, db_session, sample_super_admin, sample_admin, sample_content_manager
    ):
        """GET /audit-logs/users/<id>/activity should only return that user's logs."""
        session = create_test_session(db_session, sample_super_admin.id)

        # Create activity for admin
        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='admin.action',
            action_category='users'
        )
        # Create activity for content manager
        create_test_audit_log(
            db_session,
            user_id=sample_content_manager.id,
            user_email=sample_content_manager.email,
            action='content_manager.action',
            action_category='users'
        )

        response = client.get(
            f'/api/v1/audit-logs/users/{sample_admin.id}/activity',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for activity in data['activity']:
            assert activity['user_id'] == sample_admin.id

    def test_get_user_activity_filter_by_category(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs/users/<id>/activity?action_category=X should filter."""
        session = create_test_session(db_session, sample_super_admin.id)

        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='auth.login',
            action_category='auth'
        )
        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='user.update',
            action_category='users'
        )

        response = client.get(
            f'/api/v1/audit-logs/users/{sample_admin.id}/activity?action_category=auth',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        for activity in data['activity']:
            assert activity['action_category'] == 'auth'

    def test_get_user_activity_filter_by_date(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs/users/<id>/activity should filter by date range."""
        session = create_test_session(db_session, sample_super_admin.id)

        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=1)).isoformat()
        end_date = (now + timedelta(days=1)).isoformat()

        create_test_audit_log(
            db_session,
            user_id=sample_admin.id,
            user_email=sample_admin.email,
            action='user.date_test',
            action_category='users'
        )

        response = client.get(
            f'/api/v1/audit-logs/users/{sample_admin.id}/activity?start_date={start_date}&end_date={end_date}',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert len(data['activity']) >= 1

    def test_get_user_activity_pagination(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs/users/<id>/activity should support pagination."""
        session = create_test_session(db_session, sample_super_admin.id)

        # Create multiple logs
        for i in range(15):
            create_test_audit_log(
                db_session,
                user_id=sample_admin.id,
                user_email=sample_admin.email,
                action=f'user.test_{i}',
                action_category='users'
            )

        response = client.get(
            f'/api/v1/audit-logs/users/{sample_admin.id}/activity?page=1&per_page=5',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['pagination']['page'] == 1
        assert data['pagination']['per_page'] == 5
        assert len(data['activity']) <= 5

    def test_get_user_activity_user_not_found(
        self, client, app, db_session, sample_super_admin
    ):
        """GET /audit-logs/users/<id>/activity should return 404 for non-existent user."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            '/api/v1/audit-logs/users/non-existent-user-id/activity',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error'].lower()

    def test_get_user_activity_invalid_category(
        self, client, app, db_session, sample_super_admin, sample_admin
    ):
        """GET /audit-logs/users/<id>/activity?action_category=invalid should return 400."""
        session = create_test_session(db_session, sample_super_admin.id)

        response = client.get(
            f'/api/v1/audit-logs/users/{sample_admin.id}/activity?action_category=invalid',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 400

    def test_get_user_activity_requires_admin(
        self, client, app, db_session, sample_viewer, sample_admin
    ):
        """GET /audit-logs/users/<id>/activity should reject non-admin users."""
        session = create_test_session(db_session, sample_viewer.id)

        response = client.get(
            f'/api/v1/audit-logs/users/{sample_admin.id}/activity',
            headers=_get_auth_headers(session)
        )

        assert response.status_code == 403


# =============================================================================
# AuditLog Model Tests
# =============================================================================

class TestAuditLogModel:
    """Tests for the AuditLog model."""

    def test_audit_log_to_dict(self, db_session, sample_audit_log):
        """AuditLog.to_dict() should serialize all fields."""
        data = sample_audit_log.to_dict()

        assert 'id' in data
        assert 'user_id' in data
        assert 'user_email' in data
        assert 'action' in data
        assert 'action_category' in data
        assert 'resource_type' in data
        assert 'resource_id' in data
        assert 'details' in data
        assert 'ip_address' in data
        assert 'user_agent' in data
        assert 'created_at' in data

    def test_audit_log_valid_categories(self, db_session):
        """AuditLog.VALID_CATEGORIES should contain expected categories."""
        expected_categories = [
            'auth', 'users', 'devices', 'content',
            'playlists', 'layouts', 'hubs', 'system'
        ]

        for category in expected_categories:
            assert category in AuditLog.VALID_CATEGORIES

    def test_audit_log_repr(self, db_session, sample_audit_log):
        """AuditLog.__repr__() should return readable string."""
        repr_str = repr(sample_audit_log)

        assert 'AuditLog' in repr_str
        assert sample_audit_log.action in repr_str
        assert sample_audit_log.user_email in repr_str
