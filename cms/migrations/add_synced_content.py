#!/usr/bin/env python3
"""
Migration: Add synced_content table for Content Catalog integration.

This migration creates the synced_content table which caches approved/published
content from the Content Catalog service for display in the CMS content page.

Table columns:
- id: Primary key UUID
- source_uuid: UUID from Content Catalog (unique, indexed)
- title: Human-readable title
- description: Optional content description
- filename: Original filename
- file_path: Path to content file in Content Catalog storage
- file_size: File size in bytes
- duration: Duration in seconds (video/audio)
- resolution: Video/image resolution (e.g., "1920x1080")
- format: File format/codec (e.g., "mp4", "jpeg")
- thumbnail_url: URL or path to thumbnail image
- category: Content category for filtering
- tags: Comma-separated tags
- status: Approval status (approved, published, archived)
- organization_id: Source organization ID (indexed)
- organization_name: Cached organization name
- network_ids: JSON string of network IDs
- content_catalog_url: Base URL of Content Catalog
- synced_at: Last sync timestamp
- created_at: Original creation timestamp
- published_at: Publication timestamp

Run this script to upgrade an existing database:
    python -m cms.migrations.add_synced_content

Or import and call migrate() from Python:
    from cms.migrations.add_synced_content import migrate
    migrate()
"""

import os
import sqlite3
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def get_db_path():
    """Get the SQLite database path."""
    cms_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(cms_dir, 'data', 'cms.db')


def table_exists(cursor, table_name):
    """Check if a table exists in the database."""
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (table_name,))
    return cursor.fetchone() is not None


def index_exists(cursor, index_name):
    """Check if an index exists in the database."""
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND name=?
    """, (index_name,))
    return cursor.fetchone() is not None


def migrate():
    """Run the migration to create synced_content table."""
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Database will be created with new schema on app startup.")
        return True

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if table already exists
        if table_exists(cursor, 'synced_content'):
            print("  synced_content table already exists")
        else:
            print("  Creating synced_content table...")
            cursor.execute("""
                CREATE TABLE synced_content (
                    id VARCHAR(36) PRIMARY KEY,
                    source_uuid VARCHAR(36) UNIQUE NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    description TEXT,
                    filename VARCHAR(500) NOT NULL,
                    file_path VARCHAR(1000),
                    file_size INTEGER,
                    duration FLOAT,
                    resolution VARCHAR(50),
                    format VARCHAR(50),
                    thumbnail_url VARCHAR(1000),
                    category VARCHAR(100),
                    tags TEXT,
                    status VARCHAR(50) DEFAULT 'approved' NOT NULL,
                    organization_id INTEGER,
                    organization_name VARCHAR(255),
                    network_ids TEXT,
                    content_catalog_url VARCHAR(500),
                    synced_at DATETIME,
                    created_at DATETIME,
                    published_at DATETIME
                )
            """)
            print("  synced_content table created successfully")

        # Create indexes if they don't exist
        indexes = [
            ('ix_synced_content_source_uuid', 'source_uuid'),
            ('ix_synced_content_status', 'status'),
            ('ix_synced_content_organization_id', 'organization_id'),
        ]

        for index_name, column_name in indexes:
            if not index_exists(cursor, index_name):
                print(f"  Creating index {index_name}...")
                cursor.execute(f"""
                    CREATE INDEX {index_name}
                    ON synced_content({column_name})
                """)
            else:
                print(f"  Index {index_name} already exists")

        conn.commit()
        print("\nMigration completed successfully!")
        return True

    except Exception as e:
        conn.rollback()
        print(f"\nMigration failed: {e}")
        return False

    finally:
        conn.close()


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
