#!/bin/bash
# TuKodi Deploy Script
# Deploys the addon to Kodi at 192.168.1.40 via SSH or creates a zip for manual install

ADDON_DIR="plugin.video.tukodi"
KODI_HOST="${KODI_HOST:-192.168.1.40}"  # override with: KODI_HOST=192.168.x.x ./deploy.sh
KODI_USER="${KODI_USER:-kodi}"          # override with: KODI_USER=root ./deploy.sh
ZIP_NAME="plugin.video.tukodi-1.0.0.zip"

echo "=== TuKodi Deploy ==="

# Build zip package
echo "Building $ZIP_NAME..."
rm -f "$ZIP_NAME"
zip -r "$ZIP_NAME" "$ADDON_DIR" --exclude "*.pyc" --exclude "*/__pycache__/*" --exclude "*.DS_Store"
echo "Created $ZIP_NAME ($(du -sh "$ZIP_NAME" | cut -f1))"

# Try SSH deploy
echo ""
echo "Trying SSH deploy to $KODI_USER@$KODI_HOST..."

KODI_ADDON_PATH=""

# Try common Kodi addon paths
for path in \
    "/home/$KODI_USER/.kodi/addons" \
    "/storage/.kodi/addons" \
    "/var/lib/kodi/.kodi/addons" \
    "/opt/kodi/addons"; do

    if ssh -o ConnectTimeout=5 -o BatchMode=yes "$KODI_USER@$KODI_HOST" "test -d '$path'" 2>/dev/null; then
        KODI_ADDON_PATH="$path"
        break
    fi
done

if [ -n "$KODI_ADDON_PATH" ]; then
    echo "Found Kodi addons at: $KODI_ADDON_PATH"
    echo "Copying addon..."

    # Remove old version
    ssh "$KODI_USER@$KODI_HOST" "rm -rf '$KODI_ADDON_PATH/$ADDON_DIR'"

    # Copy new version
    scp -r "$ADDON_DIR" "$KODI_USER@$KODI_HOST:$KODI_ADDON_PATH/"

    echo "Reloading Kodi addons..."
    # Notify Kodi via JSONRPC to reload addons
    curl -s -X POST \
        "http://$KODI_HOST:8080/jsonrpc" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"plugin.video.tukodi","enabled":false},"id":1}' \
        > /dev/null 2>&1 || true

    sleep 1

    curl -s -X POST \
        "http://$KODI_HOST:8080/jsonrpc" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"plugin.video.tukodi","enabled":true},"id":1}' \
        > /dev/null 2>&1 || true

    echo "Done! Plugin deployed to Kodi at $KODI_HOST"
else
    echo "Could not connect via SSH or find Kodi addons directory."
    echo ""
    echo "=== Manual Install ==="
    echo "1. Copy $ZIP_NAME to a USB stick or make it accessible on the network"
    echo "2. In Kodi: Settings → Add-ons → Install from zip file"
    echo "3. Navigate to $ZIP_NAME and install"
    echo ""
    echo "Or install via Kodi web interface:"
    echo "  curl -s -X POST http://$KODI_HOST:8080/jsonrpc -H 'Content-Type: application/json' \\"
    echo "    -d '{\"jsonrpc\":\"2.0\",\"method\":\"Addons.InstallAddon\",\"params\":{\"addonid\":\"plugin.video.tukodi\"},\"id\":1}'"
fi
