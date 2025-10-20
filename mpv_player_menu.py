"""
Skillz Media Screens - MPV Player with On-Screen Menu
Press 'M' to show overlay control menu
"""

import json
import subprocess
import tempfile
import os
from pathlib import Path
from datetime import datetime

class MPVPlayerWithMenu:
    """Media player with on-screen overlay menu."""
    
    def __init__(self, media_dir: str = "./media"):
        self.media_dir = Path(media_dir)
        self.playlists_file = self.media_dir / "playlists.json"
        self.mpv_process = None
        
        print("🎬 Skillz Media Screens - MPV Player with Menu")
    
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
        """Create MPV playlist file."""
        playlist_file = tempfile.NamedTemporaryFile(mode='w', suffix='.m3u', delete=False)
        
        print(f"\n📋 Playlist: {playlist['name']}")
        print(f"🎬 Videos: {len(playlist['content'])}\n")
        
        for video in playlist['content']:
            video_path = self.media_dir / video['filename']
            if video_path.exists():
                playlist_file.write(f"{video_path.absolute()}\n")
        
        playlist_file.close()
        return playlist_file.name
    
    def create_input_conf(self):
        """Create MPV input config with menu key binding."""
        input_conf = tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False)
        
        # Keyboard shortcuts
        input_conf.write("""
# Skillz Media Player Controls
m show-text "═══════════════════════════════════\\n  SKILLZ MEDIA SCREENS MENU\\n═══════════════════════════════════\\n\\n  [Q] - Quit Player\\n  [SPACE] - Pause/Resume\\n  [F] - Toggle Fullscreen\\n  [R] - Restart Playlist\\n  [→] - Next Video\\n  [←] - Previous Video\\n  [M] - Show This Menu\\n\\n═══════════════════════════════════" 5000
Q quit
SPACE cycle pause
f cycle fullscreen
r playlist-play-index 0
RIGHT playlist-next
LEFT playlist-prev
""")
        
        input_conf.close()
        return input_conf.name
    
    def play_playlist_continuous(self, playlist):
        """Play playlist with on-screen menu."""
        
        mpv_playlist = self.create_mpv_playlist_file(playlist)
        input_conf = self.create_input_conf()
        
        print("\n" + "=" * 60)
        print("🚀 SKILLZ MEDIA SCREENS PLAYER")
        print("=" * 60)
        print("\n⌨️  PRESS 'M' TO SHOW ON-SCREEN MENU")
        print("\nQuick Controls:")
        print("  [M] - Show menu overlay")
        print("  [Q] - Quit")
        print("  [SPACE] - Pause/Resume")
        print("  [F] - Fullscreen toggle")
        print("=" * 60 + "\n")
        
        try:
            # Run MPV with custom input config
            self.mpv_process = subprocess.Popen([
                'mpv',
                '--fs',                          # Fullscreen
                '--loop-playlist=inf',           # Loop infinitely
                '--no-audio-display',            # No album art
                '--quiet',                       # Minimal console output
                '--osd-duration=5000',           # Show OSD messages for 5 seconds
                '--osd-font-size=32',            # Larger OSD text
                '--osd-color=#FFFFFF',           # White text
                '--osd-border-color=#000000',    # Black border
                '--osd-border-size=2',           # Border thickness
                f'--input-conf={input_conf}',    # Custom key bindings
                '--no-osc',                      # Hide default controls
                mpv_playlist
            ])
            
            # Wait for process
            self.mpv_process.wait()
            
        except KeyboardInterrupt:
            print("\n⏸️  Player stopped")
            if self.mpv_process:
                self.mpv_process.terminate()
        finally:
            # Cleanup temp files
            try:
                os.unlink(mpv_playlist)
                os.unlink(input_conf)
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
        
        self.play_playlist_continuous(playlist)


def main():
    player = MPVPlayerWithMenu(media_dir="./media")
    player.start()


if __name__ == "__main__":
    main()
