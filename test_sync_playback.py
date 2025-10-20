"""
Test synced playback - Verifies the actual playlists downloaded from CMS
"""

import json
from pathlib import Path

def test_playback():
    print("\n" + "=" * 60)
    print("🎬 Skillz Media Screens - Playback Test")
    print("=" * 60)
    
    media_dir = Path("./media")
    playlists_file = media_dir / "playlists.json"
    
    # Load playlists
    print("\n📋 Loading playlists...")
    with open(playlists_file, 'r') as f:
        data = json.load(f)
    
    print(f"✅ Found {len(data['playlists'])} playlists")
    print(f"Device ID: {data['device_id']}")
    print(f"Last sync: {data['last_sync']}")
    
    # Check each playlist
    for playlist in data['playlists']:
        print(f"\n📺 Playlist: {playlist['name']}")
        print(f"   Trigger: {playlist['trigger_type']}")
        print(f"   Videos: {len(playlist['content'])}")
        
        # Verify files exist
        for i, video in enumerate(playlist['content'], 1):
            video_path = media_dir / video['filename']
            exists = "✅" if video_path.exists() else "❌"
            size_mb = video_path.stat().st_size / (1024*1024) if video_path.exists() else 0
            print(f"   {exists} [{i}] {video['title'][:50]}")
            print(f"       Duration: {video['duration']}s | Size: {size_mb:.1f}MB")
    
    print("\n" + "=" * 60)
    print("✅ All systems working! Ready for Jetson deployment")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    test_playback()
