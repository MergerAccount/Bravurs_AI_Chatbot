#!/bin/bash

# Install custom packages
echo "--- [startup.sh] Running apt-get update ---"
apt-get update
echo "--- [startup.sh] Installing ffmpeg ---"
apt-get install -y ffmpeg
echo "--- [startup.sh] ffmpeg installation finished ---"

# Start the Gunicorn server
echo "--- [startup.sh] Starting Gunicorn server ---"

exec gunicorn --bind=0.0.0.0:$PORT --timeout 600 --workers=1 --log-level=debug --error-logfile=- --access-logfile=- run:app