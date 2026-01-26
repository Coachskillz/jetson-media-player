#!/usr/bin/env python3
"""
Migration: Add layout_id column to devices table.

This migration adds layout assignment support to devices,
allowing layouts to be assigned to individual screens.

Run this script to upgrade an existing database:
    python -m cms.migrations.add_device_layout_id

"""

import os
import sqlite3
import sys

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
    """Run the migration to add layout_id column to devices table."""
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Database will be created with new schema on app startup.")
        return True

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if devices table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='devices'
        """)
        if not cursor.fetchone():
            print("  devices table does not exist, skipping migration")
            return True

        # Add layout_id column
        if column_exists(cursor, 'devices', 'layout_id'):
            print("  layout_id column already exists")
        else:
            print("  Adding layout_id column...")
            cursor.execute("""
                ALTER TABLE devices
                ADD COLUMN layout_id VARCHAR(36)
                REFERENCES screen_layouts(id) ON DELETE SET NULL
            """)
            print("  layout_id column added successfully")

        # Create index
        index_name = 'ix_devices_layout_id'
        if not index_exists(cursor, index_name):
            print(f"  Creating index {index_name}...")
            cursor.execute(f"""
                CREATE INDEX {index_name}
                ON devices(layout_id)
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
