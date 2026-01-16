#!/usr/bin/env python3
"""
Migration: Add camera settings and trigger_type columns.

This migration adds:
- camera1_enabled, camera1_demographics, camera1_loyalty to devices table
- camera2_enabled, camera2_ncmec to devices table
- trigger_type to device_assignments table

Run this script to upgrade an existing database:
    python -m cms.migrations.add_camera_and_trigger_columns

Or import and call migrate() from Python:
    from cms.migrations.add_camera_and_trigger_columns import migrate
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
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def migrate():
    """Run the migration to add new columns."""
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Database will be created with new schema on app startup.")
        return True

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Add camera columns to devices table
        device_columns = [
            ('camera1_enabled', 'BOOLEAN DEFAULT 0'),
            ('camera1_demographics', 'BOOLEAN DEFAULT 0'),
            ('camera1_loyalty', 'BOOLEAN DEFAULT 0'),
            ('camera2_enabled', 'BOOLEAN DEFAULT 0'),
            ('camera2_ncmec', 'BOOLEAN DEFAULT 0'),
        ]

        for column_name, column_def in device_columns:
            if not column_exists(cursor, 'devices', column_name):
                print(f"  Adding devices.{column_name}...")
                cursor.execute(f"ALTER TABLE devices ADD COLUMN {column_name} {column_def}")
            else:
                print(f"  devices.{column_name} already exists")

        # Add trigger_type column to device_assignments table
        if not column_exists(cursor, 'device_assignments', 'trigger_type'):
            print("  Adding device_assignments.trigger_type...")
            cursor.execute("""
                ALTER TABLE device_assignments
                ADD COLUMN trigger_type VARCHAR(50) DEFAULT 'default'
            """)
        else:
            print("  device_assignments.trigger_type already exists")

        # Create index on trigger_type if it doesn't exist
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='ix_device_assignments_trigger_type'
        """)
        if not cursor.fetchone():
            print("  Creating index on device_assignments.trigger_type...")
            cursor.execute("""
                CREATE INDEX ix_device_assignments_trigger_type
                ON device_assignments(trigger_type)
            """)
        else:
            print("  Index on trigger_type already exists")

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
