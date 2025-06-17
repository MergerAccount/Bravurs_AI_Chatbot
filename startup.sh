#!/bin/bash
echo "Installing audio libraries for Azure Speech SDK..."

# Update package list
apt-get update

# Install required audio libraries
apt-get install -y \
    libasound2-dev \
    alsa-utils \
    alsa-oss

echo "Audio libraries installed successfully!"

# Start Flask application
python -m gunicorn app:app --bind 0.0.0.0:8000 --timeout 120 --workers 1

