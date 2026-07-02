#!/bin/sh
# first_run.sh — installs the native LabJack LJM driver (libLabJackM.so) on the
# target machine. viam-server runs this once, the first time the module is
# deployed to a machine (declared via meta.json -> first_run).
#
# The `labjack-ljm` pip package (bundled into dist/main) is only a ctypes wrapper
# around this native library, so the .so must be present on the host or the
# module fails to open the T7.
#
# This is best-effort: if the download URL or your distro isn't covered, install
# LJM manually from https://labjack.com/support/software/installers/ljm and this
# step becomes a no-op (it detects an existing install and exits 0).
set -e

# Already installed? Nothing to do.
if [ -e /usr/local/lib/libLabJackM.so ] || ldconfig -p 2>/dev/null | grep -q LabJackM; then
    echo "LJM already installed — skipping."
    exit 0
fi

SUDO="sudo"
command -v $SUDO >/dev/null 2>&1 || SUDO=""

ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64)
        URL="https://files.labjack.com/installers/LJM/Linux/x64/release/labjack_ljm_software_2020_03_30_x86_64.tar.gz"
        ;;
    aarch64|arm64)
        URL="https://files.labjack.com/installers/LJM/Linux/aarch64/release/labjack_ljm_software_2020_03_30_aarch64.tar.gz"
        ;;
    armv7l|armv6l|arm*)
        URL="https://files.labjack.com/installers/LJM/Linux/arm32/release/labjack_ljm_software_2020_03_30_arm32.tar.gz"
        ;;
    *)
        echo "Unsupported arch '$ARCH'. Install LJM manually from labjack.com." >&2
        exit 0
        ;;
esac

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Downloading LJM installer for $ARCH ..."
if ! curl -fsSL "$URL" -o "$TMP/ljm.tar.gz"; then
    echo "LJM download failed. Install manually from labjack.com; then this module will work." >&2
    exit 0
fi

tar -xzf "$TMP/ljm.tar.gz" -C "$TMP"
INSTALLER=$(find "$TMP" -name 'labjack_ljm_installer.run' -o -name 'labjack_ljm_installer*.run' | head -n1)
if [ -z "$INSTALLER" ]; then
    echo "Could not find LJM installer script in archive." >&2
    exit 0
fi

echo "Running LJM installer ..."
chmod +x "$INSTALLER"
$SUDO "$INSTALLER" -- --no-restart-device-rules || {
    echo "LJM installer returned non-zero; install manually if the module can't open the T7." >&2
    exit 0
}

$SUDO ldconfig 2>/dev/null || true
echo "✓  LJM installed."
