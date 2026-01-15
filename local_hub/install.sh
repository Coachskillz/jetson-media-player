#!/bin/bash
#
# Skillz Hub Installation Script
# Installs the Local Hub Software on Intel NUC or similar small PC
#
# This script:
#   - Installs system dependencies
#   - Creates skillz-hub user and group
#   - Sets up directory structure
#   - Creates Python virtual environment
#   - Installs Python dependencies
#   - Creates configuration template
#   - Installs and enables systemd service
#
# Usage:
#   sudo ./install.sh [OPTIONS]
#
# Options:
#   --network-slug SLUG    Network identifier for HQ registration (required for new installs)
#   --hq-url URL           HQ API URL (default: https://hub.skillzmedia.com)
#   --uninstall            Remove skillz-hub installation
#   --upgrade              Upgrade existing installation
#   --help                 Show this help message
#

set -e

# =============================================================================
# CONFIGURATION
# =============================================================================

# Installation paths
INSTALL_DIR="/opt/skillz-hub"
CONFIG_DIR="/etc/skillz-hub"
STORAGE_DIR="/var/skillz-hub"
LOG_DIR="/var/log/skillz-hub"

# User and group
SERVICE_USER="skillz-hub"
SERVICE_GROUP="skillz-hub"

# Default configuration values
DEFAULT_HQ_URL="https://hub.skillzmedia.com"

# Script directory (where install.sh is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

show_help() {
    cat << EOF
Skillz Hub Installation Script

Usage: sudo ./install.sh [OPTIONS]

Options:
  --network-slug SLUG    Network identifier for HQ registration
                         Required for new installations
  --hq-url URL           HQ API URL (default: $DEFAULT_HQ_URL)
  --uninstall            Remove skillz-hub installation completely
  --upgrade              Upgrade existing installation (preserves config)
  --help                 Show this help message

Examples:
  # Fresh installation
  sudo ./install.sh --network-slug high-octane

  # Installation with custom HQ URL
  sudo ./install.sh --network-slug high-octane --hq-url https://custom-hq.example.com

  # Upgrade existing installation
  sudo ./install.sh --upgrade

  # Uninstall
  sudo ./install.sh --uninstall

EOF
}

# =============================================================================
# SYSTEM DEPENDENCY INSTALLATION
# =============================================================================

install_dependencies() {
    log_info "Installing system dependencies..."

    # Detect package manager
    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        apt-get update -qq
        apt-get install -y -qq python3 python3-venv python3-pip curl
    elif command -v yum &> /dev/null; then
        # RHEL/CentOS
        yum install -y -q python3 python3-pip curl
    elif command -v dnf &> /dev/null; then
        # Fedora
        dnf install -y -q python3 python3-pip curl
    elif command -v pacman &> /dev/null; then
        # Arch Linux
        pacman -Sy --noconfirm python python-pip curl
    else
        log_warning "Could not detect package manager. Please ensure Python 3.9+ and pip are installed."
    fi

    # Verify Python version
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)

    if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
        log_error "Python 3.9 or higher is required. Found: Python $PYTHON_VERSION"
        exit 1
    fi

    log_success "System dependencies installed (Python $PYTHON_VERSION)"
}

# =============================================================================
# USER AND GROUP SETUP
# =============================================================================

create_service_user() {
    log_info "Creating service user and group..."

    # Create group if it doesn't exist
    if ! getent group "$SERVICE_GROUP" > /dev/null 2>&1; then
        groupadd --system "$SERVICE_GROUP"
        log_success "Created group: $SERVICE_GROUP"
    else
        log_info "Group $SERVICE_GROUP already exists"
    fi

    # Create user if it doesn't exist
    if ! id "$SERVICE_USER" > /dev/null 2>&1; then
        useradd --system \
            --gid "$SERVICE_GROUP" \
            --home-dir "$INSTALL_DIR" \
            --shell /usr/sbin/nologin \
            --comment "Skillz Hub Service" \
            "$SERVICE_USER"
        log_success "Created user: $SERVICE_USER"
    else
        log_info "User $SERVICE_USER already exists"
    fi
}

# =============================================================================
# DIRECTORY STRUCTURE
# =============================================================================

create_directories() {
    log_info "Creating directory structure..."

    # Installation directory
    mkdir -p "$INSTALL_DIR"

    # Configuration directory
    mkdir -p "$CONFIG_DIR"

    # Storage directories
    mkdir -p "$STORAGE_DIR"
    mkdir -p "$STORAGE_DIR/storage/content"
    mkdir -p "$STORAGE_DIR/storage/databases"

    # Log directory
    mkdir -p "$LOG_DIR"

    log_success "Directories created"
}

set_permissions() {
    log_info "Setting permissions..."

    # Installation directory - owned by root, readable by service user
    chown -R root:$SERVICE_GROUP "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"

    # Configuration directory - owned by root, readable by service user
    chown -R root:$SERVICE_GROUP "$CONFIG_DIR"
    chmod 750 "$CONFIG_DIR"

    # Config file should be readable by service user
    if [ -f "$CONFIG_DIR/config.json" ]; then
        chmod 640 "$CONFIG_DIR/config.json"
    fi

    # Storage directory - owned by service user for write access
    chown -R $SERVICE_USER:$SERVICE_GROUP "$STORAGE_DIR"
    chmod -R 750 "$STORAGE_DIR"

    # Log directory - owned by service user for write access
    chown -R $SERVICE_USER:$SERVICE_GROUP "$LOG_DIR"
    chmod -R 750 "$LOG_DIR"

    # Virtual environment needs to be accessible
    if [ -d "$INSTALL_DIR/venv" ]; then
        chmod -R 755 "$INSTALL_DIR/venv"
    fi

    log_success "Permissions set"
}

# =============================================================================
# APPLICATION INSTALLATION
# =============================================================================

copy_application_files() {
    log_info "Copying application files..."

    # Copy all Python files and directories
    cp -r "$SCRIPT_DIR"/*.py "$INSTALL_DIR/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR"/models "$INSTALL_DIR/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR"/routes "$INSTALL_DIR/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR"/services "$INSTALL_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/requirements.txt "$INSTALL_DIR/" 2>/dev/null || true

    log_success "Application files copied to $INSTALL_DIR"
}

create_virtual_environment() {
    log_info "Creating Python virtual environment..."

    # Create venv if it doesn't exist
    if [ ! -d "$INSTALL_DIR/venv" ]; then
        python3 -m venv "$INSTALL_DIR/venv"
        log_success "Virtual environment created"
    else
        log_info "Virtual environment already exists"
    fi

    # Upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip --quiet

    log_success "Virtual environment ready"
}

install_python_dependencies() {
    log_info "Installing Python dependencies..."

    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet
        log_success "Python dependencies installed"
    else
        log_warning "requirements.txt not found, skipping dependency installation"
    fi
}

# =============================================================================
# CONFIGURATION
# =============================================================================

create_config_template() {
    local network_slug="$1"
    local hq_url="$2"

    log_info "Creating configuration file..."

    # Don't overwrite existing config
    if [ -f "$CONFIG_DIR/config.json" ]; then
        log_warning "Configuration file already exists at $CONFIG_DIR/config.json"
        log_info "To update configuration, edit the file manually or remove it and re-run install"
        return
    fi

    # Check if network_slug is provided
    if [ -z "$network_slug" ]; then
        log_error "Network slug is required for new installations"
        log_error "Use: sudo ./install.sh --network-slug YOUR_NETWORK_SLUG"
        exit 1
    fi

    # Use default HQ URL if not provided
    if [ -z "$hq_url" ]; then
        hq_url="$DEFAULT_HQ_URL"
    fi

    # Create configuration file
    cat > "$CONFIG_DIR/config.json" << EOF
{
  "hq_url": "$hq_url",
  "network_slug": "$network_slug",
  "sync_interval_minutes": 5,
  "heartbeat_interval_seconds": 60,
  "alert_retry_interval_seconds": 30,
  "storage_path": "$STORAGE_DIR",
  "log_path": "$LOG_DIR",
  "port": 5000
}
EOF

    # Set proper permissions
    chown root:$SERVICE_GROUP "$CONFIG_DIR/config.json"
    chmod 640 "$CONFIG_DIR/config.json"

    log_success "Configuration file created at $CONFIG_DIR/config.json"
}

# =============================================================================
# SYSTEMD SERVICE
# =============================================================================

install_systemd_service() {
    log_info "Installing systemd service..."

    # Copy service file
    if [ -f "$SCRIPT_DIR/skillz-hub.service" ]; then
        cp "$SCRIPT_DIR/skillz-hub.service" /etc/systemd/system/skillz-hub.service
    else
        # Create service file if not present
        cat > /etc/systemd/system/skillz-hub.service << 'EOF'
[Unit]
Description=Skillz Hub - Local Media Distribution Service
Documentation=https://github.com/skillzmedia/jetson-media-player
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=notify
User=skillz-hub
Group=skillz-hub

# Working directory where the application lives
WorkingDirectory=/opt/skillz-hub

# Python virtual environment and Gunicorn
Environment="PATH=/opt/skillz-hub/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"

# Gunicorn production server
ExecStart=/opt/skillz-hub/venv/bin/gunicorn \
    --workers 4 \
    --bind 0.0.0.0:5000 \
    --access-logfile /var/log/skillz-hub/access.log \
    --error-logfile /var/log/skillz-hub/error.log \
    --capture-output \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    'app:create_app()'

# Reload command for graceful restart
ExecReload=/bin/kill -s HUP $MAINPID

# Restart on failure - hub is critical for store operation
Restart=always
RestartSec=5

# Stop timeout - allow graceful shutdown
TimeoutStopSec=30

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

# Read-write paths for data and logs
ReadWritePaths=/var/skillz-hub
ReadWritePaths=/var/log/skillz-hub

# Read-only paths for configuration
ReadOnlyPaths=/etc/skillz-hub

# Limit resources to prevent runaway processes
LimitNOFILE=65536
LimitNPROC=4096

# Standard output and error to journal
StandardOutput=journal
StandardError=journal
SyslogIdentifier=skillz-hub

[Install]
WantedBy=multi-user.target
EOF
    fi

    # Reload systemd daemon
    systemctl daemon-reload

    # Enable service to start on boot
    systemctl enable skillz-hub.service

    log_success "Systemd service installed and enabled"
}

start_service() {
    log_info "Starting skillz-hub service..."

    systemctl start skillz-hub.service

    # Wait a moment for service to start
    sleep 2

    # Check if service is running
    if systemctl is-active --quiet skillz-hub.service; then
        log_success "Service started successfully"
    else
        log_error "Service failed to start. Check logs with: journalctl -u skillz-hub -n 50"
        exit 1
    fi
}

# =============================================================================
# UNINSTALL
# =============================================================================

uninstall() {
    log_info "Uninstalling Skillz Hub..."

    # Stop and disable service
    if systemctl is-active --quiet skillz-hub.service 2>/dev/null; then
        log_info "Stopping service..."
        systemctl stop skillz-hub.service
    fi

    if systemctl is-enabled --quiet skillz-hub.service 2>/dev/null; then
        log_info "Disabling service..."
        systemctl disable skillz-hub.service
    fi

    # Remove service file
    if [ -f /etc/systemd/system/skillz-hub.service ]; then
        rm /etc/systemd/system/skillz-hub.service
        systemctl daemon-reload
        log_success "Service file removed"
    fi

    # Remove installation directory
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
        log_success "Installation directory removed"
    fi

    # Ask about config and data
    echo ""
    read -p "Remove configuration files in $CONFIG_DIR? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$CONFIG_DIR"
        log_success "Configuration directory removed"
    fi

    read -p "Remove data files in $STORAGE_DIR? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$STORAGE_DIR"
        log_success "Storage directory removed"
    fi

    read -p "Remove log files in $LOG_DIR? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$LOG_DIR"
        log_success "Log directory removed"
    fi

    # Remove user (optional)
    read -p "Remove service user '$SERVICE_USER'? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if id "$SERVICE_USER" > /dev/null 2>&1; then
            userdel "$SERVICE_USER"
            log_success "User removed"
        fi
        if getent group "$SERVICE_GROUP" > /dev/null 2>&1; then
            groupdel "$SERVICE_GROUP"
            log_success "Group removed"
        fi
    fi

    log_success "Skillz Hub uninstalled"
}

# =============================================================================
# UPGRADE
# =============================================================================

upgrade() {
    log_info "Upgrading Skillz Hub..."

    # Check if already installed
    if [ ! -d "$INSTALL_DIR" ]; then
        log_error "Skillz Hub is not installed. Use install without --upgrade flag."
        exit 1
    fi

    # Stop service if running
    if systemctl is-active --quiet skillz-hub.service 2>/dev/null; then
        log_info "Stopping service for upgrade..."
        systemctl stop skillz-hub.service
    fi

    # Backup current installation (except venv)
    BACKUP_DIR="/tmp/skillz-hub-backup-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    cp -r "$INSTALL_DIR"/*.py "$BACKUP_DIR/" 2>/dev/null || true
    cp -r "$INSTALL_DIR"/models "$BACKUP_DIR/" 2>/dev/null || true
    cp -r "$INSTALL_DIR"/routes "$BACKUP_DIR/" 2>/dev/null || true
    cp -r "$INSTALL_DIR"/services "$BACKUP_DIR/" 2>/dev/null || true
    log_info "Backup created at $BACKUP_DIR"

    # Copy new files
    copy_application_files

    # Update dependencies
    install_python_dependencies

    # Update service file if needed
    if [ -f "$SCRIPT_DIR/skillz-hub.service" ]; then
        cp "$SCRIPT_DIR/skillz-hub.service" /etc/systemd/system/skillz-hub.service
        systemctl daemon-reload
    fi

    # Set permissions
    set_permissions

    # Start service
    start_service

    log_success "Upgrade complete!"
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    local network_slug=""
    local hq_url=""
    local do_uninstall=false
    local do_upgrade=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --network-slug)
                network_slug="$2"
                shift 2
                ;;
            --hq-url)
                hq_url="$2"
                shift 2
                ;;
            --uninstall)
                do_uninstall=true
                shift
                ;;
            --upgrade)
                do_upgrade=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    # Check root
    check_root

    echo ""
    echo "========================================"
    echo "  Skillz Hub Installation"
    echo "========================================"
    echo ""

    # Handle uninstall
    if [ "$do_uninstall" = true ]; then
        uninstall
        exit 0
    fi

    # Handle upgrade
    if [ "$do_upgrade" = true ]; then
        upgrade
        exit 0
    fi

    # Fresh installation
    log_info "Starting fresh installation..."

    # Installation steps
    install_dependencies
    create_service_user
    create_directories
    copy_application_files
    create_virtual_environment
    install_python_dependencies
    create_config_template "$network_slug" "$hq_url"
    set_permissions
    install_systemd_service
    start_service

    echo ""
    echo "========================================"
    echo "  Installation Complete!"
    echo "========================================"
    echo ""
    echo "Service Status:"
    systemctl status skillz-hub.service --no-pager -l || true
    echo ""
    echo "Useful Commands:"
    echo "  View logs:       journalctl -u skillz-hub -f"
    echo "  Service status:  systemctl status skillz-hub"
    echo "  Restart service: systemctl restart skillz-hub"
    echo "  Stop service:    systemctl stop skillz-hub"
    echo ""
    echo "Configuration file: $CONFIG_DIR/config.json"
    echo "Log files:          $LOG_DIR/"
    echo "Data storage:       $STORAGE_DIR/"
    echo ""
    echo "API Endpoint: http://localhost:5000"
    echo ""
}

# Run main
main "$@"
