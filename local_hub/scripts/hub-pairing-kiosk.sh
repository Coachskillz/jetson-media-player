#!/bin/bash
# Hub Pairing Kiosk Script
# This script runs on user login and displays the pairing screen if the Hub is not registered.
# It also monitors for pairing completion and redirects to the dashboard.

HUB_URL="http://localhost:5000"
CHECK_INTERVAL=5

# Set up display environment for Wayland/X11
setup_display() {
    export DISPLAY=:0

    # Find Xauthority for Wayland (mutter) or X11
    if [ -z "$XAUTHORITY" ]; then
        # Try Wayland XWayland auth
        local wayland_auth=$(find /run/user/$(id -u) -name '.mutter-Xwaylandauth.*' 2>/dev/null | head -1)
        if [ -n "$wayland_auth" ]; then
            export XAUTHORITY="$wayland_auth"
        elif [ -f "$HOME/.Xauthority" ]; then
            export XAUTHORITY="$HOME/.Xauthority"
        fi
    fi

    echo "Display: $DISPLAY, Xauthority: $XAUTHORITY"
}

# Wait for the Hub service to be ready
wait_for_hub() {
    echo "Waiting for Hub service..."
    for i in {1..60}; do
        if curl -s "$HUB_URL/health" > /dev/null 2>&1; then
            echo "Hub service is ready"
            return 0
        fi
        sleep 1
    done
    echo "Hub service not available after 60 seconds"
    return 1
}

# Check if Hub is registered
is_registered() {
    local status=$(curl -s "$HUB_URL/api/v1/hub/status" 2>/dev/null)
    if echo "$status" | grep -q '"registered": true'; then
        return 0
    fi
    return 1
}

# Launch browser in kiosk mode
launch_kiosk() {
    local url="$1"

    # Kill any existing kiosk browser
    pkill -f "chromium.*--kiosk" 2>/dev/null
    pkill -f "firefox.*--kiosk" 2>/dev/null

    sleep 1

    # Try chromium first, then firefox
    if command -v chromium-browser &> /dev/null; then
        nohup chromium-browser \
            --kiosk \
            --noerrdialogs \
            --disable-infobars \
            --no-first-run \
            --start-fullscreen \
            --disable-session-crashed-bubble \
            --disable-translate \
            "$url" > /tmp/kiosk-browser.log 2>&1 &
    elif command -v firefox &> /dev/null; then
        nohup firefox --kiosk "$url" > /tmp/kiosk-browser.log 2>&1 &
    else
        echo "No suitable browser found"
        return 1
    fi

    sleep 2
    echo "Browser launched for $url"
}

# Main logic
main() {
    # Set up display environment
    setup_display

    # Wait for Hub service
    if ! wait_for_hub; then
        exit 1
    fi

    # Check if already registered
    if is_registered; then
        echo "Hub is already registered, showing dashboard"
        launch_kiosk "$HUB_URL/"
        exit 0
    fi

    echo "Hub not registered, showing pairing screen"

    # Start pairing if not already active
    curl -s -X POST "$HUB_URL/api/v1/hub/start-pairing" > /dev/null 2>&1

    # Launch pairing screen
    launch_kiosk "$HUB_URL/hub/pairing"

    # Monitor for pairing completion
    while true; do
        sleep $CHECK_INTERVAL

        if is_registered; then
            echo "Hub paired! Redirecting to dashboard..."
            sleep 2
            launch_kiosk "$HUB_URL/"
            exit 0
        fi
    done
}

# Run main function
main
