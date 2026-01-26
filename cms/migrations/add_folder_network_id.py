"""
Migration: Add network_id to Folder model

Adds the network_id column to the folders table to associate
folders with specific networks. This enables organizing folders
within network contexts.
"""

import sqlite3
import os


def migrate(db_path):
    """Add network_id column to folders table."""
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(folders)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'network_id' not in columns:
            cursor.execute("""
                ALTER TABLE folders
                ADD COLUMN network_id VARCHAR(36) REFERENCES networks(id)
            """)
            print("Added network_id column to folders table")

            # Create index for network_id
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS ix_folders_network_id
                ON folders(network_id)
            """)
            print("Created index on folders.network_id")
        else:
            print("network_id column already exists in folders table")

        conn.commit()
        return True

    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


def get_db_path():
    """Get the SQLite database path."""
    cms_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(cms_dir, 'data', 'cms.db')


if __name__ == '__main__':
    # Default CMS database path
    db_path = os.environ.get('CMS_DATABASE_PATH', get_db_path())
    migrate(db_path)
