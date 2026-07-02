#!/bin/sh
# run.sh — module entrypoint. viam-server executes this on the target machine.
# Ensures the venv + Python deps exist (first launch), then runs the module from
# source under the system Python.
#
# We ship SOURCE (not a PyInstaller binary) because the `labjack-ljm` wrapper
# ctypes-loads the native libLabJackM.so driver at runtime, which does not
# survive PyInstaller freezing. Running from source under normal Python loads it
# the same way a manual install does.
cd `dirname $0`

if [ ! -f .installed ]; then
    ./setup.sh
fi

# src/main.py imports `from models.labjack_t7 import ...`; running the script
# from src/ puts that dir on sys.path so the import resolves.
#
# "$@" forwards the socket path that viam-server passes to the entrypoint —
# Module.run_from_registry() requires it as a positional arg, so dropping it
# makes the module exit 2 ("the following arguments are required: socket_path").
exec venv/bin/python src/main.py "$@"
