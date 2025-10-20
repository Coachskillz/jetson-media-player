"""
Playback Service - Main video player for Jetson Media Player
Loads playlists from local cache and plays videos in loop
"""

import time
import json
import vlc
from pathlib import Path
from src.common.logger import setup_logger

logger = setup_logger(__name__)


class PlaybackService:
    """Main playback service that plays videos from cached playlists."""
    
    def __init__(self, media_dir: str = "./media"):
        self.media_dir = Path(media_dir)
        self.playlists_file = self.media_dir / "playlists.json"
        
        # VLC player instance
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        
        # Playback state
        self.current_playlist = None
        self.current_video_index = 0
        self.playlists_data = None
        
        logger.info("Playback service initialized")
    
    def load_playlists(self) -> bool:
        """Load playlists from local cache."""
        if not self.playlists_file.exists():
            logger.error(f"Playlists file not found: {self.playlists_file}")
            return False
        
        try:
            with open(self.playlists_file, 'r') as f:
                self.playlists_data = json.load(f)
            
            logger.info(f"Loaded {len(self.playlists_data['playlists'])} playlists")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load playlists: {e}")
            return False
    
    def get_default_playlist(self):
        """Get the default playlist."""
        if not self.playlists_data:
            return None
        
        for playlist in self.playlists_data['playlists']:
            if playlist['trigger_type'] == 'default':
                return playlist
        
        # If no default, return first playlist
        if self.playlists_data['playlists']:
            return self.playlists_data['playlists'][0]
        
        return None
    
    def get_playlist_by_trigger(self, trigger_type: str, trigger_value: str = None):
        """Get playlist for a specific trigger."""
        if not self.playlists_data:
            return None
        
        for playlist in self.playlists_data['playlists']:
            if playlist['trigger_type'] == trigger_type:
                if trigger_value is None or playlist.get('trigger_value') == trigger_value:
                    return playlist
        
        # Fallback to default
        return self.get_default_playlist()
    
    def play_video(self, video_path: Path) -> bool:
        """Play a single video."""
        if not video_path.exists():
            logger.error(f"Video file not found: {video_path}")
            return False
        
        try:
            media = self.instance.media_new(str(video_path))
            self.player.set_media(media)
            self.player.play()
            
            logger.info(f"Playing: {video_path.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to play video: {e}")
            return False
    
    def play_playlist(self, playlist):
        """Play all videos in a playlist in loop."""
        if not playlist or not playlist['content']:
            logger.error("Empty playlist")
            return
        
        logger.info(f"Starting playlist: {playlist['name']}")
        logger.info(f"Trigger: {playlist['trigger_type']}")
        logger.info(f"Videos: {len(playlist['content'])}")
        
        self.current_playlist = playlist
        self.current_video_index = 0
        
        # Play videos in loop
        while True:
            try:
                # Get current video
                video = playlist['content'][self.current_video_index]
                video_path = self.media_dir / video['filename']
                
                logger.info(f"[{self.current_video_index + 1}/{len(playlist['content'])}] {video['title']}")
                
                # Play video
                if not self.play_video(video_path):
                    logger.error(f"Failed to play {video['filename']}, skipping...")
                    self.current_video_index = (self.current_video_index + 1) % len(playlist['content'])
                    continue
                
                # Wait for video to finish
                duration = video.get('duration', 30.0)
                time.sleep(duration)
                
                # Move to next video
                self.current_video_index = (self.current_video_index + 1) % len(playlist['content'])
                
                # Small delay between videos
                time.sleep(0.5)
                
            except KeyboardInterrupt:
                logger.info("Playback interrupted")
                break
            except Exception as e:
                logger.error(f"Error during playback: {e}")
                time.sleep(2)
    
    def start(self):
        """Start playback service."""
        logger.info("=" * 60)
        logger.info("🎬 Skillz Media Screens - Playback Service")
        logger.info("=" * 60)
        
        # Load playlists
        if not self.load_playlists():
            logger.error("Failed to load playlists. Run media sync first!")
            return
        
        # Get default playlist
        playlist = self.get_default_playlist()
        
        if not playlist:
            logger.error("No playlists found!")
            return
        
        # Start playing
        self.play_playlist(playlist)
    
    def stop(self):
        """Stop playback."""
        if self.player:
            self.player.stop()
        logger.info("Playback stopped")


def main():
    """Main entry point."""
    print("\n" + "=" * 60)
    print("🎬 Skillz Media Screens - Playback Service")
    print("=" * 60)
    print("\nStarting playback from locally cached content...")
    print("Press Ctrl+C to stop\n")
    print("=" * 60 + "\n")
    
    service = PlaybackService(media_dir="./media")
    
    try:
        service.start()
    except KeyboardInterrupt:
        print("\n\nStopping playback...")
        service.stop()
        print("✅ Playback service stopped\n")


if __name__ == "__main__":
    main()
