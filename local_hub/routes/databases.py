"""
Database management API endpoints.

This module provides REST API endpoints for database distribution to screens:
- GET /databases/ncmec/version - Get NCMEC database version and hash
- GET /databases/ncmec/download - Download NCMEC FAISS database file
- GET /databases/loyalty/version - Get Loyalty database version and hash
- GET /databases/loyalty/download - Download Loyalty FAISS database file

All endpoints are prefixed with /api/v1 when registered with the app.

These FAISS databases are used for facial recognition:
- NCMEC: National Center for Missing & Exploited Children database
- Loyalty: Customer loyalty/membership recognition database
"""

import os

from flask import jsonify, send_file, current_app

from models import SyncStatus
from routes import databases_bp


# FAISS database file names
NCMEC_DB_FILENAME = 'ncmec.faiss'
LOYALTY_DB_FILENAME = 'loyalty.faiss'


def _get_databases_path():
    """
    Get the databases storage path from app config.

    Returns:
        str: Path to databases storage directory
    """
    return current_app.config.get('DATABASES_PATH', '/var/skillz-hub/storage/databases')


@databases_bp.route('/ncmec/version', methods=['GET'])
def get_ncmec_version():
    """
    Get version information for NCMEC database.

    Jetson screens call this endpoint to check if they need to
    download an updated NCMEC database. The file_hash can be used
    to verify integrity after download.

    Returns:
        200: Version information
            {
                "success": true,
                "version": "2024-01-15T10:30:00Z",
                "file_hash": "sha256...",
                "file_size": 1024000,
                "last_updated": "2024-01-15T10:30:00Z"
            }
        404: Database not synced yet
            {
                "success": false,
                "error": "NCMEC database not available"
            }
    """
    status = SyncStatus.get_by_type(SyncStatus.RESOURCE_NCMEC_DB)

    if not status or not status.is_synced:
        return jsonify({
            'success': False,
            'error': 'NCMEC database not available'
        }), 404

    version_info = status.to_version_info()
    version_info['success'] = True

    return jsonify(version_info), 200


@databases_bp.route('/ncmec/download', methods=['GET'])
def download_ncmec_database():
    """
    Download the NCMEC FAISS database file.

    Jetson screens call this endpoint to download the NCMEC
    database for local facial recognition. The file is streamed
    directly from local storage.

    Returns:
        200: FAISS file streamed with application/octet-stream type
        404: Database not available
            {
                "success": false,
                "error": "NCMEC database not available"
            }
    """
    status = SyncStatus.get_by_type(SyncStatus.RESOURCE_NCMEC_DB)

    if not status or not status.is_synced:
        return jsonify({
            'success': False,
            'error': 'NCMEC database not available'
        }), 404

    # Construct path to database file
    databases_path = _get_databases_path()
    file_path = os.path.join(databases_path, NCMEC_DB_FILENAME)

    # Verify file exists on disk
    if not os.path.isfile(file_path):
        return jsonify({
            'success': False,
            'error': 'NCMEC database file not found on disk'
        }), 404

    # Stream the file
    return send_file(
        file_path,
        mimetype='application/octet-stream',
        as_attachment=True,
        download_name=NCMEC_DB_FILENAME
    )


@databases_bp.route('/loyalty/version', methods=['GET'])
def get_loyalty_version():
    """
    Get version information for Loyalty database.

    Jetson screens call this endpoint to check if they need to
    download an updated Loyalty database. The file_hash can be used
    to verify integrity after download.

    Returns:
        200: Version information
            {
                "success": true,
                "version": "2024-01-15T10:30:00Z",
                "file_hash": "sha256...",
                "file_size": 1024000,
                "last_updated": "2024-01-15T10:30:00Z"
            }
        404: Database not synced yet
            {
                "success": false,
                "error": "Loyalty database not available"
            }
    """
    status = SyncStatus.get_by_type(SyncStatus.RESOURCE_LOYALTY_DB)

    if not status or not status.is_synced:
        return jsonify({
            'success': False,
            'error': 'Loyalty database not available'
        }), 404

    version_info = status.to_version_info()
    version_info['success'] = True

    return jsonify(version_info), 200


@databases_bp.route('/loyalty/download', methods=['GET'])
def download_loyalty_database():
    """
    Download the Loyalty FAISS database file.

    Jetson screens call this endpoint to download the Loyalty
    database for local customer recognition. The file is streamed
    directly from local storage.

    Returns:
        200: FAISS file streamed with application/octet-stream type
        404: Database not available
            {
                "success": false,
                "error": "Loyalty database not available"
            }
    """
    status = SyncStatus.get_by_type(SyncStatus.RESOURCE_LOYALTY_DB)

    if not status or not status.is_synced:
        return jsonify({
            'success': False,
            'error': 'Loyalty database not available'
        }), 404

    # Construct path to database file
    databases_path = _get_databases_path()
    file_path = os.path.join(databases_path, LOYALTY_DB_FILENAME)

    # Verify file exists on disk
    if not os.path.isfile(file_path):
        return jsonify({
            'success': False,
            'error': 'Loyalty database file not found on disk'
        }), 404

    # Stream the file
    return send_file(
        file_path,
        mimetype='application/octet-stream',
        as_attachment=True,
        download_name=LOYALTY_DB_FILENAME
    )


@databases_bp.route('', methods=['GET'])
def list_databases():
    """
    List all available databases with their status.

    Returns status information for all database types including
    version, sync status, and availability.

    Returns:
        200: List of database statuses
            {
                "success": true,
                "databases": [
                    {
                        "type": "ncmec_db",
                        "available": true,
                        "version": "2024-01-15T10:30:00Z",
                        "file_hash": "sha256...",
                        "file_size": 1024000,
                        "last_updated": "2024-01-15T10:30:00Z"
                    },
                    ...
                ],
                "count": 2
            }
    """
    databases = []

    # Get NCMEC database status
    ncmec_status = SyncStatus.get_by_type(SyncStatus.RESOURCE_NCMEC_DB)
    if ncmec_status:
        db_info = ncmec_status.to_version_info()
        db_info['type'] = SyncStatus.RESOURCE_NCMEC_DB
        db_info['available'] = ncmec_status.is_synced
        databases.append(db_info)
    else:
        databases.append({
            'type': SyncStatus.RESOURCE_NCMEC_DB,
            'available': False,
            'version': None,
            'file_hash': None,
            'file_size': None,
            'last_updated': None
        })

    # Get Loyalty database status
    loyalty_status = SyncStatus.get_by_type(SyncStatus.RESOURCE_LOYALTY_DB)
    if loyalty_status:
        db_info = loyalty_status.to_version_info()
        db_info['type'] = SyncStatus.RESOURCE_LOYALTY_DB
        db_info['available'] = loyalty_status.is_synced
        databases.append(db_info)
    else:
        databases.append({
            'type': SyncStatus.RESOURCE_LOYALTY_DB,
            'available': False,
            'version': None,
            'file_hash': None,
            'file_size': None,
            'last_updated': None
        })

    return jsonify({
        'success': True,
        'databases': databases,
        'count': len(databases)
    }), 200
