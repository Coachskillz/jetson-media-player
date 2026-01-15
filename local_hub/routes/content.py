"""
Content management API endpoints.

This module provides REST API endpoints for content distribution to screens:
- GET /content - Get content manifest with all cached content and hashes
- GET /content/{content_id}/download - Download a specific content file

All endpoints are prefixed with /api/v1 when registered with the app.
"""

import os

from flask import jsonify, send_file

from models import Content
from routes import content_bp


@content_bp.route('', methods=['GET'])
def get_content_manifest():
    """
    Get content manifest listing all cached content.

    Jetson screens call this endpoint to determine which content
    they need to download or update. The manifest includes file
    hashes for integrity verification and change detection.

    Returns:
        200: Content manifest
            {
                "success": true,
                "content": [
                    {
                        "content_id": "abc123",
                        "filename": "video.mp4",
                        "file_hash": "sha256...",
                        "file_size": 1024000,
                        "content_type": "video",
                        "duration_seconds": 30
                    },
                    ...
                ],
                "count": 5
            }
    """
    manifest = Content.get_manifest()

    return jsonify({
        'success': True,
        'content': manifest,
        'count': len(manifest)
    }), 200


@content_bp.route('/<string:content_id>/download', methods=['GET'])
def download_content(content_id):
    """
    Download a specific content file.

    Jetson screens call this endpoint to download content files
    from the hub's local cache. The file is streamed directly
    from the local storage path.

    Args:
        content_id: Content identifier from HQ

    Returns:
        200: File streamed with appropriate content type
        404: Content not found or not cached
            {
                "success": false,
                "error": "Content not found"
            }
    """
    # Validate content_id format (basic sanitization)
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'success': False,
            'error': 'Invalid content_id format'
        }), 400

    # Find content by content_id
    content = Content.get_by_content_id(content_id)

    if not content:
        return jsonify({
            'success': False,
            'error': 'Content not found'
        }), 404

    # Check if content is cached locally
    if not content.is_cached:
        return jsonify({
            'success': False,
            'error': 'Content not cached locally'
        }), 404

    # Verify local file exists
    local_path = content.local_path
    if not local_path or not os.path.isfile(local_path):
        return jsonify({
            'success': False,
            'error': 'Content file not found on disk'
        }), 404

    # Update last accessed timestamp
    content.mark_accessed()

    # Determine MIME type based on content type
    mime_types = {
        'video': 'video/mp4',
        'image': 'image/jpeg',
        'audio': 'audio/mpeg'
    }
    mime_type = mime_types.get(content.content_type, 'application/octet-stream')

    # Stream the file
    return send_file(
        local_path,
        mimetype=mime_type,
        as_attachment=True,
        download_name=content.filename
    )


@content_bp.route('/<string:content_id>', methods=['GET'])
def get_content_info(content_id):
    """
    Get metadata for a specific content item.

    Returns detailed information about a single content item
    including its cache status and file hash.

    Args:
        content_id: Content identifier from HQ

    Returns:
        200: Content metadata
            {
                "success": true,
                "content": {
                    "content_id": "abc123",
                    "filename": "video.mp4",
                    "file_hash": "sha256...",
                    "file_size": 1024000,
                    "content_type": "video",
                    "duration_seconds": 30,
                    "cached": true
                }
            }
        404: Content not found
            {
                "success": false,
                "error": "Content not found"
            }
    """
    # Validate content_id format (basic sanitization)
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'success': False,
            'error': 'Invalid content_id format'
        }), 400

    content = Content.get_by_content_id(content_id)

    if not content:
        return jsonify({
            'success': False,
            'error': 'Content not found'
        }), 404

    # Return content info with cache status
    content_data = content.to_manifest_item()
    content_data['cached'] = content.is_cached

    return jsonify({
        'success': True,
        'content': content_data
    }), 200
