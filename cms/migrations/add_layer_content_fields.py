#!/usr/bin/env python3
"""
Migration: Add content source fields to screen_layers table.

This migration adds support for assigning playlists and content to layers:
- content_source: Type of content ('none', 'playlist', 'static', 'widget')
- playlist_id: Foreign key to playlists table
- content_id: Reference to content item
- is_primary: Boolean flag for primary layer (receives triggered content)

Run this script to upgrade an existing database:
    python -m cms.migrations.add_layer_content_fields

Or import and call migrate() from Python:
    from cms.migrations.add_layer_content_fields import migrate
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


def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    return any(col[1] == column_name for col in columns)


def index_exists(cursor, index_name):
    """Check if an index exists in the database."""
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND name=?
    """, (index_name,))
    return cursor.fetchone() is not None


def migrate():
    """Run the migration to add content source fields to screen_layers table."""
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Database will be created with new schema on app startup.")
        return True

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if screen_layers table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='screen_layers'
        """)
        if not cursor.fetchone():
            print("  screen_layers table does not exist, skipping migration")
            print("  Table will be created with new schema on app startup.")
            return True

        # Add content_source column
        if column_exists(cursor, 'screen_layers', 'content_source'):
            print("  content_source column already exists")
        else:
            print("  Adding content_source column...")
            cursor.execute("""
                ALTER TABLE screen_layers
                ADD COLUMN content_source VARCHAR(50) DEFAULT 'none'
            """)
            print("  content_source column added successfully")

        # Add playlist_id column
        if column_exists(cursor, 'screen_layers', 'playlist_id'):
            print("  playlist_id column already exists")
        else:
            print("  Adding playlist_id column...")
            cursor.execute("""
                ALTER TABLE screen_layers
                ADD COLUMN playlist_id VARCHAR(36)
                REFERENCES playlists(id) ON DELETE SET NULL
            """)
            print("  playlist_id column added successfully")

        # Add content_id column
        if column_exists(cursor, 'screen_layers', 'content_id'):
            print("  content_id column already exists")
        else:
            print("  Adding content_id column...")
            cursor.execute("""
                ALTER TABLE screen_layers
                ADD COLUMN content_id VARCHAR(36)
            """)
            print("  content_id column added successfully")

        # Add is_primary column
        if column_exists(cursor, 'screen_layers', 'is_primary'):
            print("  is_primary column already exists")
        else:
            print("  Adding is_primary column...")
            cursor.execute("""
                ALTER TABLE screen_layers
                ADD COLUMN is_primary BOOLEAN DEFAULT 0
            """)
            print("  is_primary column added successfully")

        # Create indexes
        indexes = [
            ('ix_screen_layers_playlist_id', 'playlist_id'),
            ('ix_screen_layers_content_id', 'content_id'),
        ]

        for index_name, column in indexes:
            if not index_exists(cursor, index_name):
                print(f"  Creating index {index_name}...")
                cursor.execute(f"""
                    CREATE INDEX {index_name}
                    ON screen_layers({column})
                """)
                print(f"  Index {index_name} created successfully")
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
