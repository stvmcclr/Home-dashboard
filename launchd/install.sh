#!/bin/bash
# install.sh — One-time setup for Home Monitor launchd jobs
# Run from the project root:
#   bash launchd/install.sh

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
LOGS_DIR="$PROJECT_DIR/logs"

echo "Project directory: $PROJECT_DIR"
echo ""

# Create logs dir
mkdir -p "$LOGS_DIR"

# ── Helper: fill in REPLACE_WITH_PROJECT_DIR in a plist ──────────────────
install_plist() {
    local name="$1"
    local src="$PROJECT_DIR/launchd/${name}.plist"
    local dst="$PLIST_DIR/${name}.plist"

    # Unload existing if present
    if launchctl list "$name" &>/dev/null 2>&1; then
        echo "  Unloading existing $name..."
        launchctl unload "$dst" 2>/dev/null || true
    fi

    # Substitute project dir into plist
    sed "s|REPLACE_WITH_PROJECT_DIR|$PROJECT_DIR|g" "$src" > "$dst"
    chmod 644 "$dst"

    # Load it
    launchctl load "$dst"
    echo "  ✓ $name loaded"
}

echo "Installing launchd agents..."
mkdir -p "$PLIST_DIR"
install_plist "com.steve.homeserver"
install_plist "com.steve.homemonitor"

echo ""
echo "✓ Done! Services installed."
echo ""
echo "  Dashboard:  http://localhost:8080/home_dashboard.html"
echo "  Nest polls: every 15 minutes"
echo "  Logs:       $LOGS_DIR/"
echo ""
echo "To check status:"
echo "  launchctl list | grep steve"
echo ""
echo "To stop everything:"
echo "  launchctl unload ~/Library/LaunchAgents/com.steve.homeserver.plist"
echo "  launchctl unload ~/Library/LaunchAgents/com.steve.homemonitor.plist"
echo ""
echo "To restart after changes:"
echo "  bash launchd/install.sh"
