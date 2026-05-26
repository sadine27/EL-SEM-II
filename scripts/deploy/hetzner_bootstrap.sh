#!/usr/bin/env bash
# SP8 — idempotent provisioner for a fresh Hetzner CX22 (Ubuntu 24.04).
# Run as root on a freshly-imaged box.
set -euo pipefail

REPO="${REPO:-sadine27/el-sem-ii}"
PIN_SHA="${PIN_SHA:-REPLACE_WITH_COMMIT_SHA_AFTER_PUSH}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"

log() { printf '\n=== %s ===\n' "$*"; }

log "1/9 Verify Ubuntu 24.04"
. /etc/os-release
[ "$ID" = "ubuntu" ] && [ "$VERSION_ID" = "24.04" ] \
    || { echo "Expected Ubuntu 24.04, got $ID $VERSION_ID"; exit 1; }

log "2/9 apt update + base packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl ufw ca-certificates gnupg

log "3/9 Install Docker (official convenience script)"
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
fi

log "4/9 Create ${DEPLOY_USER} user and add to docker group"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"
mkdir -p "/home/${DEPLOY_USER}/.ssh"
chmod 700 "/home/${DEPLOY_USER}/.ssh"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
echo "Paste the deploy SSH public key into /home/${DEPLOY_USER}/.ssh/authorized_keys (mode 600) before continuing."

log "5/9 Harden sshd"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

log "6/9 Configure firewall"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

log "7/9 Create /etc/el and /var/lib/el"
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /etc/el
install -d -m 755 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /var/lib/el

log "8/9 Fetch docker-compose.yml + Caddyfile at pinned SHA"
RAW="https://raw.githubusercontent.com/${REPO}/${PIN_SHA}"
curl -fsSL "${RAW}/docker-compose.yml" -o /etc/el/docker-compose.yml
curl -fsSL "${RAW}/Caddyfile" -o /etc/el/Caddyfile
chown "${DEPLOY_USER}:${DEPLOY_USER}" /etc/el/docker-compose.yml /etc/el/Caddyfile

log "9/9 Touch .env, compose.env, compose.env.prev (so first deploy cp doesn't fail)"
install -m 600 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /dev/null /etc/el/.env
install -m 644 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /dev/null /etc/el/compose.env
install -m 644 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /dev/null /etc/el/compose.env.prev

echo
echo "Bootstrap complete. Next steps:"
echo "  1. Paste deploy SSH public key into /home/${DEPLOY_USER}/.ssh/authorized_keys"
echo "  2. Paste production secrets into /etc/el/.env"
echo "  3. Set vars/secrets in GitHub repo settings"
echo "  4. Push to main"
