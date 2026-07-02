# Systemd Service

Use this on the Linux server to keep the HE web receiver always running.

The installer writes a service that runs directly from your server clone path,
so normal update flow is `git pull`, rebuild, restart.

The service:

- starts on boot
- restarts if the Python receiver crashes
- reads `/etc/he-uc-credit.env`
- runs from your clone directory
- stores jobs under `<clone>/server_jobs/web`

## Install

From a fresh clone on the server:

```bash
git pull
chmod +x deploy/systemd/install_he_job_service.sh
./deploy/systemd/install_he_job_service.sh "$USER" "$PWD"
```

Edit the env file:

```bash
sudo nano /etc/he-uc-credit.env
```

Set:

```text
HE_WEB_HOST=100.84.97.118
HE_WEB_PORT=8080
HE_RECEIVER_TOKEN=<long-random-token>
HE_WEB_MAX_WORKERS=1
HE_WEB_MAX_UPLOAD_BYTES=536870912
```

Build the C++ HE binaries in the clone:

```bash
cmake -S . -B build -DOpenFHE_DIR=$HOME/openfhe-development/build
cmake --build build
```

Start and enable:

```bash
sudo systemctl start he-uc-credit@$USER.service
sudo systemctl status he-uc-credit@$USER.service
```

Logs:

```bash
journalctl -u he-uc-credit@$USER.service -f
```

Restart after code/build changes:

```bash
git pull
cmake --build build
sudo systemctl restart he-uc-credit@$USER.service
```

Open:

```text
http://100.84.97.118:8080
```

## Manual Service Install

If you do not want the installer, edit `deploy/systemd/he-uc-credit.service`
and replace all `/opt/he_uc_credit` paths with your clone path, then:

```bash
sudo cp deploy/systemd/he-uc-credit.service /etc/systemd/system/he-uc-credit@.service
sudo systemctl daemon-reload
sudo systemctl enable he-uc-credit@$USER.service
sudo systemctl start he-uc-credit@$USER.service
```
