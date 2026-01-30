"""
Tests for privacy compliance across the dual-camera architecture.

Verifies that the safety and commercial pipelines maintain proper
data separation and privacy boundaries.
"""

import pytest
from unittest.mock import MagicMock, patch

from jetson_player.processors.age_gating import AgeGatingService
from jetson_player.processors.analytics import AnalyticsAggregator
from jetson_player.services.alert_service import AlertService


class TestSafetyPipelinePrivacy:
    """Verify the safety pipeline does not store biometric data."""

    def test_alert_contains_no_embedding_data(self, tmp_path):
        """Alerts must reference NCMEC case IDs, not raw embeddings."""
        svc = AlertService(
            device_id="dev1", location_id="loc1",
            alert_path=str(tmp_path / "alerts"),
        )

        ncmec_match = {
            "ncmec_id": "NC-12345",
            "case_number": "2024-ABC",
            "similarity": 0.85,
        }

        alert = svc.create_alert(ncmec_match, camera_id="safety")

        assert "ncmec_id" in alert
        assert "case_number" in alert
        assert "embedding" not in alert
        assert "face_image" not in alert
        assert "raw_data" not in alert

    def test_alert_snapshot_disabled_by_default(self, tmp_path):
        """Snapshot inclusion must be opt-in, not default."""
        svc = AlertService(
            device_id="dev1", location_id="loc1",
            alert_path=str(tmp_path / "alerts"),
        )
        assert svc._include_snapshot is False

    def test_alert_has_audit_fields(self, tmp_path):
        """Every alert must include device, location, and timestamp."""
        svc = AlertService(
            device_id="dev1", location_id="loc1",
            alert_path=str(tmp_path / "alerts"),
        )

        alert = svc.create_alert(
            {"ncmec_id": "NC-1", "case_number": "C-1", "similarity": 0.9},
            camera_id="safety",
        )

        assert alert["device_id"] == "dev1"
        assert alert["location_id"] == "loc1"
        assert "timestamp" in alert
        assert "alert_id" in alert


class TestCommercialPipelinePrivacy:
    """Verify the commercial pipeline stores only anonymized aggregates."""

    def test_analytics_bucket_has_no_individual_data(self, tmp_path):
        """Analytics must contain counts and distributions, not individual records."""
        agg = AnalyticsAggregator(
            device_id="dev1", storage_path=str(tmp_path),
        )

        bucket = {
            "start_time": "2026-01-28T10:00:00Z",
            "end_time": "2026-01-28T10:15:00Z",
            "people_count": 12,
            "age_distribution": {"18-24": 3, "25-34": 5, "35-49": 4},
            "gender_distribution": {"male": 7, "female": 5},
            "avg_dwell_seconds": 45.2,
        }

        agg.add_bucket(bucket)

        assert len(agg._pending_buckets) == 1
        stored = agg._pending_buckets[0]
        assert stored["device_id"] == "dev1"
        assert "embeddings" not in stored
        assert "face_images" not in stored
        assert "track_ids" not in stored

    def test_analytics_export_anonymized(self, tmp_path):
        """Exported analytics must not contain individual-level data."""
        agg = AnalyticsAggregator(
            device_id="dev1", storage_path=str(tmp_path),
        )
        agg.add_bucket({
            "people_count": 5,
            "age_distribution": {"25-34": 5},
        })

        export = agg.export()

        assert export is not None
        assert "device_id" in export
        assert "buckets" in export
        for bucket in export["buckets"]:
            assert "embeddings" not in bucket
            assert "face_images" not in bucket


class TestPipelineSeparation:
    """Verify safety and commercial pipelines are isolated."""

    def test_age_gating_does_not_access_ncmec(self):
        """Age gating service must not reference NCMEC data."""
        svc = AgeGatingService()

        assert not hasattr(svc, "_ncmec_db")
        assert not hasattr(svc, "_ncmec_index")
        assert not hasattr(svc, "ncmec")

    def test_alert_service_type_is_ncmec(self, tmp_path):
        """Alert service should only handle NCMEC-type alerts."""
        svc = AlertService(
            device_id="dev1", location_id="loc1",
            alert_path=str(tmp_path / "alerts"),
        )

        alert = svc.create_alert(
            {"ncmec_id": "NC-1", "case_number": "C-1", "similarity": 0.9},
        )

        assert alert["type"] == "ncmec"

    def test_age_gate_trigger_source_is_commercial(self):
        """Age gate triggers must be tagged as commercial source."""
        callback = MagicMock()
        svc = AgeGatingService(trigger_callback=callback)
        svc.set_current_content("c1", "alcohol", alternative_id="alt1")

        svc.evaluate(youngest_detected_age=18)

        trigger = callback.call_args[0][0]
        assert trigger["source"] == "commercial"
        assert trigger["type"] == "trigger"


class TestConsentCompliance:
    """Verify loyalty system requires consent."""

    def test_loyalty_metadata_consent_validation(self):
        """LoyaltyDatabase should warn about missing consent fields."""
        from jetson_player.databases.loyalty_db import LoyaltyDatabase

        db = LoyaltyDatabase()
        # Simulate metadata without consent
        db._metadata = [
            {"member_id": "m1", "advertiser_id": "a1"},
            {"member_id": "m2", "advertiser_id": "a1", "consent_date": "2026-01-01"},
        ]

        with patch("jetson_player.databases.loyalty_db.logger") as mock_logger:
            db._validate_consent()
            mock_logger.warning.assert_called_once()
            assert "1 loyalty entries missing consent_date" in str(
                mock_logger.warning.call_args
            )
