"""
Media Sync Service - Downloads content from CMS to local storage
"""

import requests
import os
import json
from pathlib import Path
from src.common.device_id import get_device_info
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class MediaSync:
    """Syncs media content from CMS to local device storage."""
    
    def __init__(self, cms_url: str = "http://localhost:5001", media_dir: str = "media"):
        self.cms_url = cms_url
        self.device_info = get_device_info()
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_file = self.media_dir / "playlists.json"
        
    def get_device_config(self):
        """Get device configuration including assigned playlists."""
        try:
            response = requests.get(
                f"{self.cms_url}/api/v1/device/{self.device_info['device_id']}/config",
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get device config: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting device config: {e}")
            return None
    
    def download_video(self, filename: str) -> bool:
        """Download a video file from CMS to local storage."""
        local_path = self.media_dir / filename
        
        # Skip if already downloaded
        if local_path.exists():
            logger.info(f"Video already exists: {filename}")
            return True
        
        try:
            logger.info(f"Downloading {filename}...")
            
            response = requests.get(
                f"{self.cms_url}/cms/uploads/{filename}",
                stream=True,
                timeout=60
            )
            
            if response.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                logger.info(f"✅ Downloaded: {filename}")
                return True
            else:
                logger.error(f"Failed to download {filename}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error downloading {filename}: {e}")
            return False
    
    def sync_playlist_content(self, playlist_id: int) -> list:
        """Download all content for a playlist."""
        try:
            response = requests.get(
                f"{self.cms_url}/api/playlists/{playlist_id}/items",
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get playlist items: {response.status_code}")
                return []
            
            items = response.json()
            downloaded = []
            
            for item in items:
                if self.download_video(item['filename']):
                    downloaded.append({
                        'filename': item['filename'],
                        'title': item['title'],
                        'duration': item['duration']
                    })
            
            return downloaded
            
        except Exception as e:
            logger.error(f"Error syncing playlist content: {e}")
            return []
    
    def sync_all(self) -> bool:
        """Sync all assigned playlists and their content."""
        logger.info("🔄 Starting media sync...")
        
        # Get device configuration
        config = self.get_device_config()
        
        if not config or 'playlists' not in config:
            logger.warning("No playlists assigned to this device")
            return False
        
        playlists = config['playlists']
        
        if not playlists:
            logger.info("No playlists assigned")
            return True
        
        # Sync each playlist
        synced_playlists = []
        
        for playlist in playlists:
            logger.info(f"Syncing playlist: {playlist['name']}")
            
            content = self.sync_playlist_content(playlist['id'])
            
            if content:
                synced_playlists.append({
                    'id': playlist['id'],
                    'name': playlist['name'],
                    'trigger_type': playlist.get('trigger_type', 'default'),
                    'trigger_value': playlist.get('trigger_value', ''),
                    'content': content
                })
        
        # Save playlist configuration locally
        with open(self.config_file, 'w') as f:
            json.dump({
                'device_id': self.device_info['device_id'],
                'playlists': synced_playlists,
                'last_sync': str(datetime.now())
            }, f, indent=2)
        
        logger.info(f"✅ Sync complete! {len(synced_playlists)} playlists synced")
        return True
    
    def get_local_playlists(self) -> dict:
        """Get locally cached playlists."""
        if not self.config_file.exists():
            return {'playlists': []}
        
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading local playlists: {e}")
            return {'playlists': []}
    
    def get_playlist_by_trigger(self, trigger_type: str, trigger_value: str = None):
        """Get playlist for a specific trigger."""
        config = self.get_local_playlists()
        
        for playlist in config.get('playlists', []):
            if playlist['trigger_type'] == trigger_type:
                if trigger_value is None or playlist.get('trigger_value') == trigger_value:
                    return playlist
        
        # Return default playlist if no match
        for playlist in config.get('playlists', []):
            if playlist['trigger_type'] == 'default':
                return playlist
        
        return None


if __name__ == "__main__":
    from datetime import datetime
    
    print("🎬 Jetson Media Sync")
    print("=" * 50)
    
    sync = MediaSync()
    
    if sync.sync_all():
        print("\n✅ Sync successful!")
        
        # Show what was synced
        config = sync.get_local_playlists()
        print(f"\nSynced Playlists:")
        for playlist in config.get('playlists', []):
            print(f"\n📋 {playlist['name']}")
            print(f"   Trigger: {playlist['trigger_type']}")
            print(f"   Videos: {len(playlist['content'])}")
            for item in playlist['content']:
                print(f"   - {item['title']} ({item['duration']}s)")
    else:
        print("\n❌ Sync failed")
