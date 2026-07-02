#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_USER="${1:-$USER}"
SERVICE_REPO_DIR="${2:-$REPO_DIR}"
ENV_FILE="/etc/he-uc-lending.env"
UNIT_NAME="he-uc-lending@${SERVICE_USER}.service"
UNIT_PATH="/etc/systemd/system/he-uc-lending@.service"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; this installer is for Linux systemd servers." >&2
  exit 1
fi

echo "Installing HE receiver service"
echo "  repo:         $SERVICE_REPO_DIR"
echo "  service user: $SERVICE_USER"
echo "  unit:         $UNIT_NAME"

if [ ! -f "$SERVICE_REPO_DIR/code/server/web/he_job_server.py" ]; then
  echo "repo path does not look right: $SERVICE_REPO_DIR" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  sudo cp "$REPO_DIR/deploy/systemd/he-uc-lending.env.example" "$ENV_FILE"
  sudo chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE. Edit HE_RECEIVER_TOKEN before opening the service to clients."
fi

sudo tee "$UNIT_PATH" >/dev/null <<UNIT
[Unit]
Description=HE UC Lending encrypted job receiver
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=%i
WorkingDirectory=$SERVICE_REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=/usr/bin/python3 $SERVICE_REPO_DIR/code/server/web/he_job_server.py --host \${HE_WEB_HOST} --port \${HE_WEB_PORT} --build-dir $SERVICE_REPO_DIR/build --jobs-dir $SERVICE_REPO_DIR/server_jobs/web
Restart=always
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGINT
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable "$UNIT_NAME"

echo
echo "Next:"
echo "  cd $SERVICE_REPO_DIR"
echo "  cmake -S . -B build -DOpenFHE_DIR=\$HOME/openfhe-development/build"
echo "  cmake --build build"
echo "  sudo systemctl start $UNIT_NAME"
echo "  sudo systemctl status $UNIT_NAME"
