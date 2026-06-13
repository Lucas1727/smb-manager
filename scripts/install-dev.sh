#!/usr/bin/env bash
# Developer install: wires the daemon, polkit policy and D-Bus files into the
# system so you can run the real app locally. Re-run after editing daemon code.
#
# Usage:  ./install-dev.sh           # install
#         ./install-dev.sh uninstall # remove
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"

DAEMON_LAUNCHER=/usr/libexec/smb-manager-daemon
DBUS_SERVICE=/usr/share/dbus-1/system-services/org.smbmanager.Manager.service
DBUS_CONF=/usr/share/dbus-1/system.d/org.smbmanager.Manager.conf
POLKIT=/usr/share/polkit-1/actions/org.smbmanager.policy

if [[ "${1:-}" == "uninstall" ]]; then
    sudo rm -f "$DAEMON_LAUNCHER" "$DBUS_SERVICE" "$DBUS_CONF" "$POLKIT"
    sudo systemctl reload dbus 2>/dev/null || true
    echo "Removed system integration files."
    exit 0
fi

if [[ $EUID -eq 0 ]]; then
    echo "Run as your normal user; the script will sudo where needed." >&2
    exit 1
fi

# A launcher that runs the daemon from this checkout (no reinstall on edits).
sudo tee "$DAEMON_LAUNCHER" >/dev/null <<EOF
#!/usr/bin/env bash
exec env PYTHONPATH="$REPO/src" "$PY" -m smbmanager.daemon "\$@"
EOF
sudo chmod 0755 "$DAEMON_LAUNCHER"

sudo install -Dm644 "$REPO/data/org.smbmanager.Manager.service" "$DBUS_SERVICE"
sudo install -Dm644 "$REPO/data/org.smbmanager.Manager.conf" "$DBUS_CONF"
sudo install -Dm644 "$REPO/data/org.smbmanager.policy" "$POLKIT"

sudo systemctl reload dbus 2>/dev/null || true

echo "Installed. Run the UI with:"
echo "    PYTHONPATH=$REPO/src python3 -m smbmanager.app"
