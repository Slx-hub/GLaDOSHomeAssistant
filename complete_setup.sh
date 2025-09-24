#!/bin/bash

SERVICE_FILE="$(pwd)/setup_files/glados.service"

echo "Linking systemd service..."
sudo systemctl link "$SERVICE_FILE"

echo "Enabling service..."
sudo systemctl enable glados.service

echo "Starting service..."
sudo systemctl start glados.service

echo "Setting up aliases..."
cp ./setup_files/.bash_aliases ..

echo "Installing python dependencies..."
sh ./install.sh

echo "Done."
