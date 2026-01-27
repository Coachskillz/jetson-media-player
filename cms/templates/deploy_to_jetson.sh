#!/bin/bash
# Deploy Skillz Media Player to Jetson Device
# Usage: ./deploy_to_jetson.sh <jetson_ip> [ssh_user]

JETSON_IP="${1:-192.168.1.94}"
SSH_USER="${2:-nvidia}"
SSH_TARGET="${SSH_USER}@${JETSON_IP}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_DIR="/home/nvidia/skillz-player"

echo "============================================="
echo "Deploying Skillz Media Player to Jetson"
echo "Target: ${SSH_TARGET}"
echo "============================================="

# Create remote directory structure
echo "Creating directory structure..."
ssh "${SSH_TARGET}" "mkdir -p ${REMOTE_DIR}/{src,config,media,logs}"

# Copy Python files
echo "Copying player files..."
scp "${SCRIPT_DIR}/skillz_player.py" "${SSH_TARGET}:${REMOTE_DIR}/main.py"
scp "${SCRIPT_DIR}/layout_renderer.py" "${SSH_TARGET}:${REMOTE_DIR}/src/layout_renderer.py"
scp "${SCRIPT_DIR}/health_server.py" "${SSH_TARGET}:${REMOTE_DIR}/src/health_server.py"

# Create systemd service
echo "Creating systemd service..."
ssh "${SSH_TARGET}" "cat > /tmp/skillz-player.service << 'EOF'
[Unit]
Description=Skillz Media Player
After=display-manager.service
Wants=display-manager.service

[Service]
Type=simple
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/nvidia/.Xauthority
ExecStart=/usr/bin/python3 ${REMOTE_DIR}/main.py --cms-url http://cms.skillzmedia.com:5002
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF"

ssh "${SSH_TARGET}" "mkdir -p ~/.config/systemd/user && mv /tmp/skillz-player.service ~/.config/systemd/user/"

# Create desktop shortcut
echo "Creating desktop shortcuts..."
ssh "${SSH_TARGET}" "cat > ~/Desktop/skillz-player.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Skillz Media Player
Comment=Start Skillz Media Player
Exec=python3 ${REMOTE_DIR}/main.py
Icon=video-display
Terminal=false
Categories=AudioVideo;Player;
EOF"

ssh "${SSH_TARGET}" "cat > ~/Desktop/reset-pairing.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=Reset Pairing
Comment=Reset device pairing and show pairing screen
Exec=python3 ${REMOTE_DIR}/main.py --reset-pairing
Icon=system-lock-screen
Terminal=false
Categories=System;
EOF"

# Make desktop files executable
ssh "${SSH_TARGET}" "chmod +x ~/Desktop/*.desktop"

# Enable and start service
echo "Enabling systemd service..."
ssh "${SSH_TARGET}" "systemctl --user daemon-reload"
ssh "${SSH_TARGET}" "systemctl --user enable skillz-player.service"
ssh "${SSH_TARGET}" "loginctl enable-linger nvidia"

echo "============================================="
echo "Deployment complete!"
echo ""
echo "To start the player:"
echo "  ssh ${SSH_TARGET} 'systemctl --user start skillz-player'"
echo ""
echo "To reset pairing and test from beginning:"
echo "  ssh ${SSH_TARGET} 'python3 ${REMOTE_DIR}/main.py --reset-pairing'"
echo ""
echo "Or use the CMS to send reset_pairing command"
echo "============================================="
