#!/bin/bash
#
# Skillz Media Player Auto-Start Verification Script
#
# This script verifies that the systemd service is properly configured
# for auto-start on boot. Run this on the Jetson device after installation.
#
# Usage: ./verify-autostart.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test counters
PASSED=0
FAILED=0
WARNINGS=0

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED++))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    ((WARNINGS++))
}

log_info() {
    echo -e "[INFO] $1"
}

echo ""
echo "=============================================="
echo "   Skillz Player Auto-Start Verification"
echo "=============================================="
echo ""

# 1. Check if service file exists
log_info "Checking service file..."
if [[ -f /etc/systemd/system/skillz-player.service ]]; then
    log_pass "Service file exists at /etc/systemd/system/skillz-player.service"
else
    log_fail "Service file not found at /etc/systemd/system/skillz-player.service"
    echo "  Run: sudo cp skillz-player.service /etc/systemd/system/"
fi

# 2. Check service is enabled
log_info "Checking if service is enabled..."
if systemctl is-enabled skillz-player &>/dev/null; then
    log_pass "Service is enabled for auto-start"
else
    log_fail "Service is not enabled"
    echo "  Run: sudo systemctl enable skillz-player"
fi

# 3. Check graphical.target dependency
log_info "Checking graphical target configuration..."
if grep -q "After=.*graphical.target" /etc/systemd/system/skillz-player.service 2>/dev/null; then
    log_pass "Service depends on graphical.target"
else
    log_fail "Service missing graphical.target dependency"
fi

if grep -q "WantedBy=graphical.target" /etc/systemd/system/skillz-player.service 2>/dev/null; then
    log_pass "Service wanted by graphical.target"
else
    log_fail "Service not configured for graphical.target"
fi

# 4. Check DISPLAY environment
log_info "Checking display configuration..."
if grep -q "DISPLAY=:0" /etc/systemd/system/skillz-player.service 2>/dev/null; then
    log_pass "DISPLAY=:0 is configured"
else
    log_fail "DISPLAY environment not configured"
fi

# 5. Check XDG desktop autostart (fallback)
log_info "Checking XDG autostart desktop file..."
if [[ -f /etc/xdg/autostart/skillz-player.desktop ]] || [[ -f ~/.config/autostart/skillz-player.desktop ]]; then
    log_pass "XDG autostart desktop file exists"
else
    log_warn "XDG autostart desktop file not found (fallback mechanism)"
fi

# 6. Check if graphical.target is active
log_info "Checking graphical target status..."
if systemctl is-active graphical.target &>/dev/null; then
    log_pass "graphical.target is active"
else
    log_warn "graphical.target is not active (may be normal on headless systems)"
fi

# 7. Check service status
log_info "Checking service status..."
SERVICE_STATUS=$(systemctl is-active skillz-player 2>/dev/null || echo "inactive")
if [[ "$SERVICE_STATUS" == "active" ]]; then
    log_pass "Service is currently running"
elif [[ "$SERVICE_STATUS" == "inactive" ]]; then
    log_warn "Service is not running (start with: sudo systemctl start skillz-player)"
else
    log_fail "Service status: $SERVICE_STATUS"
fi

# 8. Check for restart configuration
log_info "Checking restart configuration..."
if grep -q "Restart=always" /etc/systemd/system/skillz-player.service 2>/dev/null; then
    log_pass "Automatic restart on crash is configured"
else
    log_warn "Restart=always not configured"
fi

# 9. Check user exists
log_info "Checking service user..."
SERVICE_USER=$(grep "^User=" /etc/systemd/system/skillz-player.service 2>/dev/null | cut -d= -f2)
if [[ -n "$SERVICE_USER" ]]; then
    if id "$SERVICE_USER" &>/dev/null; then
        log_pass "Service user '$SERVICE_USER' exists"
    else
        log_fail "Service user '$SERVICE_USER' does not exist"
    fi
else
    log_warn "No User= specified in service file"
fi

# 10. Check working directory exists
log_info "Checking working directory..."
WORK_DIR=$(grep "^WorkingDirectory=" /etc/systemd/system/skillz-player.service 2>/dev/null | cut -d= -f2)
if [[ -n "$WORK_DIR" ]]; then
    if [[ -d "$WORK_DIR" ]]; then
        log_pass "Working directory '$WORK_DIR' exists"
    else
        log_fail "Working directory '$WORK_DIR' does not exist"
    fi
else
    log_warn "No WorkingDirectory= specified in service file"
fi

# Summary
echo ""
echo "=============================================="
echo "   Verification Summary"
echo "=============================================="
echo ""
echo -e "  ${GREEN}Passed:${NC}   $PASSED"
echo -e "  ${YELLOW}Warnings:${NC} $WARNINGS"
echo -e "  ${RED}Failed:${NC}   $FAILED"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}All critical checks passed!${NC}"
    echo ""
    echo "Next Steps for Full Verification:"
    echo "1. Reboot the system: sudo reboot"
    echo "2. Wait 30 seconds after desktop appears"
    echo "3. Verify player is visible on screen"
    echo "4. Check service status: systemctl status skillz-player"
    echo ""
    exit 0
else
    echo -e "${RED}Some checks failed. Please fix the issues above.${NC}"
    echo ""
    exit 1
fi
