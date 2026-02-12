#!/bin/bash
# Install Hub Kiosk Mode
# Run this script on the Hub to set up automatic pairing screen display

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HUB_DIR="/home/skillz/skillz-hub"
AUTOSTART_DIR="/home/skillz/.config/autostart"

echo "=== Skillz Hub Kiosk Installation ==="

# Create scripts directory
echo "Creating scripts directory..."
mkdir -p "$HUB_DIR/scripts"

# Copy kiosk script
echo "Installing kiosk script..."
cp "$SCRIPT_DIR/hub-pairing-kiosk.sh" "$HUB_DIR/scripts/"
chmod +x "$HUB_DIR/scripts/hub-pairing-kiosk.sh"

# Create autostart directory if it doesn't exist
echo "Setting up autostart..."
mkdir -p "$AUTOSTART_DIR"

# Install autostart entry
cp "$SCRIPT_DIR/skillz-hub-kiosk.desktop" "$AUTOSTART_DIR/"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "The Hub will now automatically:"
echo "  1. Check if registered with CMS on login"
echo "  2. If NOT registered: Show pairing screen with code"
echo "  3. If registered: Show the Hub dashboard"
echo ""
echo "To test, either:"
echo "  - Log out and log back in"
echo "  - Run: $HUB_DIR/scripts/hub-pairing-kiosk.sh"
echo ""
