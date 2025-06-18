#!/bin/bash

# This command ensures that the script will exit immediately if any command fails.
# It's a safety measure to prevent unexpected behavior.
set -e

echo "--- [startup.sh] Starting custom startup script ---"

# --- Step 1: Install System Dependencies ---
echo "--- [startup.sh] Running apt-get update... ---"
apt-get update

echo "--- [startup.sh] Installing ffmpeg with --no-install-recommends... ---"
# The --no-install-recommends flag is crucial to keep the install small and fast.
apt-get install -y --no-install-recommends ffmpeg

echo "--- [startup.sh] ffmpeg installation finished successfully. ---"

# --- Step 2: Clean up apt cache to reduce image size ---
# This is a good practice for container environments.
echo "--- [startup.sh] Cleaning up apt-get cache... ---"
rm -rf /var/lib/apt/lists/*

# --- Step 3: Start the Application Server ---
echo "--- [startup.sh] All dependencies installed. Starting Gunicorn server... ---"
# The 'exec' command replaces the script process with the Gunicorn process.
# This is the last command that should run.
exec gunicorn --bind=0.0.0.0:$PORT --timeout 600 --workers=1 --log-level=debug --error-logfile=- --access-logfile=- run:app