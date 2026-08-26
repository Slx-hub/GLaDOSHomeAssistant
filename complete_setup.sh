#!/bin/bash

echo "Installing python dependencies..."
sh ./install.sh

echo "Linking and enabling systemd services..."
# enable-by-path links and enables in one step and succeeds on re-run,
# unlike `systemctl link` which fails once the link exists
sudo systemctl enable "$(pwd)/setup_files/glados.service"
sudo systemctl enable "$(pwd)/setup_files/http_bridge.service"

echo "Starting services..."
sudo systemctl start glados.service
sudo systemctl start http_bridge.service

echo "Setting up meter service..."
bash ./meter/setup_meter.sh

echo "Setting up aliases..."
cp ./setup_files/.bash_aliases ..

echo "Done."
