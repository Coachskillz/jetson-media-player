"""
Loyalty Member Bulk Import Task

Processes CSV or JSON bulk imports of loyalty members:
1. Parse uploaded file (CSV with member_code, name, photo_url columns)
2. Download face photos from URLs
3. Extract face encodings
4. Create LoyaltyMember records
5. Trigger FAISS recompilation when complete

Triggered via API: POST /api/v1/networks/{id}/loyalty/import
"""

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from central_hub.extensions import celery, db
from central_hub.config import get_config
from central_hub.models.loyalty import LoyaltyMember
from central_hub.services.face_encoder import (
    extract_encoding,
    extract_encoding_from_bytes,
    NoFaceDetectedError,
    InvalidImageError,
    FaceEncodingError,
)
from central_hub.tasks import (
    LongRunningTask,
    task_success_result,
    task_error_result,
    QUEUE_DEFAULT,
)

logger = logging.getLogger(__name__)

PHOTO_DOWNLOAD_TIMEOUT = 30


def _download_member_photo(url: str) -> Optional[bytes]:
    """Download a member photo from a URL."""
    try:
        response = requests.get(url, timeout=PHOTO_DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to download photo from %s: %s", url, e)
        return None


def _save_photo_bytes(photo_bytes: bytes, member_id: uuid.UUID, network_id: uuid.UUID) -> Optional[str]:
    """Save photo bytes to disk and return the relative path."""
    config = get_config()
    uploads_dir = config.UPLOADS_PATH / "loyalty" / str(network_id)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    file_path = uploads_dir / f"{member_id}.jpg"
    with open(file_path, "wb") as f:
        f.write(photo_bytes)

    return f"loyalty/{network_id}/{member_id}.jpg"


def _process_csv_row(
    row: Dict,
    network_id: uuid.UUID,
    existing_codes: set,
) -> Optional[Dict]:
    """
    Process a single CSV row into member data.

    Expected CSV columns:
    - member_code (required)
    - name (required)
    - photo_url (required) - URL to download face photo
    - email (optional)
    - phone (optional)
    - assigned_playlist_id (optional)

    Returns:
        Dict with member data and encoding, or None if failed.
    """
    member_code = row.get("member_code", "").strip()
    name = row.get("name", "").strip()
    photo_url = row.get("photo_url", "").strip()

    if not member_code or not name:
        return None

    if not photo_url:
        logger.warning("No photo_url for member %s, skipping", member_code)
        return None

    # Skip duplicates
    if member_code in existing_codes:
        logger.debug("Member %s already exists, skipping", member_code)
        return None

    # Download photo
    photo_bytes = _download_member_photo(photo_url)
    if not photo_bytes:
        return None

    # Extract face encoding
    try:
        encoding = extract_encoding_from_bytes(photo_bytes)
    except (NoFaceDetectedError, InvalidImageError, FaceEncodingError) as e:
        logger.warning("Encoding failed for member %s: %s", member_code, e)
        return None

    member_id = uuid.uuid4()
    photo_path = _save_photo_bytes(photo_bytes, member_id, network_id)

    return {
        "id": member_id,
        "member_code": member_code,
        "name": name,
        "email": row.get("email", "").strip() or None,
        "phone": row.get("phone", "").strip() or None,
        "assigned_playlist_id": row.get("assigned_playlist_id") or None,
        "encoding": encoding,
        "photo_path": photo_path,
    }


@celery.task(
    base=LongRunningTask,
    bind=True,
    name="central_hub.tasks.import_loyalty_members.import_loyalty_csv_task",
    queue=QUEUE_DEFAULT,
    acks_late=True,
    time_limit=3600,  # 1 hour
    soft_time_limit=3300,
)
def import_loyalty_csv_task(
    self,
    network_id: str,
    csv_file_path: str,
    triggered_by: Optional[str] = None,
) -> Dict:
    """
    Celery task: Import loyalty members from a CSV file.

    The CSV file should already be saved to disk by the API endpoint.

    Args:
        network_id: UUID string of the network
        csv_file_path: Path to the uploaded CSV file
        triggered_by: Who triggered the import

    Returns:
        Task result with import statistics.
    """
    started_at = datetime.now(timezone.utc)
    task_id = self.request.id
    network_uuid = uuid.UUID(network_id)

    logger.info(
        "Starting loyalty CSV import task[%s] for network %s",
        task_id, network_id
    )

    stats = {
        "rows_processed": 0,
        "members_created": 0,
        "members_skipped": 0,
        "photos_failed": 0,
        "encoding_failed": 0,
    }

    try:
        # Get existing member codes for this network
        existing_members = LoyaltyMember.query.filter_by(
            network_id=network_uuid
        ).with_entities(LoyaltyMember.member_code).all()
        existing_codes = {m.member_code for m in existing_members}

        # Parse CSV
        csv_path = Path(csv_file_path)
        if not csv_path.exists():
            return task_error_result(
                error=f"CSV file not found: {csv_file_path}",
                code="FILE_NOT_FOUND",
            )

        with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            batch = []

            for row in reader:
                stats["rows_processed"] += 1

                result = _process_csv_row(row, network_uuid, existing_codes)
                if result:
                    member = LoyaltyMember(
                        id=result["id"],
                        network_id=network_uuid,
                        member_code=result["member_code"],
                        name=result["name"],
                        email=result["email"],
                        phone=result["phone"],
                        face_encoding=result["encoding"],
                        photo_path=result["photo_path"],
                        assigned_playlist_id=result.get("assigned_playlist_id"),
                    )
                    batch.append(member)
                    existing_codes.add(result["member_code"])
                    stats["members_created"] += 1

                    # Commit in batches of 50
                    if len(batch) >= 50:
                        db.session.add_all(batch)
                        db.session.commit()
                        logger.info(
                            "Committed batch: %d members (%d total)",
                            len(batch), stats["members_created"]
                        )
                        batch = []
                else:
                    stats["members_skipped"] += 1

            # Commit remaining
            if batch:
                db.session.add_all(batch)
                db.session.commit()

        # Trigger FAISS recompilation
        if stats["members_created"] > 0:
            logger.info(
                "Triggering loyalty database recompilation for network %s",
                network_id
            )
            from central_hub.tasks.compile_loyalty import compile_loyalty_task
            compile_loyalty_task.delay(
                network_id=network_id,
                triggered_by="loyalty_csv_import"
            )

        # Clean up CSV file
        csv_path.unlink(missing_ok=True)

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        logger.info(
            "Loyalty CSV import completed in %.1fs: "
            "processed=%d, created=%d, skipped=%d",
            duration,
            stats["rows_processed"],
            stats["members_created"],
            stats["members_skipped"],
        )

        return task_success_result(
            message="Loyalty CSV import completed",
            data={
                **stats,
                "network_id": network_id,
                "triggered_by": triggered_by,
                "duration_seconds": duration,
                "completed_at": completed_at.isoformat(),
            },
        )

    except Exception as e:
        logger.exception("Loyalty CSV import failed: %s", e)
        db.session.rollback()
        return task_error_result(
            error=str(e),
            code="IMPORT_FAILED",
            data={"triggered_by": triggered_by, "stats": stats},
        )


@celery.task(
    base=LongRunningTask,
    bind=True,
    name="central_hub.tasks.import_loyalty_members.import_loyalty_json_task",
    queue=QUEUE_DEFAULT,
    acks_late=True,
    time_limit=3600,
    soft_time_limit=3300,
)
def import_loyalty_json_task(
    self,
    network_id: str,
    json_file_path: str,
    triggered_by: Optional[str] = None,
) -> Dict:
    """
    Celery task: Import loyalty members from a JSON file.

    Expected JSON format:
    {
        "members": [
            {
                "member_code": "MEM001",
                "name": "John Doe",
                "photo_url": "https://...",
                "email": "john@example.com",  // optional
                "phone": "555-0100",           // optional
                "assigned_playlist_id": 1      // optional
            }
        ]
    }
    """
    started_at = datetime.now(timezone.utc)
    task_id = self.request.id
    network_uuid = uuid.UUID(network_id)

    logger.info(
        "Starting loyalty JSON import task[%s] for network %s",
        task_id, network_id
    )

    stats = {
        "rows_processed": 0,
        "members_created": 0,
        "members_skipped": 0,
    }

    try:
        json_path = Path(json_file_path)
        if not json_path.exists():
            return task_error_result(
                error=f"JSON file not found: {json_file_path}",
                code="FILE_NOT_FOUND",
            )

        with open(json_path, "r") as f:
            data = json.load(f)

        members_data = data.get("members", [])
        if not members_data:
            return task_error_result(
                error="No members found in JSON file",
                code="EMPTY_DATA",
            )

        # Get existing codes
        existing_members = LoyaltyMember.query.filter_by(
            network_id=network_uuid
        ).with_entities(LoyaltyMember.member_code).all()
        existing_codes = {m.member_code for m in existing_members}

        batch = []
        for row in members_data:
            stats["rows_processed"] += 1

            result = _process_csv_row(row, network_uuid, existing_codes)
            if result:
                member = LoyaltyMember(
                    id=result["id"],
                    network_id=network_uuid,
                    member_code=result["member_code"],
                    name=result["name"],
                    email=result["email"],
                    phone=result["phone"],
                    face_encoding=result["encoding"],
                    photo_path=result["photo_path"],
                    assigned_playlist_id=result.get("assigned_playlist_id"),
                )
                batch.append(member)
                existing_codes.add(result["member_code"])
                stats["members_created"] += 1

                if len(batch) >= 50:
                    db.session.add_all(batch)
                    db.session.commit()
                    batch = []
            else:
                stats["members_skipped"] += 1

        if batch:
            db.session.add_all(batch)
            db.session.commit()

        # Trigger recompilation
        if stats["members_created"] > 0:
            from central_hub.tasks.compile_loyalty import compile_loyalty_task
            compile_loyalty_task.delay(
                network_id=network_id,
                triggered_by="loyalty_json_import"
            )

        json_path.unlink(missing_ok=True)

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        logger.info(
            "Loyalty JSON import completed in %.1fs: created=%d, skipped=%d",
            duration, stats["members_created"], stats["members_skipped"]
        )

        return task_success_result(
            message="Loyalty JSON import completed",
            data={
                **stats,
                "network_id": network_id,
                "triggered_by": triggered_by,
                "duration_seconds": duration,
            },
        )

    except Exception as e:
        logger.exception("Loyalty JSON import failed: %s", e)
        db.session.rollback()
        return task_error_result(
            error=str(e),
            code="IMPORT_FAILED",
            data={"triggered_by": triggered_by, "stats": stats},
        )


__all__ = ["import_loyalty_csv_task", "import_loyalty_json_task"]
