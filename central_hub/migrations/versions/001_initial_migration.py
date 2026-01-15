"""Initial migration - create all tables

Creates the following 7 tables for the Central Hub:
- ncmec_records: NCMEC missing children records
- ncmec_database_versions: NCMEC FAISS database versions
- loyalty_members: Per-network loyalty members
- loyalty_database_versions: Per-network loyalty FAISS versions
- alerts: Match alerts from screens
- alert_notification_logs: Notification delivery logs
- notification_settings: Notification configuration

Revision ID: 001_initial
Revises:
Create Date: 2024-01-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create ncmec_records table
    op.create_table(
        'ncmec_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('case_id', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('age_when_missing', sa.Integer(), nullable=True),
        sa.Column('missing_since', sa.Date(), nullable=True),
        sa.Column('last_known_location', sa.Text(), nullable=True),
        sa.Column('face_encoding', sa.LargeBinary(512), nullable=False),
        sa.Column('photo_path', sa.String(500), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id'),
        sa.CheckConstraint("status IN ('active', 'resolved')", name='check_ncmec_status'),
    )
    op.create_index('ix_ncmec_records_case_id', 'ncmec_records', ['case_id'])
    op.create_index('ix_ncmec_records_status', 'ncmec_records', ['status'])

    # Create ncmec_database_versions table
    op.create_table(
        'ncmec_database_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('record_count', sa.Integer(), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ncmec_database_versions_version', 'ncmec_database_versions', ['version'])

    # Create loyalty_members table
    op.create_table(
        'loyalty_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('member_code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('face_encoding', sa.LargeBinary(512), nullable=False),
        sa.Column('photo_path', sa.String(500), nullable=True),
        sa.Column('assigned_playlist_id', sa.Integer(), nullable=True),
        sa.Column('enrolled_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_store_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('network_id', 'member_code', name='uq_loyalty_member_network_code'),
    )
    op.create_index('ix_loyalty_members_network_id', 'loyalty_members', ['network_id'])
    op.create_index('ix_loyalty_members_member_code', 'loyalty_members', ['member_code'])

    # Create loyalty_database_versions table
    op.create_table(
        'loyalty_database_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('record_count', sa.Integer(), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_loyalty_database_versions_network_id', 'loyalty_database_versions', ['network_id'])
    op.create_index('ix_loyalty_database_versions_version', 'loyalty_database_versions', ['version'])

    # Create alerts table
    op.create_table(
        'alerts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('screen_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('alert_type', sa.String(20), nullable=False),
        sa.Column('case_id', sa.String(50), nullable=True),
        sa.Column('member_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('captured_image_path', sa.String(500), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('status', sa.String(20), nullable=False, server_default='new'),
        sa.Column('reviewed_by', sa.String(255), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("alert_type IN ('ncmec_match', 'loyalty_match')", name='check_alert_type'),
        sa.CheckConstraint("status IN ('new', 'reviewed', 'escalated', 'resolved', 'false_positive')", name='check_alert_status'),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name='check_confidence_range'),
    )
    op.create_index('ix_alerts_network_id', 'alerts', ['network_id'])
    op.create_index('ix_alerts_store_id', 'alerts', ['store_id'])
    op.create_index('ix_alerts_screen_id', 'alerts', ['screen_id'])
    op.create_index('ix_alerts_alert_type', 'alerts', ['alert_type'])
    op.create_index('ix_alerts_case_id', 'alerts', ['case_id'])
    op.create_index('ix_alerts_member_id', 'alerts', ['member_id'])
    op.create_index('ix_alerts_status', 'alerts', ['status'])

    # Create alert_notification_logs table
    op.create_table(
        'alert_notification_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('alert_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('notification_type', sa.String(10), nullable=False),
        sa.Column('recipient', sa.String(255), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ondelete='CASCADE'),
        sa.CheckConstraint("notification_type IN ('email', 'sms')", name='check_notification_type'),
        sa.CheckConstraint("status IN ('sent', 'failed')", name='check_notification_status'),
    )
    op.create_index('ix_alert_notification_logs_alert_id', 'alert_notification_logs', ['alert_id'])

    # Create notification_settings table
    op.create_table(
        'notification_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('recipients', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('delay_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.CheckConstraint("channel IN ('email', 'sms', 'webhook')", name='check_notification_channel'),
        sa.CheckConstraint("delay_minutes >= 0", name='check_delay_minutes_non_negative'),
    )
    op.create_index('ix_notification_settings_name', 'notification_settings', ['name'])
    op.create_index('ix_notification_settings_channel', 'notification_settings', ['channel'])


def downgrade():
    # Drop tables in reverse order (to respect foreign keys)
    op.drop_table('notification_settings')
    op.drop_table('alert_notification_logs')
    op.drop_table('alerts')
    op.drop_table('loyalty_database_versions')
    op.drop_table('loyalty_members')
    op.drop_table('ncmec_database_versions')
    op.drop_table('ncmec_records')
