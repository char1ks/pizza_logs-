#!/bin/bash

# Pizza Order System - Log Initialization Script
# This script ensures all required log files and directories exist before service startup

set -e

# Get service name from environment variable or use default
SERVICE_NAME=${SERVICE_NAME:-"unknown-service"}
LOGS_DIR="/app/logs"

echo "Initializing logs for service: $SERVICE_NAME"

# Create logs directory if it doesn't exist
mkdir -p "$LOGS_DIR"

# Use service name directly for log file name to ensure consistency across services
LOG_FILE="$LOGS_DIR/${SERVICE_NAME}.log"
if [ ! -f "$LOG_FILE" ]; then
    touch "$LOG_FILE"
    echo "Created log file: $LOG_FILE"
else
    echo "Log file already exists: $LOG_FILE"
fi

chown -R pizza:pizza "$LOGS_DIR"
chmod -R 755 "$LOGS_DIR"
chmod 644 "$LOG_FILE"

echo "Log initialization completed for $SERVICE_NAME"

# Execute the main command passed to the script
exec "$@"