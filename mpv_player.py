"""
Skillz Media Screens - MPV Player with Smooth Transitions
Keeps MPV running continuously with playlist looping
"""

import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

class MPVPlayer:
    """Media player using MPV with continuous playback."""
    
    def __init__(self, media_dir: str = "./media"):
        self.media_dir = Path(media_dir)
        self.playlists_file = self.media_dir / "playlists.json"
        
        print("🎬 Skillz Media Screens - MPV Player")
        print(f"📁 Media directory: {self.media_dir}")
    
    def load_playlists(self) -> bool:
        """Load playlists from local cache."""
        if not self.playlists_file.exists():
            print(f"❌ Playlists file not found")
            return False
        
        try:
            with open(self.playlists_file, 'r') as f:
                self.playlists_data = json.load(f)
            
            print(f"✅ Loaded {len(self.playlists_data['playlists'])} playlists")
            return True
            
        except Exception as e:
            print(f"❌ Failed to load playlists: {e}")
            return False
    
    def get_default_playlist(self):
        """Get the default playlist."""
        for playlist in self.playlists_data['playlists']:
            if playlist['trigger_type'] == 'default':
                return playlist
        
        if self.playlists_data['playlists']:
            return self.playlists_data['playlists'][0]
        
        return None
    
    def create_mpv_playlist_file(self, playlist) -> str:
        """Create MPV playlist file for smooth continuous playback."""
        # Create temporary playlist file
        playlist_file = tempfile.NamedTemporaryFile(mode='w', suffix='.m3u', delete=False)
        
        print(f"\n📋 Creating playlist: {playlist['name']}")
        print(f"🎯 Trigger: {playlist['trigger_type']}")
        print(f"🎬 Videos: {len(playlist['content'])}\n")
        
        for video in playlist['content']:
            video_path = self.media_dir / video['filename']
            if video_path.exists():
                playlist_file.write(f"{video_path.absolute()}\n")
                print(f"✅ {video['title'][:50]}")
            else:
                print(f"⚠️  Missing: {video['filename']}")
        
        playlist_file.close()
        return playlist_file.name
    
    def play_playlist_continuous(self, playlist):
        """Play playlist continuously with MPV - keeps window open."""
        
        # Create MPV playlist file
        mpv_playlist = self.create_mpv_playlist_file(playlist)
        
        print("\n" + "=" * 60)
        print("🚀 Starting continuous playback...")
        print("Videos will loop smoothly without interruption")
        print("Press 'q' or Ctrl+C to stop")
        print("=" * 60 + "\n")
        
        try:
            # Run MPV with playlist looping
            subprocess.run([
                'mpv',
                '--fs',                      # Fullscreen
                '--loop-playlist=inf',       # Loop playlist infinitely
                '--no-audio-display',        # No album art
                '--quiet',                   # Minimal output
                '--no-osc',                  # No on-screen controller
                '--no-osd-bar',              # No progress bar
                '--osd-level=0',             # No OSD messages
                '--no-input-default-bindings', # Disable most keys (only q works)
                mpv_playlist
            ])
            
        except KeyboardInterrupt:
            print("\n⏸️  Playback stopped")
        finally:
            # Clean up temp playlist file
            import os
            try:
                os.unlink(mpv_playlist)
            except:
                pass
    
    def start(self):
        """Start the player."""
        print("\n" + "=" * 60)
        print("🎬 Skillz Media Screens - Jetson Player")
        print("=" * 60)
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60 + "\n")
        
        if not self.load_playlists():
            return
        
        playlist = self.get_default_playlist()
        
        if not playlist:
            print("❌ No playlists found!")
            return
        
        # Start continuous playback
        self.play_playlist_continuous(playlist)


def main():
    player = MPVPlayer(media_dir="./media")
    player.start()


if __name__ == "__main__":
    main()
