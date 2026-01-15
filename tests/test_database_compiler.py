"""
Test Database Compiler Service

Tests the database_compiler service for FAISS index compilation functionality.
"""

import os
import json
import uuid
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import tempfile
from pathlib import Path

# Set testing environment
os.environ['FLASK_ENV'] = 'testing'


class TestCompileNCMECDatabase:
    """Tests for compile_ncmec_database function."""

    def test_compile_ncmec_creates_faiss_index(self, app, mock_face_encoding):
        """Test compilation creates valid FAISS index file."""
        from central_hub.extensions import db
        from central_hub.models import NCMECRecord, NCMECStatus, NCMECDatabaseVersion
        from central_hub.services.database_compiler import compile_ncmec_database

        with app.app_context():
            # Create test records with valid encodings
            for i in range(3):
                record = NCMECRecord(
                    case_id=f'TEST-{i:03d}',
                    name=f'Test Person {i}',
                    face_encoding=mock_face_encoding,
                    status=NCMECStatus.ACTIVE.value,
                )
                db.session.add(record)
            db.session.commit()

            # Use temp directory for output
            with tempfile.TemporaryDirectory() as tmpdir:
                # Patch the config to use temp directory
                with patch('central_hub.services.database_compiler.get_config') as mock_config:
                    mock_cfg = MagicMock()
                    mock_cfg.DATABASES_PATH = Path(tmpdir)
                    mock_cfg.DATABASE_VERSIONS_TO_KEEP = 5
                    mock_cfg.FACE_ENCODING_BYTES = 512
                    mock_cfg.FACE_ENCODING_DIMENSIONS = 128
                    mock_config.return_value = mock_cfg

                    result = compile_ncmec_database()

                    # Verify result structure
                    assert 'version' in result
                    assert 'record_count' in result
                    assert 'file_hash' in result
                    assert 'file_path' in result
                    assert 'metadata_path' in result

                    assert result['version'] == 1
                    assert result['record_count'] == 3

                    # Verify FAISS file was created
                    assert Path(result['file_path']).exists()

                    # Verify file has content
                    file_size = Path(result['file_path']).stat().st_size
                    assert file_size > 0

    def test_compile_ncmec_creates_metadata(self, app, mock_face_encoding):
        """Test metadata JSON matches record count."""
        from central_hub.extensions import db
        from central_hub.models import NCMECRecord, NCMECStatus
        from central_hub.services.database_compiler import compile_ncmec_database

        with app.app_context():
            # Create test records
            for i in range(5):
                record = NCMECRecord(
                    case_id=f'META-{i:03d}',
                    name=f'Person {i}',
                    age_when_missing=10 + i,
                    face_encoding=mock_face_encoding,
                    status=NCMECStatus.ACTIVE.value,
                )
                db.session.add(record)
            db.session.commit()

            with tempfile.TemporaryDirectory() as tmpdir:
                with patch('central_hub.services.database_compiler.get_config') as mock_config:
                    mock_cfg = MagicMock()
                    mock_cfg.DATABASES_PATH = Path(tmpdir)
                    mock_cfg.DATABASE_VERSIONS_TO_KEEP = 5
                    mock_cfg.FACE_ENCODING_BYTES = 512
                    mock_cfg.FACE_ENCODING_DIMENSIONS = 128
                    mock_config.return_value = mock_cfg

                    result = compile_ncmec_database()

                    # Verify metadata file exists
                    metadata_path = Path(result['metadata_path'])
                    assert metadata_path.exists()

                    # Load and verify metadata
                    with open(metadata_path) as f:
                        metadata = json.load(f)

                    assert metadata['record_count'] == 5
                    assert len(metadata['records']) == 5
                    assert metadata['database_type'] == 'ncmec'

    def test_compile_ncmec_empty_database(self, app):
        """Test raises EmptyDatabaseError when no records."""
        from central_hub.services.database_compiler import (
            compile_ncmec_database,
            EmptyDatabaseError
        )

        with app.app_context():
            # No records in database
            with pytest.raises(EmptyDatabaseError) as exc_info:
                compile_ncmec_database()

            assert "no active" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()

    def test_compile_ncmec_version_increment(self, app, mock_face_encoding):
        """Test each compilation increments version number."""
        from central_hub.extensions import db
        from central_hub.models import NCMECRecord, NCMECStatus, NCMECDatabaseVersion
        from central_hub.services.database_compiler import compile_ncmec_database

        with app.app_context():
            # Create initial records
            for i in range(2):
                record = NCMECRecord(
                    case_id=f'VER-{i:03d}',
                    name=f'Person {i}',
                    face_encoding=mock_face_encoding,
                    status=NCMECStatus.ACTIVE.value,
                )
                db.session.add(record)
            db.session.commit()

            with tempfile.TemporaryDirectory() as tmpdir:
                with patch('central_hub.services.database_compiler.get_config') as mock_config:
                    mock_cfg = MagicMock()
                    mock_cfg.DATABASES_PATH = Path(tmpdir)
                    mock_cfg.DATABASE_VERSIONS_TO_KEEP = 5
                    mock_cfg.FACE_ENCODING_BYTES = 512
                    mock_cfg.FACE_ENCODING_DIMENSIONS = 128
                    mock_config.return_value = mock_cfg

                    # First compilation
                    result1 = compile_ncmec_database()
                    assert result1['version'] == 1

                    # Second compilation
                    result2 = compile_ncmec_database()
                    assert result2['version'] == 2

                    # Third compilation
                    result3 = compile_ncmec_database()
                    assert result3['version'] == 3


class TestCompileLoyaltyDatabase:
    """Tests for compile_loyalty_database function."""

    def test_compile_loyalty_network_scoped(self, app, mock_face_encoding):
        """Test creates separate database per network."""
        from central_hub.extensions import db
        from central_hub.models import LoyaltyMember, LoyaltyDatabaseVersion
        from central_hub.services.database_compiler import compile_loyalty_database

        network_id_1 = uuid.uuid4()
        network_id_2 = uuid.uuid4()

        with app.app_context():
            # Create members for network 1
            for i in range(2):
                member = LoyaltyMember(
                    network_id=network_id_1,
                    member_code=f'N1-MEM-{i:03d}',
                    name=f'Member {i}',
                    face_encoding=mock_face_encoding,
                )
                db.session.add(member)

            # Create members for network 2
            for i in range(3):
                member = LoyaltyMember(
                    network_id=network_id_2,
                    member_code=f'N2-MEM-{i:03d}',
                    name=f'Member {i}',
                    face_encoding=mock_face_encoding,
                )
                db.session.add(member)
            db.session.commit()

            with tempfile.TemporaryDirectory() as tmpdir:
                with patch('central_hub.services.database_compiler.get_config') as mock_config:
                    mock_cfg = MagicMock()
                    mock_cfg.DATABASES_PATH = Path(tmpdir)
                    mock_cfg.DATABASE_VERSIONS_TO_KEEP = 5
                    mock_cfg.FACE_ENCODING_BYTES = 512
                    mock_cfg.FACE_ENCODING_DIMENSIONS = 128
                    mock_config.return_value = mock_cfg

                    # Compile network 1
                    result1 = compile_loyalty_database(network_id_1)
                    assert result1['network_id'] == str(network_id_1)
                    assert result1['record_count'] == 2

                    # Compile network 2
                    result2 = compile_loyalty_database(network_id_2)
                    assert result2['network_id'] == str(network_id_2)
                    assert result2['record_count'] == 3

                    # Verify separate files
                    assert result1['file_path'] != result2['file_path']

    def test_compile_loyalty_empty_network(self, app):
        """Test raises EmptyDatabaseError for network with no members."""
        from central_hub.services.database_compiler import (
            compile_loyalty_database,
            EmptyDatabaseError
        )

        network_id = uuid.uuid4()

        with app.app_context():
            with pytest.raises(EmptyDatabaseError) as exc_info:
                compile_loyalty_database(network_id)

            assert "no loyalty members" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()


class TestDatabaseVersionFunctions:
    """Tests for version query functions."""

    def test_get_latest_ncmec_version(self, app, mock_face_encoding):
        """Test getting latest NCMEC database version."""
        from central_hub.extensions import db
        from central_hub.models import NCMECRecord, NCMECStatus
        from central_hub.services.database_compiler import (
            compile_ncmec_database,
            get_latest_ncmec_version
        )

        with app.app_context():
            # Initially no versions
            result = get_latest_ncmec_version()
            assert result is None

            # Create records and compile
            record = NCMECRecord(
                case_id='LATEST-001',
                name='Test Person',
                face_encoding=mock_face_encoding,
                status=NCMECStatus.ACTIVE.value,
            )
            db.session.add(record)
            db.session.commit()

            with tempfile.TemporaryDirectory() as tmpdir:
                with patch('central_hub.services.database_compiler.get_config') as mock_config:
                    mock_cfg = MagicMock()
                    mock_cfg.DATABASES_PATH = Path(tmpdir)
                    mock_cfg.DATABASE_VERSIONS_TO_KEEP = 5
                    mock_cfg.FACE_ENCODING_BYTES = 512
                    mock_cfg.FACE_ENCODING_DIMENSIONS = 128
                    mock_config.return_value = mock_cfg

                    compile_ncmec_database()

                    # Now we should have a version
                    result = get_latest_ncmec_version()
                    assert result is not None
                    assert result['version'] == 1
                    assert 'file_hash' in result

    def test_verify_database_integrity(self, app, mock_face_encoding):
        """Test database file integrity verification."""
        from central_hub.extensions import db
        from central_hub.models import NCMECRecord, NCMECStatus
        from central_hub.services.database_compiler import (
            compile_ncmec_database,
            verify_database_integrity
        )

        with app.app_context():
            record = NCMECRecord(
                case_id='INTEGRITY-001',
                name='Test Person',
                face_encoding=mock_face_encoding,
                status=NCMECStatus.ACTIVE.value,
            )
            db.session.add(record)
            db.session.commit()

            with tempfile.TemporaryDirectory() as tmpdir:
                with patch('central_hub.services.database_compiler.get_config') as mock_config:
                    mock_cfg = MagicMock()
                    mock_cfg.DATABASES_PATH = Path(tmpdir)
                    mock_cfg.DATABASE_VERSIONS_TO_KEEP = 5
                    mock_cfg.FACE_ENCODING_BYTES = 512
                    mock_cfg.FACE_ENCODING_DIMENSIONS = 128
                    mock_config.return_value = mock_cfg

                    result = compile_ncmec_database()

                    # Verify integrity passes with correct hash
                    is_valid = verify_database_integrity(
                        result['file_path'],
                        result['file_hash']
                    )
                    assert is_valid is True

                    # Verify integrity fails with wrong hash
                    is_valid = verify_database_integrity(
                        result['file_path'],
                        'wrong_hash_value'
                    )
                    assert is_valid is False
