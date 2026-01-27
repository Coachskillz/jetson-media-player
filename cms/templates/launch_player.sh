#!/bin/bash
# Launch Skillz Media Player with persistent fullscreen
# This script starts the player and monitors to keep it fullscreen

export DISPLAY=:0

VIDEO_FILE="${1:-/home/nvidia/skillz-player/content/test_video.mp4}"
PLAYER_SCRIPT="/home/nvidia/skillz-player/simple_player.py"
LOG_FILE="/home/nvidia/skillz-player/logs/player.log"

# Create logs directory
mkdir -p /home/nvidia/skillz-player/logs

echo "Starting Skillz Media Player..."
echo "Video: $VIDEO_FILE"

# Start the player in background
python3 "$PLAYER_SCRIPT" "$VIDEO_FILE" >> "$LOG_FILE" 2>&1 &
PLAYER_PID=$!

echo "Player started with PID: $PLAYER_PID"

# Wait for window to appear
sleep 2

# Function to force fullscreen
force_fullscreen() {
    wmctrl -r 'python3' -b remove,maximized_vert,maximized_horz 2>/dev/null
    wmctrl -r 'python3' -b add,fullscreen 2>/dev/null
    wmctrl -r 'python3' -b add,above 2>/dev/null
}

# Initial fullscreen
force_fullscreen
echo "Fullscreen applied"

# Keep monitoring and maintaining fullscreen
while kill -0 $PLAYER_PID 2>/dev/null; do
    # Check every 5 seconds and re-apply fullscreen if needed
    sleep 5
    force_fullscreen
done

echo "Player exited"
