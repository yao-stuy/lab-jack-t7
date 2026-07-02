#!/bin/sh
# first_run.sh — installs the native LabJack LJM driver (libLabJackM.so) on the
# target machine. viam-server runs this once, the first time the module is
# deployed to a machine (declared via meta.json -> first_run).
#
# The `labjack-ljm` pip package (installed into the venv by setup.sh) is only a
# ctypes wrapper around this native library, so the .so must be present and
# registered with the dynamic linker (ldconfig) or the module can't open the T7.
#
# Best-effort: if your distro/arch isn't covered, install LJM manually from
# https://support.labjack.com/docs/ljm-software-installer-downloads-t4-t7-t8-digit
# and this step becomes a no-op (it detects a loadable install and exits 0).
set -e

# Already loadable by the dynamic linker? Then we're done. (We check the
# ldconfig cache specifically — a stray file that isn't cached wouldn't load.)
if ldconfig -p 2>/dev/null | grep -qi LabJackM; then
    echo "LJM already installed — skipping."
    exit 0
fi

SUDO="sudo"
command -v $SUDO >/dev/null 2>&1 || SUDO=""

# libLabJackM.so links against libusb-1.0; unzip is needed for the installer.
if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get -qq update >/dev/null 2>&1 || true
    $SUDO apt-get -qqy install libusb-1.0-0 unzip >/dev/null 2>&1 || true
fi

ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64)
        URL="https://files.labjack.com/installers/LJM/Linux/x64/release/LabJack-LJM_2025-05-07.zip"
        ;;
    aarch64|arm64)
        URL="https://files.labjack.com/installers/LJM/Linux/AArch64/release/LabJack-LJM_2025-05-07.zip"
        ;;
    *)
        echo "Unsupported arch '$ARCH'. Install LJM manually from labjack.com." >&2
        exit 0
        ;;
esac

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Downloading LJM installer for $ARCH ..."
if ! curl -fsSL "$URL" -o "$TMP/ljm.zip"; then
    echo "LJM download failed. Install manually from labjack.com; then this module will work." >&2
    exit 0
fi

unzip -q "$TMP/ljm.zip" -d "$TMP"
RUN=$(find "$TMP" -name 'labjack_ljm_installer.run' | head -n1)
if [ -z "$RUN" ]; then
    echo "Could not find LJM installer (.run) in the archive." >&2
    exit 0
fi

echo "Running LJM installer ..."
chmod +x "$RUN"
# --without-kipling skips the GUI app (unneeded on a headless machine). Fall back
# to a plain run if the installer rejects the argument.
$SUDO "$RUN" -- --without-kipling || $SUDO "$RUN" || {
    echo "LJM installer returned non-zero; install manually if the module can't open the T7." >&2
    exit 0
}

$SUDO ldconfig 2>/dev/null || true
echo "✓  LJM installed."
