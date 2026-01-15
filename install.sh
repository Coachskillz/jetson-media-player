#!/bin/bash
#
# Skillz Media Player Installation Script
#
# This script installs the Skillz Media Player on Jetson Orin Nano devices.
# It handles system dependencies, Python packages, directory structure,
# config templates, and systemd service setup.
#
# Usage: sudo ./install.sh
#
# Target: Jetson Orin Nano with JetPack 5.x or later
#

set -e  # Exit on any error

# Constants
INSTALL_DIR="/home/skillz"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="skillz-player"
SKILLZ_USER="skillz"
SKILLZ_GROUP="skillz"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if script is run as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# Check if running on Jetson platform
check_jetson() {
    if [[ -f /etc/nv_tegra_release ]]; then
        log_info "Detected NVIDIA Jetson platform"
        cat /etc/nv_tegra_release
    else
        log_warn "Not running on Jetson platform - some features may not work"
        log_warn "NVIDIA hardware acceleration requires Jetson Orin Nano"
    fi
}

# Install system dependencies
install_system_deps() {
    log_info "Installing system dependencies..."

    apt-get update

    # GStreamer core and plugins
    apt-get install -y \
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-libav

    # Python GObject bindings (DO NOT use pip for this)
    apt-get install -y \
        python3-gi \
        gir1.2-gstreamer-1.0 \
        gir1.2-gst-plugins-base-1.0

    # Additional Python tools
    apt-get install -y \
        python3-pip \
        python3-venv

    # ZeroMQ system library
    apt-get install -y libzmq3-dev

    log_info "System dependencies installed successfully"
}

# Create skillz user if not exists
create_user() {
    if id "${SKILLZ_USER}" &>/dev/null; then
        log_info "User ${SKILLZ_USER} already exists"
    else
        log_info "Creating user ${SKILLZ_USER}..."
        useradd -m -s /bin/bash -G video,audio "${SKILLZ_USER}"
        log_info "User ${SKILLZ_USER} created"
    fi

    # Ensure user is in required groups for display access
    usermod -a -G video,audio "${SKILLZ_USER}" 2>/dev/null || true
}

# Create required directories
create_directories() {
    log_info "Creating directory structure..."

    # Main directories
    mkdir -p "${INSTALL_DIR}/config"
    mkdir -p "${INSTALL_DIR}/media"
    mkdir -p "${INSTALL_DIR}/logs"
    mkdir -p "${INSTALL_DIR}/databases"
    mkdir -p "${INSTALL_DIR}/src/player"

    log_info "Directories created at ${INSTALL_DIR}"
}

# Install Python dependencies
install_python_deps() {
    log_info "Installing Python dependencies..."

    # Install from requirements.txt
    # Note: PyGObject (gi) must be installed via apt, not pip
    if [[ -f "${SCRIPT_DIR}/requirements.txt" ]]; then
        pip3 install --upgrade pip
        pip3 install -r "${SCRIPT_DIR}/requirements.txt"
    else
        # Fallback to manual installation
        pip3 install --upgrade pip
        pip3 install pyzmq>=25.0 requests>=2.31.0 PyYAML>=6.0
    fi

    log_info "Python dependencies installed"
}

# Copy source files
copy_source_files() {
    log_info "Copying source files..."

    # Copy entire src/player directory
    if [[ -d "${SCRIPT_DIR}/src/player" ]]; then
        cp -r "${SCRIPT_DIR}/src/player" "${INSTALL_DIR}/src/"
    else
        log_error "Source directory ${SCRIPT_DIR}/src/player not found"
        exit 1
    fi

    # Copy common modules if they exist
    if [[ -d "${SCRIPT_DIR}/src/common" ]]; then
        cp -r "${SCRIPT_DIR}/src/common" "${INSTALL_DIR}/src/"
    fi

    # Copy src __init__.py if it exists
    if [[ -f "${SCRIPT_DIR}/src/__init__.py" ]]; then
        cp "${SCRIPT_DIR}/src/__init__.py" "${INSTALL_DIR}/src/"
    fi

    log_info "Source files copied to ${INSTALL_DIR}/src/"
}

# Copy config templates
copy_config_templates() {
    log_info "Copying config templates..."

    # Copy templates to config directory (without .template extension)
    for template in "${SCRIPT_DIR}/config"/*.template; do
        if [[ -f "$template" ]]; then
            filename=$(basename "$template" .template)
            target="${INSTALL_DIR}/config/${filename}"

            if [[ -f "$target" ]]; then
                log_warn "Config file ${target} exists, skipping (not overwriting)"
            else
                cp "$template" "$target"
                log_info "Created ${target}"
            fi
        fi
    done

    log_info "Config templates processed"
}

# Set proper file permissions
set_permissions() {
    log_info "Setting file permissions..."

    # Own everything by skillz user
    chown -R "${SKILLZ_USER}:${SKILLZ_GROUP}" "${INSTALL_DIR}"

    # Source files readable by all, writable by owner
    find "${INSTALL_DIR}/src" -type f -name "*.py" -exec chmod 644 {} \;
    find "${INSTALL_DIR}/src" -type d -exec chmod 755 {} \;

    # Config directory needs write access for sync service
    chmod 755 "${INSTALL_DIR}/config"
    find "${INSTALL_DIR}/config" -type f -exec chmod 644 {} \;

    # Media directory for downloaded content
    chmod 755 "${INSTALL_DIR}/media"

    # Logs directory for application logs
    chmod 755 "${INSTALL_DIR}/logs"

    # Databases directory for FAISS files
    chmod 755 "${INSTALL_DIR}/databases"

    # Make player.py executable
    chmod +x "${INSTALL_DIR}/src/player/player.py"

    log_info "Permissions set"
}

# Install systemd service
install_service() {
    log_info "Installing systemd service..."

    # Copy service file
    if [[ -f "${SCRIPT_DIR}/skillz-player.service" ]]; then
        cp "${SCRIPT_DIR}/skillz-player.service" /etc/systemd/system/
        chmod 644 /etc/systemd/system/skillz-player.service
    else
        log_error "Service file ${SCRIPT_DIR}/skillz-player.service not found"
        exit 1
    fi

    # Reload systemd
    systemctl daemon-reload

    # Enable service for auto-start on boot
    systemctl enable "${SERVICE_NAME}"

    log_info "Service ${SERVICE_NAME} installed and enabled"
}

# Verify GStreamer plugins
verify_gstreamer() {
    log_info "Verifying GStreamer installation..."

    # Check for NVIDIA plugins (only meaningful on Jetson)
    if command -v gst-inspect-1.0 &>/dev/null; then
        if gst-inspect-1.0 nv3dsink &>/dev/null; then
            log_info "NVIDIA nv3dsink plugin: Available"
        else
            log_warn "NVIDIA nv3dsink plugin: Not available (requires Jetson hardware)"
        fi

        if gst-inspect-1.0 nvv4l2decoder &>/dev/null; then
            log_info "NVIDIA nvv4l2decoder plugin: Available"
        else
            log_warn "NVIDIA nvv4l2decoder plugin: Not available (requires Jetson hardware)"
        fi

        # Check standard plugins
        if gst-inspect-1.0 playbin3 &>/dev/null; then
            log_info "GStreamer playbin3: Available"
        else
            log_error "GStreamer playbin3: Not available (required)"
        fi
    else
        log_error "gst-inspect-1.0 not found - GStreamer may not be installed correctly"
    fi
}

# Verify Python modules
verify_python() {
    log_info "Verifying Python modules..."

    # Check for PyGObject
    if python3 -c "import gi" 2>/dev/null; then
        log_info "PyGObject (gi): Available"
    else
        log_error "PyGObject (gi): Not available - run: apt install python3-gi"
        return 1
    fi

    # Check for GStreamer bindings
    if python3 -c "import gi; gi.require_version('Gst', '1.0'); from gi.repository import Gst" 2>/dev/null; then
        log_info "GStreamer Python bindings: Available"
    else
        log_warn "GStreamer Python bindings: Not fully available"
    fi

    # Check for pyzmq
    if python3 -c "import zmq" 2>/dev/null; then
        log_info "pyzmq: Available"
    else
        log_error "pyzmq: Not available - run: pip3 install pyzmq"
        return 1
    fi

    # Check for requests
    if python3 -c "import requests" 2>/dev/null; then
        log_info "requests: Available"
    else
        log_error "requests: Not available - run: pip3 install requests"
        return 1
    fi
}

# Print post-installation instructions
print_instructions() {
    echo ""
    echo "=============================================="
    echo "   Installation Complete!"
    echo "=============================================="
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Configure the player by editing config files:"
    echo "   - ${INSTALL_DIR}/config/device.json"
    echo "   - ${INSTALL_DIR}/config/playlist.json"
    echo "   - ${INSTALL_DIR}/config/settings.json"
    echo ""
    echo "2. Add media files to:"
    echo "   ${INSTALL_DIR}/media/"
    echo ""
    echo "3. Start the service:"
    echo "   sudo systemctl start ${SERVICE_NAME}"
    echo ""
    echo "4. Check service status:"
    echo "   sudo systemctl status ${SERVICE_NAME}"
    echo ""
    echo "5. View logs:"
    echo "   sudo journalctl -u ${SERVICE_NAME} -f"
    echo ""
    echo "6. Stop the service:"
    echo "   sudo systemctl stop ${SERVICE_NAME}"
    echo ""
}

# Uninstall function
uninstall() {
    log_info "Uninstalling Skillz Media Player..."

    # Stop and disable service
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true

    # Remove service file
    rm -f /etc/systemd/system/skillz-player.service
    systemctl daemon-reload

    # Optionally remove install directory (ask user)
    read -p "Remove ${INSTALL_DIR}? This will delete all data! (y/N): " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -rf "${INSTALL_DIR}"
        log_info "Removed ${INSTALL_DIR}"
    else
        log_info "Keeping ${INSTALL_DIR}"
    fi

    log_info "Uninstall complete"
}

# Main installation function
main() {
    echo ""
    echo "=============================================="
    echo "   Skillz Media Player Installer"
    echo "=============================================="
    echo ""

    # Check for uninstall flag
    if [[ "$1" == "--uninstall" ]]; then
        check_root
        uninstall
        exit 0
    fi

    # Check for verify flag
    if [[ "$1" == "--verify" ]]; then
        verify_gstreamer
        verify_python
        exit 0
    fi

    # Full installation
    check_root
    check_jetson

    log_info "Starting installation..."

    install_system_deps
    create_user
    create_directories
    install_python_deps
    copy_source_files
    copy_config_templates
    set_permissions
    install_service

    log_info "Running verification..."
    verify_gstreamer
    verify_python || log_warn "Some Python modules missing - check logs above"

    print_instructions
}

# Run main function
main "$@"
