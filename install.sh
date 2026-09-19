#!/usr/bin/env bash
set -Eeuo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Run as root: sudo bash ./install.sh" >&2; exit 1; }
for c in docker python3 systemctl openssl; do command -v "$c" >/dev/null 2>&1 || { echo "$c is required" >&2; exit 1; }; done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SRC="$ROOT/oofm"
[[ -d "$APP_SRC" ]] || { echo "oofm package not found next to install.sh" >&2; exit 1; }

INSTALL_DIR=/opt/onlyoffice-font-manager
STATE_DIR=/var/lib/onlyoffice-font-manager
CONFIG=/etc/onlyoffice-font-manager.json
SERVICE=/etc/systemd/system/onlyoffice-font-manager.service
PORT="${OOFM_PORT:-8777}"

find_container() {
  docker ps --format '{{.Names}}|{{.Image}}' | awk -F'|' 'BEGIN{IGNORECASE=1} /communityserver|community-server/ {print $1; exit}'
}

COMM="$(find_container || true)"
[[ -n "$COMM" ]] || { echo "ONLYOFFICE Community Server container is not running." >&2; exit 1; }

GATEWAY="$(docker inspect "$COMM" | python3 -c 'import json,sys; x=json.load(sys.stdin)[0]["NetworkSettings"]["Networks"]; print(next((v.get("Gateway") for v in x.values() if v.get("Gateway")), ""))')"
[[ -n "$GATEWAY" ]] || { echo "Could not determine Docker gateway for $COMM" >&2; exit 1; }

mkdir -p "$INSTALL_DIR" "$STATE_DIR" "$STATE_DIR/cache" "$STATE_DIR/local" "$STATE_DIR/managed" "$STATE_DIR/backups"
rm -rf "$INSTALL_DIR/oofm"
cp -a "$APP_SRC" "$INSTALL_DIR/oofm"
find "$INSTALL_DIR/oofm" -type f -name '*.py' -exec chmod 0644 {} +

NEW_PASSWORD=""
if [[ ! -f "$CONFIG" ]]; then
  ADMIN_PASSWORD="${OOFM_ADMIN_PASSWORD:-$(openssl rand -base64 18 | tr -d '=+/\n' | cut -c1-22)}"
  PROXY_SECRET="$(openssl rand -hex 32)"
  SESSION_SECRET="$(openssl rand -hex 32)"
  python3 - "$CONFIG" "$ADMIN_PASSWORD" "$PROXY_SECRET" "$SESSION_SECRET" <<'PY'
import json,sys
p,pw,proxy,session=sys.argv[1:]
with open(p,'w') as f:
    json.dump({'admin_password':pw,'proxy_secret':proxy,'session_secret':session},f,indent=2)
PY
  chmod 0600 "$CONFIG"
  NEW_PASSWORD="$ADMIN_PASSWORD"
fi

PROXY_SECRET="$(python3 - "$CONFIG" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['proxy_secret'])
PY
)"

cat > "$SERVICE" <<EOF
[Unit]
Description=ONLYOFFICE Font Manager
After=docker.service network-online.target
Wants=docker.service network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 -m oofm
Restart=on-failure
RestartSec=3
Environment=OOFM_PORT=$PORT
Environment=OOFM_BIND_HOST=0.0.0.0
Environment=OOFM_BASE_PATH=/font-manager
Environment=OOFM_STATE_DIR=$STATE_DIR
Environment=OOFM_CONFIG=$CONFIG
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$STATE_DIR /tmp /var/tmp

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now onlyoffice-font-manager.service

TMP_CONF="$(mktemp)"
trap 'rm -f "$TMP_CONF"' EXIT
cat > "$TMP_CONF" <<EOF
# Managed by onlyoffice-font-upgrades / ONLYOFFICE Font Manager.
location = /font-manager {
    return 301 /font-manager/;
}
location /font-manager/ {
    proxy_pass http://$GATEWAY:$PORT/font-manager/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-OO-Font-Proxy "$PROXY_SECRET";
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    client_max_body_size 45m;
}
EOF

NGINX_DEST=/etc/nginx/includes/onlyoffice-communityserver-font-manager.conf
# Back up a previous manager include if present, then replace it.
if docker exec "$COMM" test -f "$NGINX_DEST" 2>/dev/null; then
  docker cp "$COMM:$NGINX_DEST" "$STATE_DIR/backups/nginx-font-manager.conf.previous" >/dev/null || true
fi
docker cp "$TMP_CONF" "$COMM:$NGINX_DEST" >/dev/null
if ! docker exec "$COMM" nginx -t; then
  echo "NGINX rejected the Font Manager include; removing it." >&2
  docker exec "$COMM" rm -f "$NGINX_DEST" || true
  exit 1
fi
docker exec "$COMM" nginx -s reload || docker restart --timeout 30 "$COMM" >/dev/null

cat > /usr/local/sbin/onlyoffice-font-manager-repair-proxy <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
COMM=\$(docker ps --format '{{.Names}}|{{.Image}}' | awk -F'|' 'BEGIN{IGNORECASE=1} /communityserver|community-server/ {print \$1; exit}')
[[ -n "\$COMM" ]] || { echo "Community Server not running" >&2; exit 1; }
GATEWAY=\$(docker inspect "\$COMM" | python3 -c 'import json,sys; x=json.load(sys.stdin)[0]["NetworkSettings"]["Networks"]; print(next((v.get("Gateway") for v in x.values() if v.get("Gateway")), ""))')
SECRET=\$(python3 -c 'import json; print(json.load(open("$CONFIG"))["proxy_secret"])')
cat >/tmp/oofm-nginx.conf <<CONF
location = /font-manager { return 301 /font-manager/; }
location /font-manager/ {
    proxy_pass http://\$GATEWAY:$PORT/font-manager/;
    proxy_http_version 1.1;
    proxy_set_header Host \\$host;
    proxy_set_header X-Real-IP \\$remote_addr;
    proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \\$scheme;
    proxy_set_header X-OO-Font-Proxy "\$SECRET";
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    client_max_body_size 45m;
}
CONF
docker cp /tmp/oofm-nginx.conf "\$COMM:$NGINX_DEST"
docker exec "\$COMM" nginx -t
docker exec "\$COMM" nginx -s reload
rm -f /tmp/oofm-nginx.conf
EOF
chmod 0755 /usr/local/sbin/onlyoffice-font-manager-repair-proxy

cat <<EOF

============================================================
 ONLYOFFICE FONT MANAGER INSTALLED
============================================================
Portal path:
  /font-manager/

Community Server:
  $COMM
Docker gateway:
  $GATEWAY

In ONLYOFFICE go to:
  Settings -> Modules & Tools -> Custom Navigation -> Add Item

Use:
  Label: Fonts
  URL:   https://<your-ONLYOFFICE-host>/font-manager/

Show it in the menu and/or on the home page.

The app applies one selected font set to BOTH:
  - Workspace Mail / CKEditor
  - ONLYOFFICE Document Server

It also installs the optional Noto Color Emoji pack and adds an
emoji picker to Mail compose.
EOF
if [[ -n "$NEW_PASSWORD" ]]; then
cat <<EOF

Font Manager admin password (shown once):
  $NEW_PASSWORD

It is stored root-only in:
  $CONFIG
EOF
else
cat <<EOF

Existing Font Manager admin password was preserved in:
  $CONFIG
EOF
fi
cat <<'EOF'

After a Community Server container is replaced by an ONLYOFFICE update,
restore the embedded route with:
  sudo onlyoffice-font-manager-repair-proxy

Then open the Fonts item inside ONLYOFFICE.
============================================================
EOF
