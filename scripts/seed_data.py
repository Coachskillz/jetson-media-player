#!/usr/bin/env python3
"""
Seed script to populate both Content Catalog and CMS databases
with networks, tenants, sample content, and a demo playlist.

Usage:
    python scripts/seed_data.py

Writes directly to local SQLite databases — no Flask app needed.
Idempotent: skips records that already exist.
"""

import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent.parent

# Database paths
CMS_DB = ROOT / 'cms' / 'data' / 'cms.db'
CATALOG_DB = ROOT / 'content_catalog' / 'data' / 'content_catalog.db'

# Upload directories
CMS_UPLOADS = ROOT / 'cms' / 'uploads'
CATALOG_UPLOADS = ROOT / 'content_catalog' / 'uploads'

# Source media
MEDIA_DIR = ROOT / 'media'

# Media files with metadata
MEDIA_FILES = [
    {
        'filename': 'bus_ad._4.mp4',
        'title': 'Bus Ad',
        'duration': 22,
        'duration_float': 22.055,
        'file_size': 7101354,
        'mime_type': 'video/mp4',
    },
    {
        'filename': '8517AleveAleveArthritisPiggybackConnectedTVC15s16915MIAV1096000HInnovid.MP4',
        'title': 'Aleve Arthritis Ad',
        'duration': 15,
        'duration_float': 15.015,
        'file_size': 7999657,
        'mime_type': 'video/mp4',
    },
    {
        'filename': 'social_coachskillz_the_word_look_in_a_dynamic_font_with_eyeballs_in__a79139cb-e492-4549-ba6c-6a5db23cf569_2.mp4',
        'title': 'Coach Skillz Promo',
        'duration': 5,
        'duration_float': 5.208,
        'file_size': 5704195,
        'mime_type': 'video/mp4',
    },
]

# Networks / Tenants
NETWORKS = [
    {'name': 'High Octane Network', 'slug': 'high-octane'},
    {'name': 'On The Wave TV', 'slug': 'on-the-wave'},
]

NOW = datetime.now(timezone.utc).isoformat()


def seed_content_catalog():
    """Seed the Content Catalog database with tenants, catalog, and content assets."""
    if not CATALOG_DB.exists():
        print(f"[SKIP] Content Catalog DB not found at {CATALOG_DB}")
        return

    conn = sqlite3.connect(str(CATALOG_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- Tenants ---
    tenant_ids = {}
    for net in NETWORKS:
        cur.execute("SELECT id, uuid FROM tenants WHERE slug = ?", (net['slug'],))
        row = cur.fetchone()
        if row:
            tenant_ids[net['slug']] = {'id': row['id'], 'uuid': row['uuid']}
            print(f"[EXISTS] Tenant: {net['name']} (slug={net['slug']})")
        else:
            t_uuid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO tenants (uuid, name, slug, description, is_active, requires_content_approval, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, 0, ?, ?)",
                (t_uuid, net['name'], net['slug'], f"{net['name']} digital signage network", NOW, NOW)
            )
            tenant_ids[net['slug']] = {'id': cur.lastrowid, 'uuid': t_uuid}
            print(f"[CREATED] Tenant: {net['name']} (slug={net['slug']})")

    # --- Catalog ---
    cur.execute("SELECT id, uuid FROM catalogs WHERE name = 'Content Library'")
    catalog_row = cur.fetchone()
    if catalog_row:
        catalog_id = catalog_row['id']
        print("[EXISTS] Catalog: Content Library")
    else:
        cat_uuid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO catalogs (uuid, name, description, is_internal_only, is_active, created_at, updated_at) "
            "VALUES (?, 'Content Library', 'Default content library', 0, 1, ?, ?)",
            (cat_uuid, NOW, NOW)
        )
        catalog_id = cur.lastrowid
        print("[CREATED] Catalog: Content Library")

    # --- Get Skillz Media org ID ---
    cur.execute("SELECT id FROM organizations WHERE name = 'Skillz Media'")
    org_row = cur.fetchone()
    org_id = org_row['id'] if org_row else None

    # --- Get admin user ID for uploaded_by ---
    cur.execute("SELECT id FROM users WHERE role = 'super_admin' LIMIT 1")
    admin_row = cur.fetchone()
    admin_id = admin_row['id'] if admin_row else None

    # --- Content Assets ---
    CATALOG_UPLOADS.mkdir(parents=True, exist_ok=True)
    ho_tenant = tenant_ids.get('high-octane', {})

    for media in MEDIA_FILES:
        src = MEDIA_DIR / media['filename']
        if not src.exists():
            print(f"[SKIP] Media file not found: {src}")
            continue

        # Check if already exists
        cur.execute("SELECT id FROM content_assets WHERE title = ?", (media['title'],))
        if cur.fetchone():
            print(f"[EXISTS] Asset: {media['title']}")
            continue

        # Copy file to catalog uploads
        dest = CATALOG_UPLOADS / media['filename']
        if not dest.exists():
            shutil.copy2(str(src), str(dest))
            print(f"  Copied {media['filename']} -> content_catalog/uploads/")

        asset_uuid = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO content_assets (
                uuid, title, filename, file_path, file_size, duration, duration_ms,
                resolution, format, asset_type, content_type, original_filename,
                organization_id, owner_org_type, uploaded_by,
                status, published_at, tenant_id, catalog_id,
                version, synced_to_cms, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                asset_uuid,
                media['title'],
                media['filename'],
                f"uploads/{media['filename']}",
                media['file_size'],
                media['duration_float'],
                int(media['duration_float'] * 1000),
                '1920x1080',
                'mp4',
                'video',
                media['mime_type'],
                media['filename'],
                org_id,
                'SKILLZ',
                admin_id,
                'published',
                NOW,
                ho_tenant.get('id'),
                catalog_id,
                1,
                0,
                NOW,
                NOW,
            )
        )
        print(f"[CREATED] Asset: {media['title']} ({media['duration']}s)")

    conn.commit()
    conn.close()
    print("[DONE] Content Catalog seeded.\n")


def seed_cms():
    """Seed the CMS database with networks, content, folder, and a demo playlist."""
    if not CMS_DB.exists():
        print(f"[SKIP] CMS DB not found at {CMS_DB}")
        return

    conn = sqlite3.connect(str(CMS_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- Networks ---
    network_ids = {}
    for net in NETWORKS:
        cur.execute("SELECT id FROM networks WHERE slug = ?", (net['slug'],))
        row = cur.fetchone()
        if row:
            network_ids[net['slug']] = row['id']
            print(f"[EXISTS] Network: {net['name']}")
        else:
            net_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO networks (id, name, slug, created_at) VALUES (?, ?, ?, ?)",
                (net_id, net['name'], net['slug'], NOW)
            )
            network_ids[net['slug']] = net_id
            print(f"[CREATED] Network: {net['name']}")

    ho_network_id = network_ids.get('high-octane')

    # --- Folder ---
    cur.execute("SELECT id FROM folders WHERE name = 'Ads'")
    folder_row = cur.fetchone()
    if folder_row:
        folder_id = folder_row['id']
        print("[EXISTS] Folder: Ads")
    else:
        folder_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO folders (id, name, icon, network_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (folder_id, 'Ads', '🎬', ho_network_id, NOW)
        )
        print("[CREATED] Folder: Ads")

    # --- Content ---
    CMS_UPLOADS.mkdir(parents=True, exist_ok=True)
    content_ids = []

    for media in MEDIA_FILES:
        src = MEDIA_DIR / media['filename']
        if not src.exists():
            print(f"[SKIP] Media file not found: {src}")
            continue

        # Check if already exists by original_name
        cur.execute("SELECT id FROM content WHERE original_name = ?", (media['filename'],))
        row = cur.fetchone()
        if row:
            content_ids.append(row['id'])
            print(f"[EXISTS] Content: {media['title']}")
            continue

        # Copy file to cms uploads
        dest = CMS_UPLOADS / media['filename']
        if not dest.exists():
            shutil.copy2(str(src), str(dest))
            print(f"  Copied {media['filename']} -> cms/uploads/")

        content_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO content (
                id, filename, original_name, mime_type, file_size,
                duration, status, network_id, folder_id, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                content_id,
                media['filename'],
                media['filename'],
                media['mime_type'],
                media['file_size'],
                media['duration'],
                'approved',
                ho_network_id,
                folder_id,
                'upload',
                NOW,
            )
        )
        content_ids.append(content_id)
        print(f"[CREATED] Content: {media['title']} ({media['duration']}s)")

    # --- Playlist ---
    cur.execute("SELECT id FROM playlists WHERE name = 'Demo Playlist'")
    playlist_row = cur.fetchone()
    if playlist_row:
        print("[EXISTS] Playlist: Demo Playlist")
    else:
        playlist_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO playlists (
                id, name, description, network_id, trigger_type, loop_mode,
                priority, is_active, sync_status, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                playlist_id,
                'Demo Playlist',
                'Sample playlist with 3 video ads',
                ho_network_id,
                'manual',
                'continuous',
                'normal',
                1,
                'draft',
                1,
                NOW,
                NOW,
            )
        )
        print("[CREATED] Playlist: Demo Playlist")

        # Add playlist items
        for pos, cid in enumerate(content_ids):
            item_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO playlist_items (
                    id, playlist_id, content_id, position, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (item_id, playlist_id, cid, pos, NOW)
            )
        print(f"  Added {len(content_ids)} items to Demo Playlist")

    conn.commit()
    conn.close()
    print("[DONE] CMS seeded.\n")


def main():
    print("=" * 60)
    print("Seeding Content Catalog and CMS databases")
    print("=" * 60)
    print()

    seed_content_catalog()
    seed_cms()

    print("=" * 60)
    print("Seed complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
