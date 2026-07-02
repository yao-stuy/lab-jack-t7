#!/bin/sh
# build.sh — package the module SOURCE for the Viam registry (no PyInstaller).
#
# Invoked by `viam module build` / `viam module build start` (meta.json ->
# build.build). Unlike the ADS1115/MCP3008 modules, we do NOT freeze into a
# single binary: the LabJack `labjack-ljm` wrapper ctypes-loads the native
# libLabJackM.so at runtime, which a frozen binary can't reliably find. So we
# ship source and let run.sh build the venv on the target at first launch.
cd `dirname $0`

mkdir -p dist
tar -czvf dist/archive.tar.gz \
    meta.json run.sh setup.sh first_run.sh requirements.txt src

echo "✓  Packaged source into dist/archive.tar.gz"
