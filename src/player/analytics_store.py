"""
Local SQLite Analytics Store for Jetson Media Player.

Persists analytics data to survive device reboots and offline periods.
Data is uploaded to the hub/CMS when connectivity is restored.

Tables:
- analytics_buckets: 15-minute aggregated demographic and traffic stats
- loyalty_engagements: Individual loyalty member sightings (consent-based)
- alert_log: NCMEC alert audit trail (no biometric data stored)
- sync_log: Track what has been uploaded to hub

Retention: 90 days local, uploaded data marked but kept for audit.
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.common.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_DB_PATH = "/opt/skillz/detection/analytics"
DEFAULT_DB_FILE = "analytics.db"
RETENTION_DAYS = 90
BUCKET_DURATION_MINUTES = 15


class AnalyticsStore:
    """
    SQLite-backed analytics store for offline-resilient data persistence.

    Thread-safe: uses a connection per thread via thread-local storage.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        db_file: str = DEFAULT_DB_FILE,
    ):
        self.db_dir = Path(os.environ.get("SKILLZ_ANALYTICS_PATH", db_path))
        self.db_file = self.db_dir / db_file
        self._local = threading.local()

        # Ensure directory exists
        self.db_dir.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        self._init_schema()
        logger.info("AnalyticsStore initialized: %s", self.db_file)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_file),
                timeout=10,
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS analytics_buckets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                camera_id TEXT NOT NULL DEFAULT 'camera1',
                people_count INTEGER DEFAULT 0,
                avg_dwell_seconds REAL DEFAULT 0.0,
                age_under_18 INTEGER DEFAULT 0,
                age_18_24 INTEGER DEFAULT 0,
                age_25_34 INTEGER DEFAULT 0,
                age_35_49 INTEGER DEFAULT 0,
                age_50_plus INTEGER DEFAULT 0,
                gender_male INTEGER DEFAULT 0,
                gender_female INTEGER DEFAULT 0,
                loyalty_matches INTEGER DEFAULT 0,
                triggers_sent INTEGER DEFAULT 0,
                uploaded INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(period_start, camera_id)
            );

            CREATE TABLE IF NOT EXISTS loyalty_engagements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                advertiser_id TEXT,
                timestamp TEXT NOT NULL,
                camera_id TEXT NOT NULL DEFAULT 'camera1',
                content_triggered TEXT,
                similarity REAL,
                uploaded INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS alert_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id TEXT UNIQUE NOT NULL,
                ncmec_case_id TEXT,
                similarity REAL,
                camera_id TEXT NOT NULL DEFAULT 'camera0',
                timestamp TEXT NOT NULL,
                forwarded_to_hub INTEGER DEFAULT 0,
                hub_acknowledged INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_type TEXT NOT NULL,
                records_uploaded INTEGER DEFAULT 0,
                last_record_id INTEGER,
                sync_timestamp TEXT DEFAULT (datetime('now')),
                success INTEGER DEFAULT 1,
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_buckets_period
                ON analytics_buckets(period_start);
            CREATE INDEX IF NOT EXISTS idx_buckets_uploaded
                ON analytics_buckets(uploaded);
            CREATE INDEX IF NOT EXISTS idx_loyalty_uploaded
                ON loyalty_engagements(uploaded);
            CREATE INDEX IF NOT EXISTS idx_alert_forwarded
                ON alert_log(forwarded_to_hub);
        """)
        conn.commit()
        logger.debug("Analytics schema initialized")

    # ─── Analytics Buckets ──────────────────────────────────────────

    def get_current_bucket_start(self) -> str:
        """Get the start time of the current 15-minute bucket."""
        now = datetime.utcnow()
        minute = (now.minute // BUCKET_DURATION_MINUTES) * BUCKET_DURATION_MINUTES
        bucket_start = now.replace(minute=minute, second=0, microsecond=0)
        return bucket_start.isoformat()

    def get_current_bucket_end(self) -> str:
        """Get the end time of the current 15-minute bucket."""
        now = datetime.utcnow()
        minute = (now.minute // BUCKET_DURATION_MINUTES) * BUCKET_DURATION_MINUTES
        bucket_start = now.replace(minute=minute, second=0, microsecond=0)
        bucket_end = bucket_start + timedelta(minutes=BUCKET_DURATION_MINUTES)
        return bucket_end.isoformat()

    def record_detection(
        self,
        camera_id: str = "camera1",
        age_bucket: str = "",
        gender: str = "",
        dwell_seconds: float = 0.0,
        is_loyalty_match: bool = False,
        trigger_sent: bool = False,
    ) -> None:
        """
        Record a face detection event in the current analytics bucket.

        Args:
            camera_id: Which camera detected the face
            age_bucket: Age range (under_18, 18_24, 25_34, 35_49, 50_plus)
            gender: Detected gender (male, female)
            dwell_seconds: Time person was visible
            is_loyalty_match: Whether this was a loyalty program match
            trigger_sent: Whether a content trigger was sent to player
        """
        conn = self._get_conn()
        period_start = self.get_current_bucket_start()
        period_end = self.get_current_bucket_end()

        # Upsert the bucket
        conn.execute("""
            INSERT INTO analytics_buckets (period_start, period_end, camera_id)
            VALUES (?, ?, ?)
            ON CONFLICT(period_start, camera_id) DO NOTHING
        """, (period_start, period_end, camera_id))

        # Build update fields
        updates = ["people_count = people_count + 1"]
        if dwell_seconds > 0:
            updates.append(
                f"avg_dwell_seconds = "
                f"(avg_dwell_seconds * people_count + {dwell_seconds}) / "
                f"(people_count + 1)"
            )

        age_column = {
            "under_18": "age_under_18",
            "18_24": "age_18_24",
            "25_34": "age_25_34",
            "35_49": "age_35_49",
            "50_plus": "age_50_plus",
        }.get(age_bucket)
        if age_column:
            updates.append(f"{age_column} = {age_column} + 1")

        if gender == "male":
            updates.append("gender_male = gender_male + 1")
        elif gender == "female":
            updates.append("gender_female = gender_female + 1")

        if is_loyalty_match:
            updates.append("loyalty_matches = loyalty_matches + 1")
        if trigger_sent:
            updates.append("triggers_sent = triggers_sent + 1")

        conn.execute(
            f"UPDATE analytics_buckets SET {', '.join(updates)} "
            f"WHERE period_start = ? AND camera_id = ?",
            (period_start, camera_id)
        )
        conn.commit()

    def get_unuploaded_buckets(self, limit: int = 100) -> List[Dict]:
        """Get analytics buckets that haven't been uploaded yet."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM analytics_buckets WHERE uploaded = 0 "
            "ORDER BY period_start ASC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_buckets_uploaded(self, bucket_ids: List[int]) -> None:
        """Mark analytics buckets as successfully uploaded."""
        if not bucket_ids:
            return
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in bucket_ids)
        conn.execute(
            f"UPDATE analytics_buckets SET uploaded = 1 WHERE id IN ({placeholders})",
            bucket_ids
        )
        conn.commit()

    # ─── Loyalty Engagements ────────────────────────────────────────

    def record_loyalty_engagement(
        self,
        member_id: str,
        advertiser_id: str = "",
        camera_id: str = "camera1",
        content_triggered: str = "",
        similarity: float = 0.0,
    ) -> None:
        """Record a loyalty member recognition event."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO loyalty_engagements
                (member_id, advertiser_id, timestamp, camera_id,
                 content_triggered, similarity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            member_id,
            advertiser_id,
            datetime.utcnow().isoformat(),
            camera_id,
            content_triggered,
            similarity,
        ))
        conn.commit()

    def get_unuploaded_engagements(self, limit: int = 200) -> List[Dict]:
        """Get loyalty engagements that haven't been uploaded."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM loyalty_engagements WHERE uploaded = 0 "
            "ORDER BY timestamp ASC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_engagements_uploaded(self, engagement_ids: List[int]) -> None:
        """Mark engagements as uploaded."""
        if not engagement_ids:
            return
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in engagement_ids)
        conn.execute(
            f"UPDATE loyalty_engagements SET uploaded = 1 "
            f"WHERE id IN ({placeholders})",
            engagement_ids
        )
        conn.commit()

    # ─── Alert Log ──────────────────────────────────────────────────

    def record_alert(
        self,
        alert_id: str,
        ncmec_case_id: str = "",
        similarity: float = 0.0,
        camera_id: str = "camera0",
    ) -> None:
        """
        Record an NCMEC alert for audit purposes.

        NOTE: No biometric data (images, embeddings) is stored.
        Only the alert metadata for audit compliance.
        """
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO alert_log
                    (alert_id, ncmec_case_id, similarity, camera_id, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (
                alert_id,
                ncmec_case_id,
                similarity,
                camera_id,
                datetime.utcnow().isoformat(),
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            logger.debug("Alert %s already logged", alert_id)

    def mark_alert_forwarded(self, alert_id: str) -> None:
        """Mark an alert as successfully forwarded to hub."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE alert_log SET forwarded_to_hub = 1 WHERE alert_id = ?",
            (alert_id,)
        )
        conn.commit()

    def mark_alert_acknowledged(self, alert_id: str) -> None:
        """Mark an alert as acknowledged by hub."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE alert_log SET hub_acknowledged = 1 WHERE alert_id = ?",
            (alert_id,)
        )
        conn.commit()

    def get_unforwarded_alerts(self) -> List[Dict]:
        """Get alerts that haven't been forwarded to hub."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM alert_log WHERE forwarded_to_hub = 0 "
            "ORDER BY timestamp ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    # ─── Sync Upload ────────────────────────────────────────────────

    def log_sync(
        self,
        sync_type: str,
        records_uploaded: int,
        last_record_id: Optional[int] = None,
        success: bool = True,
        error_message: str = "",
    ) -> None:
        """Log a sync upload attempt."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO sync_log
                (sync_type, records_uploaded, last_record_id, success, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (sync_type, records_uploaded, last_record_id, 1 if success else 0, error_message))
        conn.commit()

    # ─── Maintenance ────────────────────────────────────────────────

    def cleanup_old_data(self, retention_days: int = RETENTION_DAYS) -> int:
        """
        Delete data older than retention period.

        Only deletes records that have been successfully uploaded.

        Returns:
            Number of records deleted.
        """
        cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
        conn = self._get_conn()
        total_deleted = 0

        # Clean analytics buckets
        cursor = conn.execute(
            "DELETE FROM analytics_buckets "
            "WHERE uploaded = 1 AND period_start < ?",
            (cutoff,)
        )
        total_deleted += cursor.rowcount

        # Clean loyalty engagements
        cursor = conn.execute(
            "DELETE FROM loyalty_engagements "
            "WHERE uploaded = 1 AND timestamp < ?",
            (cutoff,)
        )
        total_deleted += cursor.rowcount

        # Clean alert log (keep all unacknowledged alerts regardless of age)
        cursor = conn.execute(
            "DELETE FROM alert_log "
            "WHERE hub_acknowledged = 1 AND timestamp < ?",
            (cutoff,)
        )
        total_deleted += cursor.rowcount

        # Clean sync log
        cursor = conn.execute(
            "DELETE FROM sync_log WHERE sync_timestamp < ?",
            (cutoff,)
        )
        total_deleted += cursor.rowcount

        conn.commit()

        if total_deleted > 0:
            logger.info(
                "Cleaned up %d old analytics records (older than %d days)",
                total_deleted, retention_days
            )
            # Reclaim space
            conn.execute("VACUUM")

        return total_deleted

    # ─── Status ─────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Get analytics store statistics."""
        conn = self._get_conn()

        bucket_count = conn.execute(
            "SELECT COUNT(*) FROM analytics_buckets"
        ).fetchone()[0]
        bucket_pending = conn.execute(
            "SELECT COUNT(*) FROM analytics_buckets WHERE uploaded = 0"
        ).fetchone()[0]
        engagement_count = conn.execute(
            "SELECT COUNT(*) FROM loyalty_engagements"
        ).fetchone()[0]
        engagement_pending = conn.execute(
            "SELECT COUNT(*) FROM loyalty_engagements WHERE uploaded = 0"
        ).fetchone()[0]
        alert_count = conn.execute(
            "SELECT COUNT(*) FROM alert_log"
        ).fetchone()[0]
        alert_unforwarded = conn.execute(
            "SELECT COUNT(*) FROM alert_log WHERE forwarded_to_hub = 0"
        ).fetchone()[0]

        # Database file size
        db_size = self.db_file.stat().st_size if self.db_file.exists() else 0

        return {
            "db_file": str(self.db_file),
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "analytics_buckets": {
                "total": bucket_count,
                "pending_upload": bucket_pending,
            },
            "loyalty_engagements": {
                "total": engagement_count,
                "pending_upload": engagement_pending,
            },
            "alerts": {
                "total": alert_count,
                "unforwarded": alert_unforwarded,
            },
        }

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
