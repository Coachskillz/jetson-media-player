#!/usr/bin/env python3
"""
Migration: Add folder_id column to content table.

This migration adds folder organization support to the Content model,
allowing content items to be organized into folders.

Changes:
- Adds folder_id column (VARCHAR(36), nullable, foreign key to folders.id)
- Creates index on folder_id for efficient filtering

Run this script to upgrade an existing database:
    python -m cms.migrations.add_content_folder_id

Or import and call migrate() from Python:
    from cms.migrations.add_content_folder_id import migrate
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
    """Run the migration to add folder_id column to content table."""
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Database will be created with new schema on app startup.")
        return True

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if content table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='content'
        """)
        if not cursor.fetchone():
            print("  content table does not exist, skipping migration")
            print("  Table will be created with new schema on app startup.")
            return True

        # Check if folder_id column already exists
        if column_exists(cursor, 'content', 'folder_id'):
            print("  folder_id column already exists in content table")
        else:
            print("  Adding folder_id column to content table...")
            cursor.execute("""
                ALTER TABLE content
                ADD COLUMN folder_id VARCHAR(36)
                REFERENCES folders(id)
            """)
            print("  folder_id column added successfully")

        # Create index if it doesn't exist
        index_name = 'ix_content_folder_id'
        if not index_exists(cursor, index_name):
            print(f"  Creating index {index_name}...")
            cursor.execute(f"""
                CREATE INDEX {index_name}
                ON content(folder_id)
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
