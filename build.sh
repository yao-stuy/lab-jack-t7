#!/bin/sh
# build.sh — compile the module into a single self-contained binary (dist/main)
# and package it as dist/archive.tar.gz for upload to the Viam registry.
#
# Invoked automatically by `viam module build`, `viam module reload`, and the
# cloud build-action (meta.json -> build.build). It produces a binary that needs
# no Python/venv on the target machine.
#
# NOTE: the binary bundles the `labjack` Python wrapper, but NOT the native LJM
# library (libLabJackM.so) — that is a system driver installed by first_run.sh.
cd `dirname $0`

VENV_NAME="venv"
PYTHON="$VENV_NAME/bin/python"

# Make sure dependencies exist even when build.sh is run on its own.
if [ ! -x "$PYTHON" ]; then
    ./setup.sh
fi

# PyInstaller turns src/main.py (and everything it imports, including
# src/models/labjack_t7.py) into one binary at dist/main.
if ! $PYTHON -m pip install pyinstaller -Uqq; then
    exit 1
fi

$PYTHON -m PyInstaller --onefile --hidden-import="labjack.ljm" src/main.py

TAR_FILES="meta.json ./dist/main"
FIRST_RUN=$($PYTHON -c "import json; print(json.load(open('meta.json')).get('first_run', ''))" 2>/dev/null)
if [ -n "$FIRST_RUN" ] && [ -f "$FIRST_RUN" ]; then
    TAR_FILES="$TAR_FILES $FIRST_RUN"
fi
tar -czvf dist/archive.tar.gz $TAR_FILES

echo "✓  Built dist/main and packaged dist/archive.tar.gz"
