"""
Database Compiler Service

Compiles face encodings from NCMEC records and Loyalty members into
versioned FAISS indexes for efficient facial recognition on edge devices.
Each compilation produces:
- A FAISS index file (.faiss) for vector similarity search
- A metadata JSON file with record details for result lookup
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np

from central_hub.config import get_config
from central_hub.extensions import db
from central_hub.models.ncmec import NCMECRecord, NCMECDatabaseVersion, NCMECStatus
from central_hub.models.loyalty import LoyaltyMember, LoyaltyDatabaseVersion

logger = logging.getLogger(__name__)


class DatabaseCompilationError(Exception):
    """Base exception for database compilation errors."""
    pass


class EmptyDatabaseError(DatabaseCompilationError):
    """Raised when attempting to compile an empty database."""
    pass


class InvalidEncodingError(DatabaseCompilationError):
    """Raised when a record has invalid face encoding data."""
    pass


def _calculate_file_hash(file_path: str) -> str:
    """
    Calculate SHA256 hash of a file for integrity verification.

    Args:
        file_path: Path to the file.

    Returns:
        Hex string of SHA256 hash (64 characters).
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        # Read in chunks to handle large files
        for chunk in iter(lambda: f.read(8192), b''):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def _encoding_to_array(encoding_bytes: bytes) -> np.ndarray:
    """
    Convert stored encoding bytes to numpy array for FAISS.

    Args:
        encoding_bytes: Face encoding as bytes (512 bytes).

    Returns:
        Numpy array of shape (128,) with dtype float32.

    Raises:
        InvalidEncodingError: If encoding bytes are invalid.
    """
    config = get_config()

    if len(encoding_bytes) != config.FACE_ENCODING_BYTES:
        raise InvalidEncodingError(
            f"Invalid encoding size: {len(encoding_bytes)} bytes, "
            f"expected {config.FACE_ENCODING_BYTES}"
        )

    array = np.frombuffer(encoding_bytes, dtype=np.float32)

    if array.shape[0] != config.FACE_ENCODING_DIMENSIONS:
        raise InvalidEncodingError(
            f"Invalid encoding dimensions: {array.shape[0]}, "
            f"expected {config.FACE_ENCODING_DIMENSIONS}"
        )

    return array


def _get_next_version(model_class, network_id: Optional[uuid.UUID] = None) -> int:
    """
    Get the next version number for a database compilation.

    Args:
        model_class: SQLAlchemy model class (NCMECDatabaseVersion or LoyaltyDatabaseVersion).
        network_id: Network ID for loyalty databases (None for NCMEC).

    Returns:
        Next version number (1 for first compilation).
    """
    query = db.session.query(db.func.max(model_class.version))

    if network_id is not None:
        query = query.filter(model_class.network_id == network_id)

    max_version = query.scalar()
    return (max_version or 0) + 1


def _cleanup_old_versions(
    model_class,
    databases_path: Path,
    keep_count: int,
    network_id: Optional[uuid.UUID] = None
) -> int:
    """
    Remove old database versions beyond the keep count.

    Args:
        model_class: SQLAlchemy model class.
        databases_path: Base path for database files.
        keep_count: Number of versions to keep.
        network_id: Network ID for loyalty databases (None for NCMEC).

    Returns:
        Number of versions deleted.
    """
    query = model_class.query

    if network_id is not None:
        query = query.filter(model_class.network_id == network_id)

    # Get all versions ordered by version number descending
    versions = query.order_by(model_class.version.desc()).all()

    if len(versions) <= keep_count:
        return 0

    # Delete versions beyond keep_count
    versions_to_delete = versions[keep_count:]
    deleted_count = 0

    for version in versions_to_delete:
        try:
            # Delete the FAISS file
            faiss_path = Path(version.file_path)
            if faiss_path.exists():
                faiss_path.unlink()

            # Delete the metadata file
            metadata_path = faiss_path.with_suffix('.json')
            if metadata_path.exists():
                metadata_path.unlink()

            # Delete the database record
            db.session.delete(version)
            deleted_count += 1

            logger.info(
                f"Deleted old database version {version.version} "
                f"(file: {version.file_path})"
            )
        except Exception as e:
            logger.warning(
                f"Failed to delete version {version.version}: {e}"
            )

    return deleted_count


def compile_ncmec_database() -> Dict:
    """
    Compile all active NCMEC records into a versioned FAISS index.

    Creates a new FAISS index file and accompanying metadata JSON
    containing all active NCMEC records. The index enables efficient
    face similarity search on edge devices.

    Returns:
        Dictionary containing compilation results:
        - version: Version number of the compilation
        - record_count: Number of records in the database
        - file_hash: SHA256 hash of the FAISS file
        - file_path: Path to the compiled FAISS file
        - metadata_path: Path to the metadata JSON file

    Raises:
        EmptyDatabaseError: If no active NCMEC records exist.
        DatabaseCompilationError: If compilation fails.
    """
    config = get_config()

    # Query active NCMEC records
    records = NCMECRecord.query.filter(
        NCMECRecord.status == NCMECStatus.ACTIVE.value
    ).order_by(NCMECRecord.case_id).all()

    if not records:
        logger.error("Cannot compile empty NCMEC database")
        raise EmptyDatabaseError(
            "No active NCMEC records to compile. Add records before compilation."
        )

    logger.info(f"Compiling NCMEC database with {len(records)} active records")

    # Get next version number
    version = _get_next_version(NCMECDatabaseVersion)

    # Prepare output paths
    databases_path = config.DATABASES_PATH / 'ncmec'
    databases_path.mkdir(parents=True, exist_ok=True)

    faiss_filename = f"ncmec_v{version}.faiss"
    metadata_filename = f"ncmec_v{version}.json"
    faiss_path = databases_path / faiss_filename
    metadata_path = databases_path / metadata_filename

    try:
        # Build numpy array of encodings
        encodings = []
        metadata = []

        for idx, record in enumerate(records):
            try:
                encoding_array = _encoding_to_array(record.face_encoding)
                encodings.append(encoding_array)

                # Store metadata keyed by FAISS index position
                metadata.append({
                    'idx': idx,
                    'id': str(record.id),
                    'case_id': record.case_id,
                    'name': record.name,
                    'age_when_missing': record.age_when_missing,
                    'missing_since': record.missing_since.isoformat() if record.missing_since else None,
                    'last_known_location': record.last_known_location,
                })
            except InvalidEncodingError as e:
                logger.warning(
                    f"Skipping record {record.case_id} with invalid encoding: {e}"
                )
                continue

        if not encodings:
            raise EmptyDatabaseError(
                "All NCMEC records have invalid encodings. No valid records to compile."
            )

        # Stack encodings into 2D array for FAISS
        encodings_array = np.vstack(encodings).astype(np.float32)

        # Create FAISS index (IndexFlatL2 for exact L2 distance search)
        index = faiss.IndexFlatL2(config.FACE_ENCODING_DIMENSIONS)
        index.add(encodings_array)

        # Write FAISS index to file
        faiss.write_index(index, str(faiss_path))
        logger.info(f"FAISS index written to {faiss_path}")

        # Calculate file hash for integrity verification
        file_hash = _calculate_file_hash(str(faiss_path))

        # Write metadata JSON
        metadata_doc = {
            'version': version,
            'database_type': 'ncmec',
            'record_count': len(encodings),
            'file_hash': file_hash,
            'compiled_at': datetime.now(timezone.utc).isoformat(),
            'records': metadata,
        }
        with open(metadata_path, 'w') as f:
            json.dump(metadata_doc, f, indent=2)
        logger.info(f"Metadata written to {metadata_path}")

        # Create database version record
        db_version = NCMECDatabaseVersion(
            version=version,
            record_count=len(encodings),
            file_hash=file_hash,
            file_path=str(faiss_path),
        )
        db.session.add(db_version)
        db.session.commit()

        # Clean up old versions
        deleted = _cleanup_old_versions(
            NCMECDatabaseVersion,
            databases_path,
            config.DATABASE_VERSIONS_TO_KEEP
        )
        if deleted > 0:
            db.session.commit()
            logger.info(f"Cleaned up {deleted} old NCMEC database versions")

        logger.info(
            f"NCMEC database compilation complete: "
            f"version={version}, records={len(encodings)}"
        )

        return {
            'version': version,
            'record_count': len(encodings),
            'file_hash': file_hash,
            'file_path': str(faiss_path),
            'metadata_path': str(metadata_path),
        }

    except EmptyDatabaseError:
        raise
    except Exception as e:
        logger.error(f"NCMEC database compilation failed: {e}")
        db.session.rollback()

        # Clean up partial files
        if faiss_path.exists():
            faiss_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()

        raise DatabaseCompilationError(f"Compilation failed: {e}")


def compile_loyalty_database(network_id: uuid.UUID) -> Dict:
    """
    Compile loyalty members for a specific network into a versioned FAISS index.

    Creates a network-specific FAISS index file and accompanying metadata
    JSON for personalized content delivery via face recognition.

    Args:
        network_id: UUID of the network to compile.

    Returns:
        Dictionary containing compilation results:
        - network_id: Network ID for this database
        - version: Version number of the compilation
        - record_count: Number of members in the database
        - file_hash: SHA256 hash of the FAISS file
        - file_path: Path to the compiled FAISS file
        - metadata_path: Path to the metadata JSON file

    Raises:
        EmptyDatabaseError: If no loyalty members exist for the network.
        DatabaseCompilationError: If compilation fails.
    """
    config = get_config()

    # Validate network_id
    if not network_id:
        raise DatabaseCompilationError("Network ID is required for loyalty compilation")

    # Query loyalty members for this network
    members = LoyaltyMember.query.filter(
        LoyaltyMember.network_id == network_id
    ).order_by(LoyaltyMember.member_code).all()

    if not members:
        logger.error(f"No loyalty members found for network {network_id}")
        raise EmptyDatabaseError(
            f"No loyalty members enrolled in network {network_id}. "
            "Enroll members before compilation."
        )

    logger.info(
        f"Compiling loyalty database for network {network_id} "
        f"with {len(members)} members"
    )

    # Get next version number for this network
    version = _get_next_version(LoyaltyDatabaseVersion, network_id)

    # Prepare output paths (network-scoped directory)
    network_id_str = str(network_id)
    databases_path = config.DATABASES_PATH / 'loyalty' / network_id_str
    databases_path.mkdir(parents=True, exist_ok=True)

    faiss_filename = f"loyalty_{network_id_str}_v{version}.faiss"
    metadata_filename = f"loyalty_{network_id_str}_v{version}.json"
    faiss_path = databases_path / faiss_filename
    metadata_path = databases_path / metadata_filename

    try:
        # Build numpy array of encodings
        encodings = []
        metadata = []

        for idx, member in enumerate(members):
            try:
                encoding_array = _encoding_to_array(member.face_encoding)
                encodings.append(encoding_array)

                # Store metadata keyed by FAISS index position
                metadata.append({
                    'idx': idx,
                    'id': str(member.id),
                    'member_code': member.member_code,
                    'name': member.name,
                    'assigned_playlist_id': member.assigned_playlist_id,
                })
            except InvalidEncodingError as e:
                logger.warning(
                    f"Skipping member {member.member_code} with invalid encoding: {e}"
                )
                continue

        if not encodings:
            raise EmptyDatabaseError(
                f"All loyalty members in network {network_id} have invalid encodings. "
                "No valid records to compile."
            )

        # Stack encodings into 2D array for FAISS
        encodings_array = np.vstack(encodings).astype(np.float32)

        # Create FAISS index (IndexFlatL2 for exact L2 distance search)
        index = faiss.IndexFlatL2(config.FACE_ENCODING_DIMENSIONS)
        index.add(encodings_array)

        # Write FAISS index to file
        faiss.write_index(index, str(faiss_path))
        logger.info(f"FAISS index written to {faiss_path}")

        # Calculate file hash for integrity verification
        file_hash = _calculate_file_hash(str(faiss_path))

        # Write metadata JSON
        metadata_doc = {
            'version': version,
            'database_type': 'loyalty',
            'network_id': network_id_str,
            'record_count': len(encodings),
            'file_hash': file_hash,
            'compiled_at': datetime.now(timezone.utc).isoformat(),
            'members': metadata,
        }
        with open(metadata_path, 'w') as f:
            json.dump(metadata_doc, f, indent=2)
        logger.info(f"Metadata written to {metadata_path}")

        # Create database version record
        db_version = LoyaltyDatabaseVersion(
            network_id=network_id,
            version=version,
            record_count=len(encodings),
            file_hash=file_hash,
            file_path=str(faiss_path),
        )
        db.session.add(db_version)
        db.session.commit()

        # Clean up old versions for this network
        deleted = _cleanup_old_versions(
            LoyaltyDatabaseVersion,
            databases_path,
            config.DATABASE_VERSIONS_TO_KEEP,
            network_id=network_id
        )
        if deleted > 0:
            db.session.commit()
            logger.info(
                f"Cleaned up {deleted} old loyalty database versions "
                f"for network {network_id}"
            )

        logger.info(
            f"Loyalty database compilation complete for network {network_id}: "
            f"version={version}, members={len(encodings)}"
        )

        return {
            'network_id': network_id_str,
            'version': version,
            'record_count': len(encodings),
            'file_hash': file_hash,
            'file_path': str(faiss_path),
            'metadata_path': str(metadata_path),
        }

    except EmptyDatabaseError:
        raise
    except Exception as e:
        logger.error(
            f"Loyalty database compilation failed for network {network_id}: {e}"
        )
        db.session.rollback()

        # Clean up partial files
        if faiss_path.exists():
            faiss_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()

        raise DatabaseCompilationError(f"Compilation failed: {e}")


def get_latest_ncmec_version() -> Optional[Dict]:
    """
    Get the latest NCMEC database version info.

    Returns:
        Dictionary with version info or None if no versions exist.
    """
    version = NCMECDatabaseVersion.query.order_by(
        NCMECDatabaseVersion.version.desc()
    ).first()

    if version:
        return version.to_dict()
    return None


def get_latest_loyalty_version(network_id: uuid.UUID) -> Optional[Dict]:
    """
    Get the latest loyalty database version for a network.

    Args:
        network_id: UUID of the network.

    Returns:
        Dictionary with version info or None if no versions exist.
    """
    version = LoyaltyDatabaseVersion.query.filter(
        LoyaltyDatabaseVersion.network_id == network_id
    ).order_by(
        LoyaltyDatabaseVersion.version.desc()
    ).first()

    if version:
        return version.to_dict()
    return None


def verify_database_integrity(file_path: str, expected_hash: str) -> bool:
    """
    Verify the integrity of a compiled database file.

    Args:
        file_path: Path to the FAISS file.
        expected_hash: Expected SHA256 hash.

    Returns:
        True if hash matches, False otherwise.
    """
    if not Path(file_path).exists():
        logger.warning(f"Database file not found: {file_path}")
        return False

    actual_hash = _calculate_file_hash(file_path)
    is_valid = actual_hash == expected_hash

    if not is_valid:
        logger.warning(
            f"Database integrity check failed for {file_path}: "
            f"expected {expected_hash}, got {actual_hash}"
        )

    return is_valid
