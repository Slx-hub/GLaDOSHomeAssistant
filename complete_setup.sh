#!/bin/bash

echo "Installing python dependencies..."
sh ./install.sh

echo "Linking systemd services..."
sudo systemctl link "$(pwd)/setup_files/glados.service"
sudo systemctl link "$(pwd)/setup_files/http_bridge.service"

echo "Enabling services..."
sudo systemctl enable glados.service
sudo systemctl enable http_bridge.service

echo "Starting services..."
sudo systemctl start glados.service
sudo systemctl start http_bridge.service

echo "Setting up aliases..."
cp ./setup_files/.bash_aliases ..

echo "Done."
