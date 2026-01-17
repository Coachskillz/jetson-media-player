"""
Jetson Media Player - Hardware Accelerated Playback
Optimized for NVIDIA Jetson with stable GStreamer pipeline
"""

import json
import time
import subprocess
from pathlib import Path
from datetime import datetime

from src.player.config import PlayerConfig


class JetsonPlayer:
    """Hardware-accelerated media player for Jetson devices."""
    
    def __init__(self, media_dir: str = "./media", config_dir: str = None):
        self.media_dir = Path(media_dir)
        self.playlists_file = self.media_dir / "playlists.json"
        self.current_process = None
        self.current_playlist = None
        self.current_video_index = 0

        # Load player configuration
        self.config = PlayerConfig(config_dir)

        # Determine connection mode and content source
        self.connection_mode = self.config.connection_mode
        self.content_source_url = self._get_content_source_url()

        print("🎬 Jetson Media Player Initialized")
        print(f"📁 Media directory: {self.media_dir}")
        print(f"🔗 Connection mode: {self.connection_mode}")
        print(f"🌐 Content source: {self.content_source_url}")

    def _get_content_source_url(self) -> str:
        """
        Get the content source URL based on connection mode.

        Returns:
            URL string - hub_url for hub mode, cms_url for direct mode
        """
        if self.connection_mode == 'hub':
            return self.config.hub_url
        else:
            # Default to direct mode (CMS)
            return self.config.cms_url
    
    def load_playlists(self) -> bool:
        """Load playlists from local cache."""
        if not self.playlists_file.exists():
            print(f"❌ Playlists file not found: {self.playlists_file}")
            print("💡 Run sync_media.py first to download playlists!")
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
        if not hasattr(self, 'playlists_data') or not self.playlists_data:
            return None
        
        for playlist in self.playlists_data['playlists']:
            if playlist['trigger_type'] == 'default':
                return playlist
        
        # If no default, return first playlist
        if self.playlists_data['playlists']:
            return self.playlists_data['playlists'][0]
        
        return None
    
    def play_video_gstreamer(self, video_path: Path) -> subprocess.Popen:
        """
        Play video using GStreamer with hardware acceleration.
        Returns the process handle for proper cleanup.
        """
        if not video_path.exists():
            print(f"❌ Video file not found: {video_path}")
            return None
        
        try:
            # Stable GStreamer pipeline for Jetson
            # Uses nv3dsink for smooth, tear-free playback
            gst_command = [
                'gst-launch-1.0',
                '-q',
                'filesrc', f'location={video_path}',
                '!', 'qtdemux',
                '!', 'h264parse',
                '!', 'nvv4l2decoder',
                '!', 'nvvidconv',
                '!', 'video/x-raw(memory:NVMM)',
                '!', 'nvoverlaysink', 'sync=true'
            ]
            
            print(f"▶️  Playing: {video_path.name}")
            
            # Start video playback
            process = subprocess.Popen(
                gst_command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            return process
            
        except Exception as e:
            print(f"❌ Failed to play video: {e}")
            return None
    
    def wait_for_video(self, process, duration):
        """Wait for video to complete or timeout."""
        if not process:
            return
        
        start_time = time.time()
        
        while time.time() - start_time < duration:
            # Check if process is still running
            if process.poll() is not None:
                # Video finished early
                break
            time.sleep(0.1)
        
        # Ensure process is terminated
        try:
            process.terminate()
            process.wait(timeout=1)
        except:
            process.kill()
    
    def play_playlist_loop(self, playlist):
        """Play all videos in playlist in continuous loop."""
        if not playlist or not playlist['content']:
            print("❌ Empty playlist")
            return
        
        print("\n" + "=" * 60)
        print(f"📋 Playlist: {playlist['name']}")
        print(f"🎯 Trigger: {playlist['trigger_type']}")
        print(f"🎬 Videos: {len(playlist['content'])}")
        print("=" * 60 + "\n")
        
        self.current_playlist = playlist
        self.current_video_index = 0
        
        # Play videos in continuous loop
        while True:
            try:
                # Get current video
                video = playlist['content'][self.current_video_index]
                video_path = self.media_dir / video['filename']
                
                video_num = self.current_video_index + 1
                total_videos = len(playlist['content'])
                duration = video.get('duration', 30.0)
                
                print(f"\n[{video_num}/{total_videos}] {video['title'][:50]}")
                print(f"⏱️  Duration: {duration}s")
                
                # Play video
                process = self.play_video_gstreamer(video_path)
                
                if process:
                    # Wait for video to complete
                    self.wait_for_video(process, duration)
                else:
                    print(f"⚠️  Skipping {video['filename']}")
                    time.sleep(1)
                
                # Move to next video (loop back to start)
                self.current_video_index = (self.current_video_index + 1) % total_videos
                
                # Small transition delay (reduces flashing)
                time.sleep(0.2)
                
            except KeyboardInterrupt:
                print("\n\n⏸️  Playback stopped by user")
                if self.current_process:
                    try:
                        self.current_process.terminate()
                    except:
                        pass
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                time.sleep(2)
    
    def start(self):
        """Start the media player."""
        print("\n" + "=" * 60)
        print("🎬 Skillz Media Screens - Jetson Player")
        print("=" * 60)
        print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"💾 Media Dir: {self.media_dir.absolute()}")
        print(f"🔗 Mode: {self.connection_mode.upper()}")
        print(f"🌐 Source: {self.content_source_url}")
        print("=" * 60 + "\n")
        
        # Load playlists
        if not self.load_playlists():
            return
        
        # Get default playlist
        playlist = self.get_default_playlist()
        
        if not playlist:
            print("❌ No playlists found!")
            return
        
        # Verify all videos exist
        missing = []
        for video in playlist['content']:
            video_path = self.media_dir / video['filename']
            if not video_path.exists():
                missing.append(video['filename'])
        
        if missing:
            print(f"⚠️  Warning: {len(missing)} videos not found:")
            for f in missing:
                print(f"   - {f}")
            print("\n💡 Run sync_media.py to download missing videos\n")
            
            if len(missing) == len(playlist['content']):
                print("❌ No videos available to play!")
                return
        
        # Start playing
        print("🚀 Starting playback...")
        print("Press Ctrl+C to stop\n")
        
        self.play_playlist_loop(playlist)


def main():
    """Main entry point."""
    player = JetsonPlayer(media_dir="./media")
    player.start()


if __name__ == "__main__":
    main()
