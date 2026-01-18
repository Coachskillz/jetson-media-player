"""
CMS Catalog Integration Routes

Blueprint for integrating CMS with the Content Catalog service:
- GET /catalog/assets: List approved/published assets from catalog
- GET /catalog/assets/<uuid>: Get specific asset details
- POST /catalog/assets/<uuid>/add-to-playlist: Add catalog asset to CMS playlist
- GET /catalog/stats: Get catalog statistics

These endpoints allow the CMS to access approved content from the
Content Catalog Partner Portal for use in playlist building.
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timezone
from sqlalchemy import or_, func

# CMS imports
from cms.models import db as cms_db, Content, Playlist, PlaylistContent

# Content Catalog imports (cross-module)
try:
    from content_catalog.models import ContentAsset
    from content_catalog.services.visibility_service import VisibilityService
    CATALOG_AVAILABLE = True
except ImportError:
    CATALOG_AVAILABLE = False


# Create catalog integration blueprint
catalog_bp = Blueprint('catalog', __name__)


def _catalog_unavailable_response():
    """Return error response when catalog is not available."""
    return jsonify({
        'error': 'Content Catalog service is not available',
        'message': 'The Content Catalog module is not installed or configured'
    }), 503


@catalog_bp.route('/assets', methods=['GET'])
@login_required
def list_catalog_assets():
    """
    List approved/published assets from the Content Catalog.

    Query Parameters:
        status: Filter by status ('approved', 'published', or 'all')
        format: Filter by format (e.g., 'mp4', 'jpg')
        search: Search term for title/description
        page: Page number (default: 1)
        per_page: Items per page (default: 20, max: 100)

    Returns:
        200: List of assets
            {
                "assets": [{ asset data }],
                "total": 100,
                "page": 1,
                "per_page": 20,
                "total_pages": 5
            }
        503: Content Catalog not available
    """
    if not CATALOG_AVAILABLE:
        return _catalog_unavailable_response()

    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    format_filter = request.args.get('format', '')
    search_query = request.args.get('search', '').strip()

    # Get pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    try:
        per_page = int(request.args.get('per_page', 20))
        if per_page < 1:
            per_page = 20
        if per_page > 100:
            per_page = 100
    except ValueError:
        per_page = 20

    # Build query for published/approved assets
    query = ContentAsset.query

    # Apply status filter
    if status_filter == 'approved':
        query = query.filter(ContentAsset.status == ContentAsset.STATUS_APPROVED)
    elif status_filter == 'published':
        query = query.filter(ContentAsset.status == ContentAsset.STATUS_PUBLISHED)
    else:
        # Default: both approved and published
        query = query.filter(
            ContentAsset.status.in_([
                ContentAsset.STATUS_APPROVED,
                ContentAsset.STATUS_PUBLISHED
            ])
        )

    # Apply format filter
    if format_filter:
        query = query.filter(ContentAsset.format == format_filter.lower())

    # Apply search filter
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                ContentAsset.title.ilike(search_pattern),
                ContentAsset.description.ilike(search_pattern)
            )
        )

    # Get total count
    total = query.count()
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Apply ordering and pagination
    assets = query.order_by(
        ContentAsset.created_at.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()

    # Serialize assets
    assets_data = []
    for asset in assets:
        assets_data.append({
            'uuid': asset.uuid,
            'title': asset.title,
            'description': asset.description,
            'filename': asset.filename,
            'format': asset.format,
            'file_size': asset.file_size,
            'duration': asset.duration,
            'resolution': asset.resolution,
            'status': asset.status,
            'category': asset.category,
            'tags': asset.tags,
            'created_at': asset.created_at.isoformat() if asset.created_at else None,
            'published_at': asset.published_at.isoformat() if asset.published_at else None,
            'organization_name': asset.organization.name if asset.organization else None
        })

    return jsonify({
        'assets': assets_data,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    }), 200


@catalog_bp.route('/assets/<asset_uuid>', methods=['GET'])
@login_required
def get_catalog_asset(asset_uuid):
    """
    Get details for a specific catalog asset.

    Args:
        asset_uuid: Content asset UUID

    Returns:
        200: Asset details
            {
                "asset": { full asset data with download_url }
            }
        404: Asset not found
        503: Content Catalog not available
    """
    if not CATALOG_AVAILABLE:
        return _catalog_unavailable_response()

    # Look up asset by UUID
    asset = ContentAsset.get_by_uuid(asset_uuid)

    if not asset:
        return jsonify({'error': 'Asset not found'}), 404

    # Only allow access to approved/published assets
    if asset.status not in [ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED]:
        return jsonify({'error': 'Asset is not available for use'}), 403

    # Build response with full details
    asset_data = asset.to_dict()

    # Add organization info
    if asset.organization:
        asset_data['organization'] = {
            'id': asset.organization.id,
            'name': asset.organization.name
        }

    # Add uploader info
    if asset.uploader:
        asset_data['uploaded_by_name'] = asset.uploader.name

    return jsonify({'asset': asset_data}), 200


@catalog_bp.route('/assets/<asset_uuid>/add-to-playlist', methods=['POST'])
@login_required
def add_catalog_asset_to_playlist(asset_uuid):
    """
    Add a catalog asset to a CMS playlist.

    This creates a reference from the CMS playlist to the catalog asset,
    syncing necessary metadata to the CMS Content table.

    Args:
        asset_uuid: Content asset UUID

    Request Body:
        {
            "playlist_id": "playlist UUID" (required),
            "position": 0 (optional, adds to end if not specified),
            "duration_override": 30 (optional, override duration in seconds)
        }

    Returns:
        200: Asset added to playlist
            {
                "message": "Asset added to playlist",
                "content": { CMS content data },
                "playlist_content": { playlist content link data }
            }
        400: Invalid request
        403: Asset not available
        404: Asset or playlist not found
        503: Content Catalog not available
    """
    if not CATALOG_AVAILABLE:
        return _catalog_unavailable_response()

    # Look up catalog asset
    catalog_asset = ContentAsset.get_by_uuid(asset_uuid)

    if not catalog_asset:
        return jsonify({'error': 'Catalog asset not found'}), 404

    # Only allow approved/published assets
    if catalog_asset.status not in [ContentAsset.STATUS_APPROVED, ContentAsset.STATUS_PUBLISHED]:
        return jsonify({'error': 'Asset is not available for use'}), 403

    # Parse request body
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    playlist_id = data.get('playlist_id')
    if not playlist_id:
        return jsonify({'error': 'playlist_id is required'}), 400

    # Look up playlist
    playlist = Playlist.query.filter_by(id=playlist_id).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    position = data.get('position')
    duration_override = data.get('duration_override')

    # Check if content already exists in CMS for this catalog asset
    cms_content = Content.query.filter_by(
        catalog_asset_uuid=asset_uuid
    ).first()

    if not cms_content:
        # Create new CMS content entry linked to catalog asset
        cms_content = Content(
            name=catalog_asset.title,
            description=catalog_asset.description,
            file_path=catalog_asset.file_path,
            file_url=catalog_asset.file_url,
            file_type=catalog_asset.format,
            file_size=catalog_asset.file_size,
            duration=catalog_asset.duration,
            resolution=catalog_asset.resolution,
            thumbnail_path=catalog_asset.thumbnail_path,
            catalog_asset_uuid=asset_uuid,
            source='catalog',
            created_at=datetime.now(timezone.utc)
        )
        cms_db.session.add(cms_content)
        cms_db.session.flush()

    # Determine position for new content
    if position is None:
        # Get current max position in playlist
        max_position = cms_db.session.query(
            func.max(PlaylistContent.position)
        ).filter_by(playlist_id=playlist_id).scalar()
        position = (max_position or 0) + 1

    # Create playlist-content link
    playlist_content = PlaylistContent(
        playlist_id=playlist_id,
        content_id=cms_content.id,
        position=position,
        duration_override=duration_override,
        added_at=datetime.now(timezone.utc)
    )
    cms_db.session.add(playlist_content)

    try:
        cms_db.session.commit()
    except Exception as e:
        cms_db.session.rollback()
        return jsonify({'error': f'Failed to add asset to playlist: {str(e)}'}), 500

    return jsonify({
        'message': 'Asset added to playlist',
        'content': cms_content.to_dict() if hasattr(cms_content, 'to_dict') else {'id': cms_content.id},
        'playlist_content': {
            'playlist_id': playlist_id,
            'content_id': cms_content.id,
            'position': position,
            'duration_override': duration_override
        }
    }), 200


@catalog_bp.route('/stats', methods=['GET'])
@login_required
def get_catalog_stats():
    """
    Get statistics from the Content Catalog.

    Returns:
        200: Catalog statistics
            {
                "total_assets": 100,
                "approved_assets": 80,
                "published_assets": 50,
                "pending_review": 10,
                "by_format": {
                    "mp4": 40,
                    "jpg": 30,
                    ...
                }
            }
        503: Content Catalog not available
    """
    if not CATALOG_AVAILABLE:
        return _catalog_unavailable_response()

    # Get counts by status
    stats = {
        'total_assets': ContentAsset.query.count(),
        'approved_assets': ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_APPROVED
        ).count(),
        'published_assets': ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_PUBLISHED
        ).count(),
        'pending_review': ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_PENDING_REVIEW
        ).count(),
        'draft_assets': ContentAsset.query.filter_by(
            status=ContentAsset.STATUS_DRAFT
        ).count()
    }

    # Get counts by format
    format_counts = cms_db.session.query(
        ContentAsset.format,
        func.count(ContentAsset.id)
    ).group_by(ContentAsset.format).all()

    stats['by_format'] = {
        fmt: count for fmt, count in format_counts if fmt
    }

    return jsonify(stats), 200


@catalog_bp.route('/sync-check', methods=['GET'])
@login_required
def check_catalog_sync():
    """
    Check sync status between CMS content and catalog assets.

    Returns a list of CMS content items that reference catalog assets
    with their current sync status.

    Returns:
        200: Sync status
            {
                "synced_items": [
                    {
                        "cms_content_id": "...",
                        "catalog_uuid": "...",
                        "catalog_status": "published",
                        "needs_update": false
                    }
                ],
                "orphaned_items": [...],
                "total_synced": 50,
                "total_orphaned": 2
            }
        503: Content Catalog not available
    """
    if not CATALOG_AVAILABLE:
        return _catalog_unavailable_response()

    # Get all CMS content that references catalog assets
    catalog_linked = Content.query.filter(
        Content.catalog_asset_uuid.isnot(None)
    ).all()

    synced_items = []
    orphaned_items = []

    for cms_content in catalog_linked:
        catalog_asset = ContentAsset.get_by_uuid(cms_content.catalog_asset_uuid)

        if catalog_asset:
            # Check if update is needed (compare timestamps or hashes)
            needs_update = False
            if hasattr(catalog_asset, 'updated_at') and hasattr(cms_content, 'updated_at'):
                if catalog_asset.updated_at and cms_content.updated_at:
                    needs_update = catalog_asset.updated_at > cms_content.updated_at

            synced_items.append({
                'cms_content_id': cms_content.id,
                'cms_content_name': cms_content.name,
                'catalog_uuid': cms_content.catalog_asset_uuid,
                'catalog_status': catalog_asset.status,
                'catalog_title': catalog_asset.title,
                'needs_update': needs_update
            })
        else:
            # Catalog asset no longer exists
            orphaned_items.append({
                'cms_content_id': cms_content.id,
                'cms_content_name': cms_content.name,
                'catalog_uuid': cms_content.catalog_asset_uuid,
                'error': 'Catalog asset not found'
            })

    return jsonify({
        'synced_items': synced_items[:50],  # Limit to 50 items
        'orphaned_items': orphaned_items,
        'total_synced': len(synced_items),
        'total_orphaned': len(orphaned_items)
    }), 200
