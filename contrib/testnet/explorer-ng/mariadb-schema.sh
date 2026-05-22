#!/usr/bin/env bash
#
# Idempotent MariaDB bootstrap for B3Chain Live Explorer.
#
# Creates database `explorer_ng` and user `explorer_ng`@`localhost`.
# Password is generated once and stored in /etc/b3chain/explorer-ng/db.pass
# (mode 0640, group b3chain-explorer-ng). install.sh re-uses that secret.
set -euo pipefail
export LC_ALL=C

DB="explorer_ng"
USER="explorer_ng"
PASS_FILE="/etc/b3chain/explorer-ng/db.pass"

install -d -m 0755 -o root -g root /etc/b3chain/explorer-ng

if ! systemctl is-active --quiet mariadb; then
    systemctl enable --now mariadb
fi

if [ ! -s "$PASS_FILE" ]; then
    PASS=$(openssl rand -hex 24)
    install -m 0640 -o root -g root /dev/null "$PASS_FILE" || touch "$PASS_FILE"
    chmod 0640 "$PASS_FILE"
    printf '%s' "$PASS" > "$PASS_FILE"
    chgrp b3chain-explorer-ng "$PASS_FILE" 2>/dev/null || true
fi
PASS=$(cat "$PASS_FILE")

mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB}\`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${USER}'@'localhost' IDENTIFIED BY '${PASS}';
ALTER USER '${USER}'@'localhost' IDENTIFIED BY '${PASS}';
GRANT ALL PRIVILEGES ON \`${DB}\`.* TO '${USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "mariadb-schema: db=${DB} user=${USER} pass=$(stat -c '%a %U:%G' "$PASS_FILE") ${PASS_FILE}"
