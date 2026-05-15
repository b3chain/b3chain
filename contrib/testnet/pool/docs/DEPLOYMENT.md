# Deployment runbook — `pool.b3chain.org` on seed1

The seed1 box already runs `b3chaind-testnet`, the faucet, the miner,
the explorer, and nginx. Adding the pool means: a new subdomain, a new
nginx vhost, Postgres + Postfix, a new dedicated wallet on the existing
b3chaind, and three new systemd units.

## Prerequisites

- Working `b3chaind-testnet.service` answering RPC at `127.0.0.1:18534`.
- `/etc/b3chain/rpcpassword` exists and is readable by group `b3chain`.
- nginx already TLS-enabled and using certbot.
- DNS A record `pool.b3chain.org → 166.88.4.250`.

## One-time install (run as root on seed1)

```bash
cd /tmp
git clone --depth 1 --branch b3chain-main https://github.com/b3chain/b3chain.git
cd b3chain/contrib/testnet/pool
sudo bash install.sh
```

`install.sh` is idempotent. It will:

1. Create the `b3chain-pool` system user, `/usr/local/lib/b3chain-pool`,
   `/var/log/b3chain-pool`, `/var/lib/b3chain-pool`, `/run/b3chain-pool`.
2. Install Node.js 20 + Postgres 16 + Postfix + nginx if missing.
3. Run `npm ci && npm run build` as `b3chain-pool`.
4. Write `/etc/b3chain-pool/pool.env` (only on first install — pre-fills
   a random `B3POOL_COOKIE_SECRET`).
5. Add the pool user to the `b3chain` group so it can read the RPC
   password.
6. Create role + database `b3chain_pool` in Postgres.
7. Apply all `db/migrations/*.sql`.
8. Create the `pool-payouts` wallet on the testnet b3chaind.
9. Install + enable the three systemd units (`b3chain-pool-stratum`,
   `b3chain-pool-daemon`, `b3chain-pool-web`) plus a `b3chain-pool.target`.
10. Drop the nginx vhost into `/etc/nginx/sites-{available,enabled}/`.
11. Open `3333/tcp` in UFW.
12. Add a daily logrotate config.

## TLS

After running `install.sh`, get the certificate before reloading nginx:

```bash
certbot certonly --webroot -w /var/www/letsencrypt -d pool.b3chain.org
nginx -t && systemctl reload nginx
```

The existing `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx`
handles auto-renewal reloads.

## Email (Postfix + DKIM/SPF)

The default Postfix install relays directly. For mail to land in user
inboxes (rather than spam), publish DNS:

- **SPF**: `b3chain.org. TXT "v=spf1 ip4:166.88.4.250 ~all"`
- **DKIM**: install `opendkim` and `opendkim-tools`, generate a key
  for selector `pool`:
  ```bash
  apt-get install -y opendkim opendkim-tools
  mkdir -p /etc/opendkim/keys/b3chain.org
  opendkim-genkey -D /etc/opendkim/keys/b3chain.org -d b3chain.org -s pool
  chown -R opendkim:opendkim /etc/opendkim
  cat /etc/opendkim/keys/b3chain.org/pool.txt   # publish as TXT pool._domainkey.b3chain.org
  ```
  Add `KeyTable`, `SigningTable`, `TrustedHosts` for opendkim and
  point Postfix at it via `smtpd_milters = inet:localhost:8891`.
- **DMARC**: `_dmarc.b3chain.org. TXT "v=DMARC1; p=quarantine; rua=mailto:postmaster@b3chain.org"`.

Until SPF/DKIM are live, verification mails will work but a measurable
fraction will be spam-foldered.

## Verifying

```bash
systemctl is-active b3chain-pool-stratum
systemctl is-active b3chain-pool-daemon
systemctl is-active b3chain-pool-web
ss -tlnp | grep -E '3333|5100|3334'
curl -sI https://pool.b3chain.org/ | head -1
curl -s  https://pool.b3chain.org/metrics | head
journalctl -u b3chain-pool-stratum -n 50 --no-pager
```

Then point a miner at it:

```bash
python3 contrib/miner/b3chain-cpuminer.py \
  --stratum stratum+tcp://pool.b3chain.org:3333 \
  --user yourreal@email.address.test1 --pass x
```

The dashboard at `https://pool.b3chain.org/dashboard` should show the
hashrate climbing within ~10 seconds.

## Backups

Postgres `pg_dumpall` should be wired into the existing nightly backup.
Specifically the tables that matter for replay: `users`, `workers`,
`shares` (last 30 days), `blocks`, `balance_entries`, `payouts`.
Everything else is reproducible.
