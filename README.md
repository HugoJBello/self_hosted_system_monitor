# System Monitor

`System Monitor` is a Dockerized Django application that collects host metrics at a configurable interval and stores them in SQLite for live dashboards and historical charts.

## Features

- Bootstrap-based UI in English.
- Reverse-proxy friendly under a configurable subpath, `/system_monitor` by default.
- Live monitor page inspired by `htop`/`glances`, adapted for the web.
- Configuration page to control the sampling interval and retention.
- Configuration page for an external notifications service API.
- Django username/password authentication for all web views.
- Admin-only settings and user management.
- Alerts page with configurable stress-detection rules and a recent alert feed.
- History page with Chart.js charts for CPU, memory, load, disk, network, and process counts.
- Persistent SQLite data exposed through a bind mount in `./data`.
- Background sampler service that continuously records system snapshots and top processes.
- Host-oriented metric collection via read-only access to the host filesystem and `/proc`.
- Staff-only web terminal with a Linux login prompt and host SSH session support.

## Project Layout

- `config/`: Django project settings and URL configuration.
- `monitor/`: monitoring app, models, services, views, and management command.
- `templates/`: Bootstrap templates.
- `static/`: CSS assets.
- `data/`: bind-mounted runtime data such as SQLite.

## Run

```bash
docker compose up --build
```

The web UI will be available at:

- `http://localhost:8012/system_monitor/`

To use a different public subpath, set `APP_SUBPATH` before starting Compose:

```bash
APP_SUBPATH=/my_monitor docker compose up --build
```

Default login after first start:

- username: `admin`
- password: `change_me`

Change this password immediately from the account password page. The default admin is created automatically during container startup if it does not already exist.

## Runtime Notes

- The app is configured for reverse proxying behind Nginx under `APP_SUBPATH`, `/system_monitor` by default.
- SQLite is stored at `./data/db.sqlite3`, so the database remains accessible outside Docker.
- The sampler runs in a separate container and reads the latest configuration from the database before each collection cycle.
- The containers mount the host root read-only so the sampler can inspect host processes, disks, memory, and network instead of only container-local values.

## Main Environment Variables

- `APP_SUBPATH`: default `/system_monitor`
- `DJANGO_DB_PATH`: default `/app/data/db.sqlite3`
- `DJANGO_ALLOWED_HOSTS`: default `*`
- `DJANGO_CSRF_TRUST_ANY_ORIGIN`: default `False`; set `True` to allow POST forms from any external origin while still requiring the CSRF cookie/token pair
- `DJANGO_CSRF_TRUSTED_ORIGINS`: comma-separated external origins allowed to POST forms, for example `https://*.hjbello.org,https://api-android18.hjbello.org`
- `DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE`: default `20971520`; global Django in-memory request body limit. HTTP backup JSON endpoints stream their bodies directly, but this remains a moderate safety margin for other Django requests.
- `GUNICORN_TIMEOUT_SECONDS`: default `960`; keep this high enough for HTTP backup receiver requests over large folder trees
- `SAMPLER_DEFAULT_INTERVAL`: default `60`
- `MONITOR_ROOT_PATH`: default `/hostfs`
- `MONITOR_PROCFS_PATH`: default `/hostfs/proc`
- `WEB_TERMINAL_IDLE_TIMEOUT_SECONDS`: default `600`; disconnected terminal sessions are kept for at least 10 minutes
- `WEB_TERMINAL_HOST_SSH`: default `true`; after validating the Linux login, open the host shell through SSH so `sudo` works normally
- `WEB_TERMINAL_HOST_SSH_HOST`: default auto-detects `host.docker.internal`, then Docker's default gateway
- `WEB_TERMINAL_SSH_KNOWN_HOSTS`: default `/app/data/web_terminal_known_hosts`
- `WEB_TERMINAL_COMMAND`: optional full command override for the terminal process; advanced/debug use only
- `NOTIFICATIONS_ENABLED`: default `False`
- `NOTIFICATIONS_API_URL`: default `http://127.0.0.1:49231/notifications/api/receive/`
- `NOTIFICATIONS_API_TOKEN`: default empty
- `NOTIFICATIONS_DEFAULT_CHANNELS`: default `email`
- `NOTIFICATIONS_DEFAULT_TAGS`: default empty
- `NOTIFICATIONS_DEFAULT_USER`: default empty
- `NOTIFICATIONS_DEFAULT_ORIGIN`: default `system-monitor`
- `NOTIFICATIONS_DEFAULT_STATUS`: default `warning`
- `NOTIFICATIONS_DEFAULT_PRIORITY`: default `high`
- `NOTIFICATIONS_DEFAULT_ACTION`: default `notify`
- `NOTIFICATIONS_TIMEOUT_SECONDS`: default `10`
- `SYSTEM_MONITOR_DEFAULT_ADMIN_USER`: default `admin`
- `SYSTEM_MONITOR_DEFAULT_ADMIN_PASSWORD`: default `change_me`
- `SYSTEM_MONITOR_DEFAULT_ADMIN_EMAIL`: default empty
- `HTTP_BACKUP_TOKEN`: default `change_this_token`

## First Start

On startup the web container entrypoint:

1. applies migrations
2. ensures the default admin user exists
3. collects static files
4. starts Daphne

The background services do not run these initialization steps. This avoids concurrent writes against the shared SQLite database during `docker compose up`.

The web service also exposes a lightweight healthcheck endpoint at `<APP_SUBPATH>/healthz/`, for example `/system_monitor/healthz/`. Docker uses the internal `/healthz/` endpoint as the healthcheck, and the background services wait for the web container to become healthy before they start.

The sampler service waits for the database and then begins saving snapshots.

## Authentication and Users

All web pages require a Django username/password login. The HTTP backup synchronization API is the exception: `/backups/http/manifest/`, `/backups/http/list/`, `/backups/http/stat/`, `/backups/http/file/`, and `/backups/http/delete/` do not use the web login because they authenticate with their own Bearer token.

Roles:

- Normal users can use the monitor, history, alerts, reports, backups, and change their own password.
- Admin users can also open Settings and Users.
- The Users page lets admins create normal/admin users and reset any user password.
- The Django admin console is still available for direct database administration.

The bootstrap admin user is:

```text
username: admin
password: change_me
```

Override it with `SYSTEM_MONITOR_DEFAULT_ADMIN_USER`, `SYSTEM_MONITOR_DEFAULT_ADMIN_PASSWORD`, and `SYSTEM_MONITOR_DEFAULT_ADMIN_EMAIL`.

## Web Terminal

The `Terminal` page is staff-only and opens an interactive login prompt for a real Linux user on the host.

Required host/container setup:

- The web container must keep `privileged: true`, `pid: host`, and the host root mounted at `MONITOR_ROOT_PATH` (`/hostfs` by default). This lets the app validate the Linux username/password against the host `/etc/passwd` and `/etc/shadow`.
- The host must run an SSH server reachable from the web container. On Arch Linux this is normally `openssh` with `sshd` enabled:

```bash
sudo pacman -S openssh
sudo systemctl enable --now sshd
```

- Password login must be allowed for the Linux users who should use the web terminal. Check the host SSH daemon config if login fails before the shell opens.
- The web image includes `openssh-client` and `sshpass`; keep both installed in the Dockerfile.
- `docker-compose.yml` maps `host.docker.internal` to Docker's `host-gateway` for the web service:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Why SSH is used:

- The terminal first verifies the Linux login against the host shadow database.
- After successful verification it opens `ssh -tt <user>@host.docker.internal`.
- This creates a normal host `sshd` session, so `sudo`, PAM, groups, TTY handling, and setuid binaries behave like they do in a regular SSH terminal.
- A direct `nsenter + su` shell is kept as a fallback, but it is not preferred because `sudo` can fail there with `effective uid is not 0` when setuid elevation is blocked by the container/runtime context.

Useful terminal environment variables:

- `WEB_TERMINAL_HOST_SSH=true`: use host SSH after login. This is the default and recommended setting.
- `WEB_TERMINAL_HOST_SSH_HOST=host.docker.internal`: override the host SSH target if Docker's gateway name is not suitable.
- `WEB_TERMINAL_SSH_KNOWN_HOSTS=/app/data/web_terminal_known_hosts`: persistent known-hosts file used by the web terminal SSH client.
- `WEB_TERMINAL_IDLE_TIMEOUT_SECONDS=600`: keep disconnected terminal sessions alive for at least 10 minutes.
- `WEB_TERMINAL_COMMAND`: override the whole terminal command for debugging or custom deployments.

## HTTP Backup Receiver Token

HTTP server-to-server backup jobs use a dedicated Bearer token and do not depend on the web login session.

The receiving server stores its accepted token in Settings under `HTTP backup receiver`. The default is:

```text
change_this_token
```

Change it before using HTTP backups between servers. The value is also initializable with:

```env
HTTP_BACKUP_TOKEN=change_this_token
```

When configuring an HTTP backup job, set `Remote Bearer token` to the token saved on the other server. The token is sent as:

```http
Authorization: Bearer <token>
```

This token protects the HTTP backup endpoints that can list, compare, inspect, read, write, and delete files under the configured backup paths.

HTTP backups compare file size and modification time in seconds, matching rsync's normal quick-check behavior. Push jobs copy the local folder to the remote server: they send large batches of local metadata to the remote compare endpoint, upload changed files through the file endpoint, and when delete is enabled prune the remote destination in bounded directory batches based on the local tree. Pull jobs copy the remote folder to a local destination: they request the remote manifest, download changed files through the file endpoint, and when delete is enabled remove local destination files that no longer exist on the remote source. If a receiver is still missing the compare endpoint, push jobs fall back to bounded stat batches, and then to `HEAD` checks on the existing file endpoint. Uploaded and pulled files preserve their source modification time so subsequent runs can skip unchanged media without hashing every file in large trees.

## Alerts

The application includes an `Alerts` page at `/system_monitor/alerts/`.

It provides:

- A push-style feed of recent alert events.
- Active versus resolved alert status.
- Editable alert rules from the web UI.
- Automatic notification delivery through the configured notifications service when both the notifications backend and the rule are enabled.

Each rule can be tuned with:

- severity
- metric
- evaluation mode
- comparator
- threshold
- time window in minutes
- minimum matching occurrences
- cooldown in minutes
- per-rule notification channels, tags, and user

Evaluation modes:

- `current`: compare only the latest snapshot
- `avg`: compare the average value across the configured time window
- `max`: compare the maximum value across the configured time window
- `min`: compare the minimum value across the configured time window

Default rules are created automatically on first use for:

- sustained high CPU
- critical memory pressure
- disk almost full
- zombie process detection

Alert evaluation happens automatically after each new snapshot is stored.

## Notifications Integration

The settings page now includes a full `Notifications service API` section intended for your external notifications server.

Supported fields in the UI:

- API receive URL
- Bearer token
- Default channels
- Default tags
- Default user
- Origin
- Status
- Priority
- Action
- Timeout

The UI also includes a `Save and send test notification` button. It sends a JSON payload to the configured `notifications/api/receive/` endpoint using the saved bearer token and includes a short summary of the latest system snapshot when available.

### Example Values

For a local deployment matching your notifications stack, these values make sense:

```env
NOTIFICATIONS_ENABLED=True
NOTIFICATIONS_API_URL=http://127.0.0.1:49231/notifications/api/receive/
NOTIFICATIONS_API_TOKEN=change-this-token
NOTIFICATIONS_DEFAULT_CHANNELS=email;telegram;xmpp
NOTIFICATIONS_DEFAULT_TAGS=server;alert
NOTIFICATIONS_DEFAULT_USER=
NOTIFICATIONS_DEFAULT_ORIGIN=system-monitor
NOTIFICATIONS_DEFAULT_STATUS=warning
NOTIFICATIONS_DEFAULT_PRIORITY=high
NOTIFICATIONS_DEFAULT_ACTION=notify
NOTIFICATIONS_TIMEOUT_SECONDS=10
```

Notes:

- `NOTIFICATIONS_API_URL` should point directly to `/notifications/api/receive/`.
- Channels are normalized as `email`, `telegram`, and `xmpp`.

## Reverse Proxy Notes

The Django settings already account for:

- `FORCE_SCRIPT_NAME`
- prefixed `STATIC_URL`
- `X-Forwarded-Proto`
- `DJANGO_CSRF_TRUSTED_ORIGINS` for external HTTPS form posts
- `DJANGO_CSRF_TRUST_ANY_ORIGIN=True` when this deployment must accept form posts from arbitrary public origins

If your external Nginx proxies `/system_monitor/` to this container, set `APP_SUBPATH=/system_monitor`. The app accepts both direct prefixed requests and proxy-rewritten requests.

### Nginx Example

Use a location block like this in your external Nginx:

```nginx
location = /system_monitor {
    return 301 /system_monitor/;
}

location /system_monitor/ {
    client_max_body_size 10G;

    proxy_pass http://127.0.0.1:8012/;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /system_monitor;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    proxy_redirect off;
    proxy_read_timeout 300;
    proxy_connect_timeout 60;
    proxy_send_timeout 300;
}
```

Important notes:

- Keep the trailing slash in `/system_monitor/`.
- Keep the trailing slash in `proxy_pass`.
- Keep `client_max_body_size` high enough for file-manager uploads. Align it with `DJANGO_DATA_UPLOAD_MAX_MEMORY_SIZE`; otherwise Nginx can return `413 Request Entity Too Large` before Django receives the upload.
- With this example, Nginx strips `/system_monitor/` before forwarding to Django. `FORCE_SCRIPT_NAME` handles URL generation with the external prefix.
- Keep `X-Forwarded-Prefix /system_monitor` aligned with `APP_SUBPATH`.
- Add the public origin to `DJANGO_CSRF_TRUSTED_ORIGINS`, for example `https://*.hjbello.org` or explicit hosts such as `https://api-android18.hjbello.org`, otherwise login and other POST forms will be rejected by Django CSRF origin checks.
- If the app is intentionally reached through many changing domains, set `DJANGO_CSRF_TRUST_ANY_ORIGIN=True`. This skips Django's Origin allowlist check, but forms still require a valid CSRF cookie and token.
