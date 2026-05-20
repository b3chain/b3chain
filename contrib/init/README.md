Sample configuration files for:
```
systemd: b3chaind.service
Upstart: b3chaind.conf
OpenRC:  b3chaind.openrc
         b3chaind.openrcconf
CentOS:  b3chaind.init
macOS:   org.bitcoin.b3chaind.plist
```
have been made available to assist packagers in creating node packages here.

See [doc/init.md](../../doc/init.md) for more information.

## b3chain seed-server units (deployed on seed1, ready for seed2/seed3)

The two systemd units below match seed1 byte-for-byte and are the canonical
shape for any additional b3chain seed server:

- [`b3chaind-testnet.service`](b3chaind-testnet.service) — `b3chaind` running
  with `-chain=test`, well-hardened (`ProtectSystem=strict`,
  `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`,
  `LockPersonality`, `NoNewPrivileges`, etc.).  Companion to the upstream
  `bitcoind.service` sample above, NOT a replacement for it.
- [`b3chain-51watch.service`](b3chain-51watch.service) — the 51%-attack
  early-warning monitor (`contrib/monitoring/51attack-watch.py`), pinned to
  `Requires=b3chaind-testnet.service` so it follows the daemon's lifecycle.

For the full install recipe (env file, logrotate, JSONL sink, ACL on
`testnet3/debug.log`) see
[`doc/security/51-MONITORING-OPS.md`](../../doc/security/51-MONITORING-OPS.md).
