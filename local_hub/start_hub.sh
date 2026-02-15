#!/bin/bash
# =============================================================================
# Skillz Hub Startup Script
# =============================================================================
# This script properly starts the Hub with:
# 1. Cloudflare quick tunnel (auto-registers URL with CMS)
# 2. Flask Hub application on port 5000
#
# Usage: ./start_hub.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
HUB_PORT=5000
TUNNEL_LOG="/tmp/cloudflared.log"
HUB_LOG="/tmp/hub.log"
TUNNEL_URL_FILE="/tmp/tunnel_url.txt"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[HUB]${NC} $1"; }
warn() { echo -e "${YELLOW}[HUB]${NC} $1"; }
error() { echo -e "${RED}[HUB]${NC} $1"; }

# ---- Step 0: Kill any existing processes ----
log "Cleaning up old processes..."
pkill -f "cloudflared tunnel" 2>/dev/null || true
pkill -f "python.*app" 2>/dev/null || true
fuser -k $HUB_PORT/tcp 2>/dev/null || true
sleep 2

# ---- Step 1: Start Cloudflare quick tunnel ----
log "Starting Cloudflare tunnel..."
cloudflared tunnel --url http://localhost:$HUB_PORT > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

# Wait for tunnel URL to appear in logs (max 30 seconds)
TUNNEL_URL=""
for i in $(seq 1 30); do
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$TUNNEL_URL" ]; then
    error "Failed to get tunnel URL after 30 seconds"
    cat "$TUNNEL_LOG"
    exit 1
fi

echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"
log "Tunnel URL: $TUNNEL_URL"

# ---- Step 2: Register tunnel URL with CMS ----
# Read hub_id from the database
HUB_ID=$(sqlite3 storage/hub.db "SELECT hub_id FROM hub_config LIMIT 1;" 2>/dev/null)
HUB_TOKEN=$(sqlite3 storage/hub.db "SELECT hub_token FROM hub_config LIMIT 1;" 2>/dev/null)

# Read CMS URL from config
CMS_URL=$(python3 -c "import json; print(json.load(open('config.json'))['cms_url'])" 2>/dev/null)

if [ -n "$HUB_ID" ] && [ -n "$CMS_URL" ]; then
    log "Registering tunnel URL with CMS..."
    log "  Hub ID: $HUB_ID"
    log "  CMS: $CMS_URL"

    REGISTER_RESULT=$(curl -s -X POST \
        "$CMS_URL/api/v1/hubs/heartbeat" \
        -H "Content-Type: application/json" \
        -d "{\"hub_id\": \"$HUB_ID\", \"api_token\": \"$HUB_TOKEN\", \"tunnel_url\": \"$TUNNEL_URL\"}" \
        --max-time 10 2>/dev/null)

    if echo "$REGISTER_RESULT" | grep -q "success"; then
        log "Tunnel URL registered with CMS ✓"
    else
        warn "CMS registration response: $REGISTER_RESULT"
    fi
else
    warn "Hub not paired yet (no hub_id). Tunnel URL will need manual registration."
    warn "Hub ID: $HUB_ID"
    warn "CMS URL: $CMS_URL"
fi

# ---- Step 3: Start Hub Flask application ----
log "Starting Hub Flask application on port $HUB_PORT..."
source venv/bin/activate 2>/dev/null || true
python app.py > "$HUB_LOG" 2>&1 &
HUB_PID=$!

# Wait for Flask to start
for i in $(seq 1 10); do
    if curl -s http://localhost:$HUB_PORT/ > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if curl -s http://localhost:$HUB_PORT/ > /dev/null 2>&1; then
    log "Hub started successfully ✓"
else
    error "Hub failed to start. Check $HUB_LOG"
    cat "$HUB_LOG" | tail -20
    exit 1
fi

# ---- Summary ----
echo ""
echo "============================================"
echo "  Skillz Hub Running"
echo "============================================"
echo "  Hub:     http://localhost:$HUB_PORT"
echo "  Tunnel:  $TUNNEL_URL"
echo "  Hub PID: $HUB_PID"
echo "  Tunnel PID: $TUNNEL_PID"
echo "============================================"
echo ""
log "Hub is ready. Press Ctrl+C to stop."

# ---- Keep running and handle shutdown ----
cleanup() {
    log "Shutting down..."
    kill $HUB_PID 2>/dev/null
    kill $TUNNEL_PID 2>/dev/null
    wait
    log "Done."
}
trap cleanup EXIT INT TERM

# Follow Hub logs
tail -f "$HUB_LOG"
