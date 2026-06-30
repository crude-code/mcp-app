#!/usr/bin/env bash
# Run on the EC2 host by the GitHub Action (.github/workflows/deploy.yml).
# Pulls main, syncs the nginx config, rebuilds the renderer, and restarts
# the MCP server only when something the running process actually loaded
# into memory has changed.
#
# Idempotent. Safe to re-run; nginx is only reloaded when its config
# differs, and the MCP server is only restarted when paths it depends on
# changed since the last successful deploy (tracked in
# .last-mcp-deployed-sha so a partially-failed previous deploy still
# triggers the restart on the next run).
set -euo pipefail

cd /home/ubuntu/crudecode

git fetch --quiet origin main
git reset --hard origin/main
NEW_SHA=$(git rev-parse HEAD)

# --- nginx config sync ----------------------------------------------------
# The canonical prod nginx configs live in deploy/nginx/ in the repo, one file
# per /etc/nginx/conf.d/ entry. For each, if it differs from what's installed
# on the host, back up the live file, copy the new one in. Only the prod files
# are synced here (the dev vhost is owned by deploy-dev.sh). nginx is validated
# and reloaded once at the end; on validation failure every change is rolled
# back and we bail before touching the MCP server.
NGINX_CONFS=(crudecode-mcp.conf crudecode-site.conf)
NGINX_TS=$(date +%Y%m%d-%H%M%S)
NGINX_CHANGED=0
NGINX_ROLLBACK=()   # entries: "live|backup" (existing file) or "live|NEW" (created)
for name in "${NGINX_CONFS[@]}"; do
    REPO_CONF="deploy/nginx/${name}"
    LIVE_CONF="/etc/nginx/conf.d/${name}"
    cmp -s "$REPO_CONF" "$LIVE_CONF" && continue
    echo "nginx config differs — applying ${name}"
    if [ -f "$LIVE_CONF" ]; then
        sudo cp "$LIVE_CONF" "${LIVE_CONF}.bak-${NGINX_TS}"
        NGINX_ROLLBACK+=("${LIVE_CONF}|${LIVE_CONF}.bak-${NGINX_TS}")
    else
        NGINX_ROLLBACK+=("${LIVE_CONF}|NEW")
    fi
    sudo cp "$REPO_CONF" "$LIVE_CONF"
    NGINX_CHANGED=1
done
if [ "$NGINX_CHANGED" = "1" ]; then
    if sudo nginx -t; then
        sudo systemctl reload nginx
        echo "nginx reloaded"
    else
        echo "nginx -t failed — rolling back nginx changes"
        for entry in "${NGINX_ROLLBACK[@]}"; do
            live="${entry%%|*}"; bak="${entry##*|}"
            if [ "$bak" = "NEW" ]; then sudo rm -f "$live"; else sudo cp "$bak" "$live"; fi
        done
        exit 1
    fi
fi

# --- python + renderer + mcp server ---------------------------------------
# Always reinstall + rebuild — these are cheap, idempotent, and skipping
# them risks an inconsistent on-disk state if a later restart fires.
.venv/bin/pip install -q -r requirements.txt

npm ci --prefix renderer
npm run build --prefix renderer

# Restart the MCP server only when paths it loaded into memory at startup
# changed: server code, utils, prompts, the renderer HTML (read into
# APP_HTML at module load), or pip requirements. Doc-only, nginx-only,
# signup-only, ingest-only, scripts-only, and tests-only changes deploy
# without disconnecting active users.
RESTART_PATHS_REGEX='^(server/|utils/|prompts/|renderer/|requirements\.txt$)'
LAST_DEPLOYED_SHA_FILE=/home/ubuntu/crudecode/.last-mcp-deployed-sha

NEEDS_RESTART=1
if [ -f "$LAST_DEPLOYED_SHA_FILE" ]; then
    LAST_SHA=$(cat "$LAST_DEPLOYED_SHA_FILE")
    if [ "$LAST_SHA" = "$NEW_SHA" ]; then
        echo "MCP already at $NEW_SHA — no restart needed"
        NEEDS_RESTART=0
    elif git cat-file -e "$LAST_SHA" 2>/dev/null; then
        if git diff --name-only "$LAST_SHA" "$NEW_SHA" | grep -Eq "$RESTART_PATHS_REGEX"; then
            echo "MCP-relevant paths changed since $LAST_SHA — restarting"
            git diff --name-only "$LAST_SHA" "$NEW_SHA" | grep -E "$RESTART_PATHS_REGEX" | sed 's/^/  changed: /'
        else
            echo "no MCP-relevant changes since $LAST_SHA — leaving MCP running"
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
    sudo systemctl restart crudecode-mcp
fi

# Restart the signup service only when code the running process loaded at
# startup changed: signup/app.py or the utils modules it imports
# (utils.platform, utils.ses). The signup HTML (index.html/setup.html) is
# served via FileResponse from disk per request, so HTML-only changes go
# live on the git pull with no restart. deploy.sh owns this because nothing
# else restarts crudecode-signup — the app.py + utils/ses.py waitlist change
# on 2026-06-10 reached disk but stayed dormant until a manual restart.
# Reuses the same LAST_SHA→NEW_SHA window as the MCP decision above.
SIGNUP_RESTART_PATHS_REGEX='^(signup/app\.py$|utils/)'
NEEDS_SIGNUP_RESTART=1
if [ -f "$LAST_DEPLOYED_SHA_FILE" ] && git cat-file -e "$LAST_SHA" 2>/dev/null; then
    if [ "$LAST_SHA" = "$NEW_SHA" ]; then
        echo "signup already at $NEW_SHA — no restart needed"
        NEEDS_SIGNUP_RESTART=0
    elif git diff --name-only "$LAST_SHA" "$NEW_SHA" | grep -Eq "$SIGNUP_RESTART_PATHS_REGEX"; then
        echo "signup-relevant paths changed since $LAST_SHA — restarting"
        git diff --name-only "$LAST_SHA" "$NEW_SHA" | grep -E "$SIGNUP_RESTART_PATHS_REGEX" | sed 's/^/  changed: /'
    else
        echo "no signup-relevant changes since $LAST_SHA — leaving signup running"
        NEEDS_SIGNUP_RESTART=0
    fi
fi

if [ "$NEEDS_SIGNUP_RESTART" = "1" ]; then
    sudo systemctl restart crudecode-signup
fi

echo "$NEW_SHA" > "$LAST_DEPLOYED_SHA_FILE"
