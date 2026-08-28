#!/bin/bash
# Setup for meter.service — own venv, deliberately separate from the Rhasspy
# stack. Called by complete_setup.sh, can also be run standalone.
# Idempotent: safe to re-run after config changes or a git pull.
set -e
cd "$(dirname "$0")"

echo "Setting up meter venv..."
if [ ! -d venv ]; then
    python3 -m venv venv
fi
./venv/bin/pip install -q -r requirements.txt

if [ ! -f /etc/meter.env ]; then
    echo "Installing /etc/meter.env template..."
    sudo cp ../setup_files/meter.env.example /etc/meter.env
fi
sudo chmod 600 /etc/meter.env

echo "Creating history data dir..."
mkdir -p data

echo "Enabling meter.service and meter-history.service..."
# enable-by-path links and enables in one step and succeeds on re-run,
# unlike `systemctl link` which fails once the link exists
sudo systemctl enable "$(pwd)/../setup_files/meter.service"
sudo systemctl enable "$(pwd)/../setup_files/meter-history.service"
sudo systemctl daemon-reload

if sudo grep -q '^FRITZBOX_PASSWORD=changeme$' /etc/meter.env; then
    echo
    echo "meter.service is enabled but NOT started — the password is still the template value."
    echo "  1. sudo nano /etc/meter.env      (set FRITZBOX_PASSWORD)"
    echo "  2. edit meter/config.yaml        (box IP, user, AIN)"
    echo "  3. re-run this script, or: sudo systemctl start meter.service"
    echo
    echo "No hardware yet? Test the MQTT contract with:"
    echo "  ./venv/bin/python meter_service.py --simulate --verbose"
else
    echo "Restarting meter.service..."
    sudo systemctl restart meter.service
    echo "Restarting meter-history.service..."
    sudo systemctl restart meter-history.service
fi
