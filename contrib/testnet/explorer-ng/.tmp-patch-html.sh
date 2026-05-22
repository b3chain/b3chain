#!/usr/bin/env bash
exec ssh -p 2222 -i ~/.ssh/lobby_cursor_ed25519 -o IdentitiesOnly=yes deploy@166.88.4.250 'sudo bash -s' <<'REMOTE'
set -e
perl -i -pe '
    s|<title>mempool - Bitcoin Explorer</title>|<title>B3Chain Live Explorer</title>|g;
    s/"\@mempool"/"\@b3chain"/g;
    s/mempool-space-preview/b3chain-explorer-preview/g;
' /var/www/b3chain-explorer-ng/index.html
echo "==> patched"
grep -iE 'mempool|title' /var/www/b3chain-explorer-ng/index.html | head -10
REMOTE
