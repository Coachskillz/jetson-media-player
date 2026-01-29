"""
NCMEC Poster Sync Task

Daily scheduled task that:
1. Pulls missing children posters from the NCMEC Poster API
2. Downloads face photos from poster data
3. Extracts face encodings using face_recognition (dlib)
4. Creates/updates NCMECRecord entries in the database
5. Triggers FAISS index recompilation when new records are added

Schedule: Runs daily at 02:00 UTC via Celery Beat.
Can also be triggered manually via API: POST /api/v1/ncmec/sync
"""

import io
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from central_hub.extensions import celery, db
from central_hub.models.ncmec import NCMECRecord, NCMECStatus
from central_hub.services.face_encoder import (
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

# NCMEC Poster API settings
POSTER_API_BASE = "https://posterapi.ncmec.org"
ORG_CODE = os.environ.get("NCMEC_ORG_CODE", "NCMEC")
PAGE_SIZE = 100
MAX_PAGES = 500  # Safety limit: 50,000 records max per sync

# Photo download settings
PHOTO_DOWNLOAD_TIMEOUT = 30
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB


def _get_api_token() -> str:
    """
    Authenticate with NCMEC Poster API using OAuth2 client credentials.

    Returns:
        Bearer token string.

    Raises:
        RuntimeError: If credentials are missing or auth fails.
    """
    client_id = os.environ.get("NCMEC_POSTER_CLIENT_ID")
    client_secret = os.environ.get("NCMEC_POSTER_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "NCMEC_POSTER_CLIENT_ID and NCMEC_POSTER_CLIENT_SECRET must be set"
        )

    payload = {"clientId": client_id, "clientSecret": client_secret}
    headers = {
        "Content-Type": "application/json-patch+json",
        "Accept": "application/json",
    }

    response = requests.post(
        f"{POSTER_API_BASE}/Auth/Token",
        json=payload,
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["accessToken"]


def _fetch_posters(token: str, page: int = 1) -> Dict:
    """
    Fetch a page of posters from NCMEC API.

    Args:
        token: Bearer token
        page: Page number (1-indexed)

    Returns:
        API response dict with 'posters' list and pagination info.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "organizationCode": ORG_CODE,
        "pageNumber": page,
        "pageSize": PAGE_SIZE,
    }

    response = requests.post(
        f"{POSTER_API_BASE}/Poster/Search",
        headers=headers,
        json=body,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _download_photo(url: str) -> Optional[bytes]:
    """
    Download a face photo from a URL.

    Args:
        url: Photo URL from NCMEC poster data.

    Returns:
        Photo bytes, or None if download fails.
    """
    try:
        response = requests.get(url, timeout=PHOTO_DOWNLOAD_TIMEOUT)
        response.raise_for_status()

        if len(response.content) > MAX_PHOTO_SIZE:
            logger.warning("Photo too large (%d bytes), skipping", len(response.content))
            return None

        return response.content
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to download photo from %s: %s", url, e)
        return None


def _extract_poster_info(poster: Dict) -> Dict:
    """
    Extract relevant fields from a NCMEC poster record.

    Args:
        poster: Raw poster data from NCMEC API.

    Returns:
        Normalized dict with case_id, name, age, location, photo_urls.
    """
    # NCMEC API poster structure varies; handle gracefully
    case_id = poster.get("caseNumber") or poster.get("id") or ""
    first_name = poster.get("firstName", "")
    last_name = poster.get("lastName", "")
    name = f"{first_name} {last_name}".strip() or "Unknown"

    # Age
    age = poster.get("age") or poster.get("ageWhenMissing")

    # Missing date
    missing_since = poster.get("missingDate") or poster.get("dateMissing")

    # Location
    location_parts = []
    if poster.get("city"):
        location_parts.append(poster["city"])
    if poster.get("state"):
        location_parts.append(poster["state"])
    if poster.get("country"):
        location_parts.append(poster["country"])
    location = ", ".join(location_parts) or None

    # Photo URLs - look in various fields
    photo_urls = []
    if poster.get("photoUrl"):
        photo_urls.append(poster["photoUrl"])
    if poster.get("images"):
        for img in poster["images"]:
            url = img.get("url") or img.get("originalUrl")
            if url:
                photo_urls.append(url)
    if poster.get("posterUrl"):
        photo_urls.append(poster["posterUrl"])

    return {
        "case_id": str(case_id),
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "age_when_missing": age,
        "missing_since": missing_since,
        "last_known_location": location,
        "photo_urls": photo_urls,
    }


def _process_poster(poster_info: Dict) -> Optional[NCMECRecord]:
    """
    Process a single poster: download photo, extract encoding, create record.

    Args:
        poster_info: Normalized poster data from _extract_poster_info().

    Returns:
        NCMECRecord if successful, None if failed.
    """
    case_id = poster_info["case_id"]
    if not case_id:
        return None

    # Check if record already exists
    existing = NCMECRecord.query.filter_by(case_id=case_id).first()
    if existing and existing.face_encoding:
        # Already processed, skip
        return None

    # Try each photo URL until we get a face encoding
    for photo_url in poster_info["photo_urls"]:
        photo_bytes = _download_photo(photo_url)
        if not photo_bytes:
            continue

        try:
            encoding_bytes = extract_encoding_from_bytes(photo_bytes)

            if existing:
                # Update existing record with encoding
                existing.face_encoding = encoding_bytes
                existing.status = NCMECStatus.ACTIVE.value
                logger.info("Updated encoding for case %s", case_id)
                return existing
            else:
                # Create new record
                record = NCMECRecord(
                    case_id=case_id,
                    name=poster_info["name"],
                    age_when_missing=poster_info.get("age_when_missing"),
                    missing_since=_parse_date(poster_info.get("missing_since")),
                    last_known_location=poster_info.get("last_known_location"),
                    face_encoding=encoding_bytes,
                    status=NCMECStatus.ACTIVE.value,
                )
                logger.info("Created record for case %s (%s)", case_id, poster_info["name"])
                return record

        except NoFaceDetectedError:
            logger.debug("No face in photo for case %s, trying next photo", case_id)
            continue
        except (InvalidImageError, FaceEncodingError) as e:
            logger.warning("Encoding failed for case %s: %s", case_id, e)
            continue

    logger.warning("No usable face photo found for case %s", case_id)
    return None


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string from NCMEC data."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


@celery.task(
    base=LongRunningTask,
    bind=True,
    name="central_hub.tasks.sync_ncmec_posters.sync_ncmec_posters_task",
    queue=QUEUE_DEFAULT,
    acks_late=True,
    time_limit=7200,  # 2 hour hard limit
    soft_time_limit=6600,  # 1h50m soft limit
)
def sync_ncmec_posters_task(self, triggered_by: Optional[str] = None) -> Dict:
    """
    Celery task: Pull posters from NCMEC API, extract face encodings,
    store as NCMECRecord entries, and trigger recompilation.

    Args:
        triggered_by: Who triggered this sync (e.g., 'scheduler', 'api', 'admin')

    Returns:
        Task result with sync statistics.
    """
    started_at = datetime.now(timezone.utc)
    task_id = self.request.id

    logger.info(
        "Starting NCMEC poster sync task[%s], triggered_by=%s",
        task_id, triggered_by
    )

    stats = {
        "posters_fetched": 0,
        "records_created": 0,
        "records_updated": 0,
        "photos_processed": 0,
        "photos_failed": 0,
        "pages_fetched": 0,
    }

    try:
        # Authenticate
        token = _get_api_token()
        logger.info("NCMEC API authentication successful")

        # Paginate through all posters
        page = 1
        while page <= MAX_PAGES:
            try:
                data = _fetch_posters(token, page)
            except requests.exceptions.RequestException as e:
                logger.error("Failed to fetch page %d: %s", page, e)
                break

            posters = data.get("posters", [])
            if not posters:
                logger.info("No more posters at page %d, sync complete", page)
                break

            stats["pages_fetched"] += 1
            stats["posters_fetched"] += len(posters)

            for poster in posters:
                poster_info = _extract_poster_info(poster)

                record = _process_poster(poster_info)
                if record:
                    if record.id:
                        # Existing record updated
                        stats["records_updated"] += 1
                    else:
                        # New record
                        db.session.add(record)
                        stats["records_created"] += 1
                    stats["photos_processed"] += 1
                else:
                    stats["photos_failed"] += 1

            # Commit batch
            db.session.commit()
            logger.info(
                "Processed page %d: %d posters (%d new, %d updated)",
                page, len(posters),
                stats["records_created"], stats["records_updated"]
            )

            # Check if there are more pages
            total_records = data.get("totalRecords", 0)
            if stats["posters_fetched"] >= total_records:
                break

            page += 1

        # Trigger FAISS recompilation if new records were added
        if stats["records_created"] > 0 or stats["records_updated"] > 0:
            logger.info(
                "Triggering NCMEC database recompilation: "
                "%d new + %d updated records",
                stats["records_created"], stats["records_updated"]
            )
            from central_hub.tasks.compile_ncmec import compile_ncmec_task
            compile_ncmec_task.delay(triggered_by="ncmec_poster_sync")

        completed_at = datetime.now(timezone.utc)
        duration = (completed_at - started_at).total_seconds()

        logger.info(
            "NCMEC poster sync completed in %.1fs: "
            "fetched=%d, created=%d, updated=%d, failed=%d",
            duration,
            stats["posters_fetched"],
            stats["records_created"],
            stats["records_updated"],
            stats["photos_failed"],
        )

        return task_success_result(
            message="NCMEC poster sync completed",
            data={
                **stats,
                "triggered_by": triggered_by,
                "duration_seconds": duration,
                "completed_at": completed_at.isoformat(),
            },
        )

    except Exception as e:
        logger.exception("NCMEC poster sync failed: %s", e)
        db.session.rollback()
        return task_error_result(
            error=str(e),
            code="SYNC_FAILED",
            data={"triggered_by": triggered_by, "stats": stats},
        )


# Celery Beat schedule entry (add to celery config):
# 'sync-ncmec-posters-daily': {
#     'task': 'central_hub.tasks.sync_ncmec_posters.sync_ncmec_posters_task',
#     'schedule': crontab(hour=2, minute=0),
#     'args': ('scheduler',),
# }

__all__ = ["sync_ncmec_posters_task"]
