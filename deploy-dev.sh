#!/usr/bin/env bash
# Deploys the `dev` branch to /home/ubuntu/crudecode-dev/ and restarts
# crudecode-mcp-dev (port 9001) only when MCP-loaded paths change.
#
# Run on the EC2 host by .github/workflows/deploy-dev.yml when `dev`
# branch is pushed. Mirrors deploy.sh for the prod side.
#
# Idempotent. Touches its own systemd service + its own nginx vhost
# file (deploy/nginx/crudecode-dev.conf → /etc/nginx/conf.d/crudecode-dev.conf).
# Does NOT touch the prod service or prod nginx config.

set -euo pipefail

cd /home/ubuntu/crudecode-dev

git fetch --quiet origin dev
git reset --hard origin/dev
NEW_SHA=$(git rev-parse HEAD)

# --- nginx config sync (dev only) ----------------------------------------
NGINX_LIVE=/etc/nginx/conf.d/crudecode-dev.conf
NGINX_REPO=deploy/nginx/crudecode-dev.conf
if ! cmp -s "$NGINX_REPO" "$NGINX_LIVE" 2>/dev/null; then
    echo "nginx-dev config differs (or missing) — applying update"
    TS=$(date +%Y%m%d-%H%M%S)
    if [ -f "$NGINX_LIVE" ]; then
        sudo cp "$NGINX_LIVE" "${NGINX_LIVE}.bak-${TS}"
    fi
    sudo cp "$NGINX_REPO" "$NGINX_LIVE"
    if sudo nginx -t; then
        sudo systemctl reload nginx
        echo "nginx reloaded"
    else
        echo "nginx -t failed — restoring previous state"
        if [ -f "${NGINX_LIVE}.bak-${TS}" ]; then
            sudo cp "${NGINX_LIVE}.bak-${TS}" "$NGINX_LIVE"
        else
            sudo rm -f "$NGINX_LIVE"
        fi
        exit 1
    fi
fi

# --- deal-sheet template publish ------------------------------------------
# Mirrors the prod block in deploy.sh — dev publishes into the same shared
# directory (content-addressed, so no skew with prod is possible). The apex
# /templates/ location itself is owned by crudecode-site.conf, which only a
# prod deploy syncs.
TEMPLATE_SRC=server/valuation/viewer/DealSheet.jsx
TEMPLATE_DIR=/var/www/cc-templates
TEMPLATE_SHA=$(sha256sum "$TEMPLATE_SRC" | cut -c1-12)
TEMPLATE_DEST="${TEMPLATE_DIR}/deal-sheet-${TEMPLATE_SHA}.jsx"
if [ ! -f "$TEMPLATE_DEST" ]; then
    sudo mkdir -p "$TEMPLATE_DIR"
    sudo install -m 644 "$TEMPLATE_SRC" "$TEMPLATE_DEST"
    echo "published deal-sheet template ${TEMPLATE_SHA}"
fi

# --- python + renderer ---------------------------------------------------
# Mirror prod's deploy.sh install block — dev and prod should diverge only
# in branch + paths + service name, never in installed packages. When a new
# pip package gets added here, prod's deploy.sh needs the same line.
.venv/bin/pip install -q -r requirements.txt

npm ci --prefix renderer
npm run build --prefix renderer

# --- restart logic (mirrors deploy.sh, scoped to dev) --------------------
RESTART_PATHS_REGEX='^(server/|utils/|prompts/|renderer/|requirements\.txt$)'
LAST_DEPLOYED_SHA_FILE=/home/ubuntu/crudecode-dev/.last-mcp-deployed-sha

NEEDS_RESTART=1
if [ -f "$LAST_DEPLOYED_SHA_FILE" ]; then
    LAST_SHA=$(cat "$LAST_DEPLOYED_SHA_FILE")
    if [ "$LAST_SHA" = "$NEW_SHA" ]; then
        echo "MCP-dev already at $NEW_SHA — no restart needed"
        NEEDS_RESTART=0
    elif git cat-file -e "$LAST_SHA" 2>/dev/null; then
        if git diff --name-only "$LAST_SHA" "$NEW_SHA" | grep -Eq "$RESTART_PATHS_REGEX"; then
            echo "MCP-relevant paths changed since $LAST_SHA — restarting crudecode-mcp-dev"
            git diff --name-only "$LAST_SHA" "$NEW_SHA" | grep -E "$RESTART_PATHS_REGEX" | sed 's/^/  changed: /'
        else
            echo "no MCP-relevant changes since $LAST_SHA — leaving crudecode-mcp-dev running"
            git diff --name-only "$LAST_SHA" "$NEW_SHA" | sed 's/^/  skipped: /'
            NEEDS_RESTART=0
        fi
    else
        echo "last-deployed sha $LAST_SHA not in history — restarting to be safe"
    fi
else
    echo "no .last-mcp-deployed-sha marker — restarting on first run"
fi

if [ "$NEEDS_RESTART" = "1" ]; then
    sudo systemctl restart crudecode-mcp-dev
fi
echo "$NEW_SHA" > "$LAST_DEPLOYED_SHA_FILE"
