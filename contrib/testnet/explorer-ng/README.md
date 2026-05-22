# B3Chain Live Explorer (`explorer-ng`) deployment

Operator-facing scaffolding for **B3Chain Live Explorer**, a B3Chain-branded
fork of the AGPLv3-licensed source at <https://github.com/mempool/mempool>.

This directory installs a separate explorer stack on **seed1** (alongside the
existing btc-rpc-explorer at port 3002) under nginx path `/v2/`, then later
takes over `/`.

> **Trademark posture.** "Mempool", "Mempool Goggles™", "Mempool Accelerator®"
> and the half-block logo are trademarks of The Mempool Open Source Project.
> We rebrand publicly to **B3Chain Live Explorer**, drop the Accelerator
> feature entirely, and rename "Goggles" to "Tx Filters". The script
> [`tools/tm-audit.sh`](tools/tm-audit.sh) refuses any deploy that contains
> upstream branding outside two whitelisted attribution lines (AGPL §5/§7).
> See [`B3Chain Live Explorer Replication Plan`](../../../../.cursor/plans/mempool_replication_seed1_6aa9c3e1.plan.md)
> §"Trademark sanitization checklist".

## File index

| File | Purpose |
|---|---|
| [`bootstrap-fork.sh`](bootstrap-fork.sh) | One-shot bootstrap: clone upstream, apply brand-strip codemod + B3Chain patches, push `github.com/b3chain/explorer-ng@b3chain-main` |
| [`install.sh`](install.sh) | Install on seed1: deps, MariaDB, build, systemd, nginx, run tm-audit |
| [`verify.sh`](verify.sh) | Smoke tests after install (RPC tip equality, REST 200, WS upgrade, tm-audit) |
| [`tools/tm-audit.sh`](tools/tm-audit.sh) | Trademark grep audit; CI required check + pre-commit hook + post-build gate |
| [`tools/strip-upstream-brand.sh`](tools/strip-upstream-brand.sh) | Codemod that purges upstream brand tokens from a fresh clone (used by `bootstrap-fork.sh` and on every upstream rebase) |
| [`patches/0001-b3chain-chain-params.patch`](patches/0001-b3chain-chain-params.patch) | Frontend chain params (B3Chain HRP, magic, genesis, units) |
| [`config/b3chain-config.json.template`](config/b3chain-config.json.template) | Backend runtime config (rendered into `/etc/b3chain/explorer-ng-config.json`) |
| [`config/zmq-snippet.conf`](config/zmq-snippet.conf) | Lines to append to `/etc/b3chain/b3chain.conf` for ZMQ pubs (P2 prereq) |
| [`systemd/b3chain-explorer-ng.service`](systemd/b3chain-explorer-ng.service) | Backend Node.js service unit |
| [`nginx/explorer-ng.conf`](nginx/explorer-ng.conf) | Server block with `/v2/` static + `/v2/api` proxy + WS upgrade |
| [`mariadb-schema.sh`](mariadb-schema.sh) | Bootstrap MariaDB DB + user idempotently |
| [`assets/b3chain-explorer-ng-logo.svg`](assets/b3chain-explorer-ng-logo.svg) | Placeholder B3Chain-only logo (replaces upstream half-block) |

## Quick start (seed1, deploy)

```bash
# As deploy on seed1, with sudo NOPASSWD:
cd /opt/b3chain/b3chain
sudo git fetch b3chain && sudo git reset --hard b3chain/b3chain-main

# 1. ensure b3chaind testnet has ZMQ pubs (P2 prereq, idempotent):
sudo bash contrib/testnet/explorer-ng/install.sh --enable-zmq

# 2. install/upgrade explorer-ng (P0+P1):
sudo bash contrib/testnet/explorer-ng/install.sh

# 3. verify:
sudo bash contrib/testnet/explorer-ng/verify.sh
```

## Phase advance flags

```bash
# Default (P0+P1): core explorer + pending-pool projection + WebSocket.
sudo bash contrib/testnet/explorer-ng/install.sh

# P3 statistics: charts populate over hours; off by default until indexer ready.
sudo bash contrib/testnet/explorer-ng/install.sh --enable-stats

# P5 mining indexer + 7 mining charts + /v2/mining dashboard:
sudo bash contrib/testnet/explorer-ng/install.sh --enable-mining

# P7 block audit + health (heavy):
sudo bash contrib/testnet/explorer-ng/install.sh --enable-audit

# All toggleable phases at once:
sudo bash contrib/testnet/explorer-ng/install.sh --enable-stats --enable-mining --enable-audit
```

P8 Lightning is parked until B3Chain LN exists (no `b3chain-lnd` yet); see
plan §P8 for prereqs.

## Cutover (run after parity acceptance)

```bash
sudo bash contrib/testnet/explorer-ng/install.sh --cutover
```

Moves `/` to explorer-ng and demotes btc-rpc-explorer to `/legacy/` for one
release cycle.

## Local fork bootstrap (developer machine, run once)

```bash
cd ~/work
bash /path/to/b3chain/contrib/testnet/explorer-ng/bootstrap-fork.sh \
    --upstream-rev master \
    --target-org b3chain \
    --target-repo explorer-ng
```

This clones upstream, runs `tools/strip-upstream-brand.sh`, applies the
B3Chain chain-params patch, runs `tools/tm-audit.sh` (must pass), then
pushes a single squashed commit to `git@github.com:b3chain/explorer-ng.git`.
After this, seed1's `install.sh` clones from `b3chain/explorer-ng`.
